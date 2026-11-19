"""
LogAIInteractionHandler — Registra interacciones del usuario con la IA.

Reemplaza al antiguo LogActivityHandler (que registraba uploads/downloads/views
de documentos). Ahora se invoca desde:
  - CurimService.ask_question()   → channel='text'
  - voice_endpoints.py            → channel='voice'

NO forma parte del chain de subida de documentos.
"""

import json
import logging
from typing import Optional, List

from sqlalchemy.orm import Session

from app.models.models import AIInteractionLog
from app.enums.enums import AIChannel, AIInteractionStatus


class LogAIInteractionHandler:
    """Handler/servicio para registrar interacciones IA en la base de datos."""

    @staticmethod
    def log(
        db: Session,
        user_id: int,
        question: str,
        answer: Optional[str],
        channel: AIChannel = AIChannel.text,
        confidence: Optional[float] = None,
        status: AIInteractionStatus = AIInteractionStatus.success,
        error_message: Optional[str] = None,
        sources: Optional[List[int]] = None,
        sources_info: Optional[List[dict]] = None,
        processing_time_ms: Optional[int] = None,
        from_cache: bool = False,
        conversation_id: Optional[int] = None,
    ) -> Optional[AIInteractionLog]:
        """
        Registra una interacción IA. No falla la operación principal si
        el logging falla — captura la excepción y devuelve None.
        """
        try:
            interaction = AIInteractionLog(
                user_id=user_id,
                question=question,
                answer=answer,
                channel=channel,
                confidence=confidence,
                status=status,
                error_message=error_message,
                sources=json.dumps(sources) if sources is not None else None,
                sources_info=json.dumps(sources_info) if sources_info is not None else None,
                processing_time_ms=int(processing_time_ms) if processing_time_ms is not None else None,
                from_cache=from_cache,
                conversation_id=conversation_id,
            )
            db.add(interaction)
            db.commit()
            db.refresh(interaction)

            logging.info(
                f"✅ Interacción IA registrada: user={user_id} "
                f"channel={channel.value} status={status.value} id={interaction.id}"
            )
            return interaction

        except Exception as e:
            logging.error(f"❌ Error registrando interacción IA: {e}", exc_info=True)
            try:
                db.rollback()
            except Exception:
                pass
            return None