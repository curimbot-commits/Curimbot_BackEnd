"""
VoiceRAGService — wrapper del VoiceRAGEngine para el asistente de voz.

Usa el vectorstore Chroma con embeddings semánticos que ya está indexado
cuando el usuario sube documentos.

Flujo:
    1. Usuario habla -> Gemini transcribe
    2. Frontend envía transcripción -> POST /api/v1/voice/context
    3. VoiceRAGService busca en Chroma los chunks más relevantes del usuario
    4. Retorna contexto formateado para inyectar en Gemini Live
"""

import logging
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session

from app.models.models import Document
from app.services.Curim.rag_engine import VoiceRAGEngine

logger = logging.getLogger(__name__)

_rag_engine: Optional[VoiceRAGEngine] = None


def get_rag_engine() -> VoiceRAGEngine:
    """Retorna la instancia singleton del VoiceRAGEngine."""
    global _rag_engine
    if _rag_engine is None:
        logger.info("[VoiceRAG] Inicializando VoiceRAGEngine...")
        _rag_engine = VoiceRAGEngine()
        logger.info("[VoiceRAG] VoiceRAGEngine listo.")
    return _rag_engine


def _sources_from(retrieved) -> List[dict]:
    """Un registro por documento usado: {document_id, filename}."""
    seen, sources = set(), []
    for doc, _score in retrieved:
        did = doc.metadata.get("document_id")
        if did is None or did in seen:
            continue
        seen.add(did)
        sources.append({"document_id": did, "filename": doc.metadata.get("filename", "Documento")})
    return sources


class VoiceRAGService:
    """
    Conecta el endpoint de voz con el VoiceRAGEngine.
    Recupera contexto semántico de los documentos del usuario.
    """

    def retrieve_context(
        self,
        query: str,
        user_id: int,
        db: Session,
        max_chars: int = 3000,
    ) -> Optional[str]:
        context, _ = self.retrieve_context_with_sources(query, user_id, db, max_chars)
        return context

    def retrieve_context_with_sources(
        self,
        query: str,
        user_id: int,
        db: Session,
        max_chars: int = 3000,
    ) -> Tuple[Optional[str], List[dict]]:
        """
        Busca fragmentos semánticamente relevantes en los documentos del usuario.

        Returns:
            String con contexto formateado, o None si no hay matches.
        """
        if not query or not query.strip():
            return None, []

        # Misma regla que el asistente de texto: propios + públicos (admin)
        from app.services.Curim.Curim_service import accessible_documents
        documents = [d for d in accessible_documents(db, user_id) if d.text]

        if not documents:
            logger.info(f"[VoiceRAG] Usuario {user_id} no tiene documentos indexados.")
            return None, []

        logger.info(
            f"[VoiceRAG] Buscando en {len(documents)} documentos "
            f"para: '{query[:60]}'"
        )

        try:
            engine = get_rag_engine()

            # _retrieve_context_sync devuelve (context_str, [(doc, score), ...])
            context_str, _retrieved = engine._retrieve_context_sync(
                query, documents
            )

            NO_RESULT_RESPONSES = {
                "No hay documentos disponibles.",
                "No se encontró información relevante en los documentos.",
                "No se encontraron fragmentos con suficiente relevancia para responder.",
                "",
            }

            if not context_str or context_str in NO_RESULT_RESPONSES:
                logger.info(
                    f"[VoiceRAG] Sin matches semánticos para: '{query[:60]}'"
                )
                return None, []

            if len(context_str) > max_chars:
                context_str = context_str[:max_chars] + "..."

            logger.info(
                f"[VoiceRAG] Contexto recuperado: {len(context_str)} chars "
                f"de {len(documents)} documento(s) disponibles"
            )
            return context_str, _sources_from(_retrieved)

        except Exception as e:
            logger.error(f"[VoiceRAG] Error en retrieval: {e}", exc_info=True)
            return None, []


_voice_rag_service: Optional[VoiceRAGService] = None


def get_voice_rag_service() -> VoiceRAGService:
    global _voice_rag_service
    if _voice_rag_service is None:
        _voice_rag_service = VoiceRAGService()
    return _voice_rag_service