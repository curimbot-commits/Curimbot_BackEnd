"""
Endpoints para el asistente de voz.

GET  /api/v1/voice/token    — Token efímero de Gemini Live (la API key no sale del servidor)
POST /api/v1/voice/context  — Fragmentos RAG relevantes para la query
"""

import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from app.core.rate_limit import rate_limit
from app.core.config import settings
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.services.Curim.voice_rag_service import get_voice_rag_service
from app.db.database import SessionLocal
from app.services.auth_service import get_current_user
from typing import List
from datetime import datetime, timedelta, timezone
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/voice", tags=["voice"])


# ─────────────────────────────────────────────────────────────────────────────
# Dependencias
# ─────────────────────────────────────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────

class VoiceTokenResponse(BaseModel):
    token: str = Field(..., description="Token efímero de Gemini Live (auth_tokens/...)")
    expire_time: datetime = Field(..., description="Caducidad del token (UTC)")
    model: str = Field(..., description="Modelo de Gemini Live que permite el token")


class ContextRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000,
                       description="Transcripción de lo que dijo el usuario")


class ContextResponse(BaseModel):
    context: str | None = Field(
        None,
        description="Fragmentos relevantes de documentos, o null si no hay matches"
    )
    found: bool = Field(
        False,
        description="True si se encontró contexto relevante"
    )
    sources_info: List[dict] = Field(
        default_factory=list,
        description="Documentos usados: [{document_id, filename}] (para el historial)"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

# Modelo de Gemini Live que el token permite usar (bloqueado en el token).
GEMINI_LIVE_MODEL = settings.GEMINI_LIVE_MODEL
# Ventana para abrir la sesión y vida máxima de la sesión abierta.
VOICE_TOKEN_NEW_SESSION_SECONDS = 60
VOICE_TOKEN_TTL_MINUTES = 30


async def _create_auth_token(config: types.CreateAuthTokenConfig):
    """Crea un token efímero en Gemini (solo disponible en v1alpha)."""
    client = genai.Client(
        api_key=os.getenv("GEMINI_API_KEY"),
        http_options=types.HttpOptions(api_version="v1alpha"),
    )
    return await client.aio.auth_tokens.create(config=config)


@router.get("/token", response_model=VoiceTokenResponse, dependencies=[Depends(rate_limit(10, 60))])
async def get_voice_token(current_user=Depends(get_current_user)):
    """
    Emite un token efímero de Gemini Live para el usuario autenticado.

    La API key real nunca sale del servidor. El token sirve para abrir UNA
    sesión (uses=1) en el primer minuto, caduca a los 30 minutos y solo
    permite el modelo GEMINI_LIVE_MODEL. El frontend pide uno nuevo en cada
    (re)conexión y conecta a BidiGenerateContentConstrained?access_token=...
    """
    if not os.getenv("GEMINI_API_KEY"):
        logger.error("GEMINI_API_KEY no configurada")
        raise HTTPException(status_code=503, detail="Servicio de voz no disponible")

    now = datetime.now(timezone.utc)
    expire_time = now + timedelta(minutes=VOICE_TOKEN_TTL_MINUTES)
    config = types.CreateAuthTokenConfig(
        uses=1,
        expire_time=expire_time,
        new_session_expire_time=now + timedelta(seconds=VOICE_TOKEN_NEW_SESSION_SECONDS),
        live_connect_constraints=types.LiveConnectConstraints(model=GEMINI_LIVE_MODEL),
        lock_additional_fields=[],  # bloquea solo el modelo; el cliente define el resto
    )

    try:
        token = await _create_auth_token(config)
    except Exception as e:
        logger.error(f"Error creando token efímero de Gemini: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="Servicio de voz no disponible")

    if not getattr(token, "name", None):
        logger.error("Gemini devolvió un token efímero sin nombre")
        raise HTTPException(status_code=503, detail="Servicio de voz no disponible")

    return VoiceTokenResponse(token=token.name, expire_time=expire_time, model=GEMINI_LIVE_MODEL)


@router.post("/context", response_model=ContextResponse, dependencies=[Depends(rate_limit(60, 60))])
def get_voice_context(
    request: ContextRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Busca fragmentos relevantes en los documentos del usuario
    para enriquecer la respuesta del asistente de voz.

    El frontend llama este endpoint cada vez que Gemini transcribe
    lo que dijo el usuario, antes de que Gemini procese la respuesta.
    """
    try:
        rag = get_voice_rag_service()
        context, sources_info = rag.retrieve_context_with_sources(
            query=request.query,
            user_id=current_user.id,
            db=db,
        )

        return ContextResponse(
            context=context,
            found=context is not None,
            sources_info=sources_info,
        )

    except Exception as e:
        logger.error(f"[RAG] Error recuperando contexto: {e}", exc_info=True)
        # No fallar la conversación por error de RAG
        return ContextResponse(context=None, found=False)
