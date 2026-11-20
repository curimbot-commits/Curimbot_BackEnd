"""
Endpoints para el asistente de voz.

GET  /api/v1/voice/token    — Token efímero de Gemini Live (la API key no sale del servidor)
POST /api/v1/voice/context  — Fragmentos RAG relevantes para la query
"""

from app.models.auth_models import User
from app.services.handlers.log_activity import LogAIInteractionHandler
import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from app.core.rate_limit import rate_limit
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.services.Curim.voice_rag_service import get_voice_rag_service
from app.db.database import SessionLocal
from app.services.auth_service import get_current_user
from app.enums.enums import AIChannel, AIInteractionStatus
from typing import List, Optional
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


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

# Modelo de Gemini Live que el token permite usar (bloqueado en el token).
GEMINI_LIVE_MODEL = os.getenv(
    "GEMINI_LIVE_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025"
)
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

    return VoiceTokenResponse(token=token.name, expire_time=expire_time)


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
        context = rag.retrieve_context(
            query=request.query,
            user_id=current_user.id,
            db=db,
        )

        return ContextResponse(
            context=context,
            found=context is not None,
        )

    except Exception as e:
        logger.error(f"[RAG] Error recuperando contexto: {e}", exc_info=True)
        # No fallar la conversación por error de RAG
        return ContextResponse(context=None, found=False)


class VoiceInteractionLogRequest(BaseModel):
    question: str = Field(..., min_length=1)
    answer: Optional[str] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    sources: Optional[List[int]] = None
    sources_info: Optional[List[dict]] = None
    status: AIInteractionStatus = AIInteractionStatus.success
    error_message: Optional[str] = None
    processing_time_ms: Optional[int] = None
    from_cache: bool = False


class VoiceInteractionLogResponse(BaseModel):
    id: int
    status: str


@router.post("/log-interaction", response_model=VoiceInteractionLogResponse)
def log_voice_interaction(
    payload: VoiceInteractionLogRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Registra una interacción de voz del usuario con la IA.

    El frontend llama a este endpoint DESPUÉS de recibir la respuesta
    de Gemini Live (que se genera directo en el navegador). Así podemos
    poblar el historial de interacciones con channel='voice'.
    """
    interaction = LogAIInteractionHandler.log(
        db=db,
        user_id=current_user.id,
        question=payload.question,
        answer=payload.answer,
        channel=AIChannel.voice,
        confidence=payload.confidence,
        status=payload.status,
        error_message=payload.error_message,
        sources=payload.sources,
        sources_info=payload.sources_info,
        processing_time_ms=payload.processing_time_ms,
        from_cache=payload.from_cache,
        conversation_id=None,  # No aplica para voz
    )

    if not interaction:
        raise HTTPException(status_code=500, detail="No se pudo registrar la interacción de voz")

    return VoiceInteractionLogResponse(id=interaction.id, status="ok")