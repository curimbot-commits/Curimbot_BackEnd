"""
Endpoints para el asistente de voz.

GET  /api/v1/voice/token    — API key de Gemini para conexión directa
POST /api/v1/voice/context  — Fragmentos RAG relevantes para la query
"""

from app.models.auth_models import User
from app.services.handlers.log_activity import LogAIInteractionHandler
import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.services.Curim.voice_rag_service import get_voice_rag_service
from app.db.database import SessionLocal
from app.services.auth_service import get_current_user
from app.enums.enums import AIChannel, AIInteractionStatus
from typing import List, Optional
from datetime import datetime

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
    api_key: str


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

@router.get("/token", response_model=VoiceTokenResponse)
async def get_voice_token(current_user=Depends(get_current_user)):
    """
    Devuelve la API key de Gemini al usuario autenticado.
    El frontend la usa para conectar directamente a Gemini Live API.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY no configurada")
        raise HTTPException(
            status_code=503,
            detail="Servicio de voz no disponible"
        )
    return VoiceTokenResponse(api_key=api_key)


@router.post("/context", response_model=ContextResponse)
async def get_voice_context(
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
async def log_voice_interaction(
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