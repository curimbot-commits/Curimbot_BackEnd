"""
Servicio principal de Curim - Asistente inteligente con caché dual.

Orquesta toda la funcionalidad de búsqueda y respuesta en documentos.
"""

from PIL.Image import logger
import json
import logging
import time
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.enums.enums import AIChannel, AIInteractionStatus
from app.models.models import (
    CurimConversation,
    CurimDocumentIndex,
    CurimMessage,
    Document,
    User,
)
from app.services.Curim.cache_manager import CacheManager
from app.services.Curim.document_processor import DocumentProcessor
from app.services.Curim.semantic_cache import SemanticCache
from app.services.Curim.voice_rag_service import get_rag_engine
from app.services.handlers.log_activity import LogAIInteractionHandler


def accessible_documents(
    db: Session,
    user_id: int,
    document_ids: Optional[List[int]] = None,
) -> List[Document]:
    """
    Documentos en los que el asistente (texto y voz) puede buscar para un
    usuario: los suyos y los públicos (los que sube un admin). Misma regla
    que la descarga de documentos.
    """
    query = db.query(Document).filter(
        (Document.uploaded_by == user_id) | (Document.is_public == 1)
    )
    if document_ids:
        query = query.filter(Document.id.in_(document_ids))
    return query.all()


class CurimService:
    """
    Servicio principal de Curim.
    """

    def __init__(self):
        self.rag_engine = get_rag_engine()
        self.cache_manager = CacheManager()
        self.semantic_cache = SemanticCache(
            similarity_threshold=0.85,
            embedding_model=self.rag_engine.embeddings,
        )
        self.document_processor = DocumentProcessor(
            rag_engine=self.rag_engine
        )

    def ask_question(
        self,
        db: Session,
        user: User,
        question: str,
        document_ids: Optional[List[int]] = None,
        use_cache: bool = True,
        conversation_id: Optional[int] = None,
    ) -> dict:
        start_time = time.time()

        if use_cache:
            cached_response = self.cache_manager.get(user.id, question)
            if cached_response:
                conv_id = self._save_to_history(
                    db, user.id, question,
                    cached_response["answer"],
                    confidence=cached_response.get("confidence", 1.0),
                    sources=cached_response.get("sources", []),
                    sources_info=cached_response.get("sources_info", []),
                    from_cache=True,
                    processing_time_ms=0,
                    conversation_id=conversation_id,
                )
                return {
                    "answer": cached_response["answer"],
                    "confidence": cached_response.get("confidence", 1.0),
                    "sources": cached_response.get("sources", []),
                    "sources_info": cached_response.get("sources_info", []),
                    "from_cache": True,
                    "processing_time_ms": round((time.time() - start_time) * 1000, 2),
                    "conversation_id": conv_id,
                }

            semantic_response = self.semantic_cache.get(user.id, question)
            if semantic_response:
                conv_id = self._save_to_history(
                    db, user.id, question,
                    semantic_response["answer"],
                    confidence=semantic_response.get("confidence", 1.0),
                    sources=semantic_response.get("sources", []),
                    sources_info=semantic_response.get("sources_info", []),
                    from_cache=True,
                    processing_time_ms=0,
                    conversation_id=conversation_id,
                )
                return {
                    "answer": semantic_response["answer"],
                    "confidence": semantic_response.get("confidence", 1.0),
                    "sources": semantic_response.get("sources", []),
                    "sources_info": semantic_response.get("sources_info", []),
                    "from_cache": True,
                    "processing_time_ms": round((time.time() - start_time) * 1000, 2),
                    "conversation_id": conv_id,
                }

        user_documents = self._get_user_documents(db, user.id, document_ids)

        try:
            answer, confidence, source_ids, sources_info = self.rag_engine.query(
                question=question,
                documents=user_documents,
            )
        except Exception as e:
            logging.exception(f"Error en RAGEngine: {e}")
            LogAIInteractionHandler.log(
                db=db,
                user_id=user.id,
                question=question,
                answer=None,
                channel=AIChannel.text,
                confidence=None,
                status=AIInteractionStatus.error,
                error_message=str(e),
                processing_time_ms=int((time.time() - start_time) * 1000),
                from_cache=False,
                conversation_id=conversation_id,
            )
            raise

        processing_time = round((time.time() - start_time) * 1000, 2)

        if use_cache and confidence > 0.7:
            self.cache_manager.set(
                user_id=user.id,
                question=question,
                answer=answer,
                confidence=confidence,
                sources=source_ids,
                sources_info=sources_info,
            )
            self.semantic_cache.set(
                user_id=user.id,
                question=question,
                answer=answer,
                confidence=confidence,
                sources=source_ids,
                sources_info=sources_info,
            )

        conv_id = self._save_to_history(
            db, user.id, question, answer,
            confidence=confidence,
            sources=source_ids,
            sources_info=sources_info,
            from_cache=False,
            processing_time_ms=processing_time,
            conversation_id=conversation_id,
        )

        return {
            "answer": answer,
            "confidence": confidence,
            "sources": source_ids,
            "sources_info": sources_info,
            "from_cache": False,
            "processing_time_ms": processing_time,
            "conversation_id": conv_id,
        }

    def _get_user_documents(
        self,
        db: Session,
        user_id: int,
        document_ids: Optional[List[int]] = None,
    ) -> List[Document]:
        return accessible_documents(db, user_id, document_ids)

    def _save_to_history(
        self,
        db: Session,
        user_id: int,
        question: str,
        answer: str,
        confidence: float,
        sources: List[int],
        sources_info: List[dict],
        from_cache: bool,
        processing_time_ms: float,
        conversation_id: Optional[int] = None,
    ) -> int:
        if conversation_id:
            conversation = (
                db.query(CurimConversation)
                .filter(
                    CurimConversation.id == conversation_id,
                    CurimConversation.user_id == user_id,
                )
                .first()
            )
            if not conversation:
                conversation = CurimConversation(
                    user_id=user_id,
                    title=(question[:50] + "...") if len(question) > 50 else question,
                )
                db.add(conversation)
                db.flush()
        else:
            conversation = CurimConversation(
                user_id=user_id,
                title=(question[:50] + "...") if len(question) > 50 else question,
            )
            db.add(conversation)
            db.flush()

        user_message = CurimMessage(
            conversation_id=conversation.id,
            role="user",
            content=question,
            created_at=datetime.now(timezone.utc),
        )
        db.add(user_message)

        assistant_message = CurimMessage(
            conversation_id=conversation.id,
            role="assistant",
            content=answer,
            confidence=int(confidence * 100),
            sources=json.dumps(sources),
            sources_info=json.dumps(sources_info),
            from_cache=from_cache,
            processing_time_ms=int(processing_time_ms),
            created_at=datetime.now(timezone.utc),
        )
        db.add(assistant_message)
        db.commit()

        LogAIInteractionHandler.log(
            db=db,
            user_id=user_id,
            question=question,
            answer=answer,
            channel=AIChannel.text,
            confidence=confidence,
            # Sin fuentes = no se encontró contexto en los documentos
            status=AIInteractionStatus.success if sources else AIInteractionStatus.no_context,
            sources=sources,
            sources_info=sources_info,
            processing_time_ms=int(processing_time_ms),
            from_cache=from_cache,
            conversation_id=conversation.id,
        )

        return conversation.id

    def get_conversation_history(
        self,
        db: Session,
        user_id: int,
        conversation_id: Optional[int] = None,
        limit: int = 50,
    ) -> List[dict]:
        if conversation_id:
            messages = (
                db.query(CurimMessage)
                .join(CurimConversation)
                .filter(
                    CurimConversation.id == conversation_id,
                    CurimConversation.user_id == user_id,
                )
                .order_by(CurimMessage.created_at.asc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": msg.id,
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": msg.created_at.isoformat(),
                    "sources": json.loads(msg.sources) if msg.sources else [],
                    "sources_info": json.loads(msg.sources_info) if msg.sources_info else [],
                    "confidence": (msg.confidence / 100.0) if msg.confidence else None,
                    "from_cache": msg.from_cache,
                }
                for msg in messages
            ]

        conversations = (
            db.query(CurimConversation)
            .filter(CurimConversation.user_id == user_id)
            .order_by(CurimConversation.updated_at.desc())
            .limit(10)
            .all()
        )
        return [
            {
                "conversation_id": conv.id,
                "title": conv.title,
                "created_at": conv.created_at.isoformat(),
                "updated_at": conv.updated_at.isoformat(),
                "message_count": len(conv.messages),
            }
            for conv in conversations
        ]

    def sync_documents(
        self,
        db: Session,
        user_id: int,
        document_ids: Optional[List[int]] = None,
        force_reindex: bool = False,
    ) -> dict:
        start_time = time.time()

        documents = self._get_user_documents(db, user_id, document_ids)

        processed_count = 0
        indexed_count = 0
        errors = []

        for doc in documents:
            try:
                index_record = (
                    db.query(CurimDocumentIndex)
                    .filter(CurimDocumentIndex.document_id == doc.id)
                    .first()
                )

                if index_record and index_record.is_indexed and not force_reindex:
                    processed_count += 1
                    continue

                chunks_count = self.document_processor.process_and_index(doc)

                if not index_record:
                    index_record = CurimDocumentIndex(
                        document_id=doc.id,
                        is_indexed=True,
                        chunks_count=chunks_count,
                        last_indexed_at=datetime.now(timezone.utc),
                    )
                    db.add(index_record)
                else:
                    index_record.is_indexed = True
                    index_record.chunks_count = chunks_count
                    index_record.last_indexed_at = datetime.now(timezone.utc)
                    index_record.error_message = None

                processed_count += 1
                indexed_count += 1

            except Exception as e:
                errors.append(f"Error procesando documento {doc.id}: {str(e)}")
                index_record = (
                    db.query(CurimDocumentIndex)
                    .filter(CurimDocumentIndex.document_id == doc.id)
                    .first()
                )
                if index_record:
                    index_record.error_message = str(e)
                else:
                    index_record = CurimDocumentIndex(
                        document_id=doc.id,
                        is_indexed=False,
                        error_message=str(e),
                    )
                    db.add(index_record)

        db.commit()

        # Invalidar cachés del usuario si se indexó algo nuevo o cambió
        if indexed_count > 0:
            try:
                self.cache_manager.clear(user_id=user_id)

                keys_to_delete = [
                    k for k, v in self.semantic_cache.cache.items()
                    if v.get("user_id") == user_id
                ]
                for k in keys_to_delete:
                    del self.semantic_cache.cache[k]
                if keys_to_delete:
                    self.semantic_cache._save_cache()

                logger.info(
                    f"Caché invalidado para usuario {user_id} tras indexar "
                    f"{indexed_count} documento(s)"
                )
            except Exception as e:
                logger.warning(
                    f"No se pudo invalidar caché para usuario {user_id}: {e}"
                )

        processing_time = round((time.time() - start_time) * 1000, 2)

        return {
            "success": len(errors) == 0,
            "documents_processed": processed_count,
            "documents_indexed": indexed_count,
            "errors": errors,
            "processing_time_ms": processing_time,
        }

    def get_status(self, db: Session, user_id: int) -> dict:
        indexed_count = (
            db.query(CurimDocumentIndex)
            .join(Document)
            .filter(
                Document.uploaded_by == user_id,
                CurimDocumentIndex.is_indexed == True,
            )
            .count()
        )

        last_sync = (
            db.query(CurimDocumentIndex)
            .join(Document)
            .filter(Document.uploaded_by == user_id)
            .order_by(CurimDocumentIndex.last_indexed_at.desc())
            .first()
        )

        cache_stats = self.cache_manager.get_stats(user_id)

        semantic_cache_size = len([
            key for key, value in self.semantic_cache.cache.items()
            if value.get("user_id") == user_id
        ])

        total_requests = max(cache_stats.get("total_entries", 1), 1)
        hit_rate = cache_stats.get("total_hits", 0) / total_requests

        return {
            "is_ready": indexed_count > 0,
            "documents_indexed": indexed_count,
            "cache_size": self.cache_manager.get_size(user_id),
            "semantic_cache_size": semantic_cache_size,
            "cache_hit_rate": hit_rate,
            "last_sync": last_sync.last_indexed_at if last_sync else None,
            "vector_db_size_mb": self.rag_engine.get_db_size(),
        }

    def clear_all_cache(self, user_id: Optional[int] = None):
        self.cache_manager.clear(user_id)
        if user_id:
            keys_to_delete = [
                key for key, value in self.semantic_cache.cache.items()
                if value.get("user_id") == user_id
            ]
            for key in keys_to_delete:
                del self.semantic_cache.cache[key]
            self.semantic_cache._save_cache()
        else:
            self.semantic_cache.cache = {}
            self.semantic_cache._save_cache()

    def on_document_deleted(self, document_id: int) -> None:
        """
        Quita los fragmentos del documento del índice y vacía las cachés de
        respuestas (un documento público afecta a todos los usuarios).
        """
        self.rag_engine.delete_document_chunks(document_id)
        self.clear_all_cache()

    def on_documents_indexed(self) -> None:
        """Tras indexar documentos nuevos, las respuestas cacheadas quedan obsoletas."""
        self.clear_all_cache()

_curim_service: Optional[CurimService] = None


def get_curim_service() -> CurimService:
    """Instancia única: una sola caché exacta y semántica para toda la app."""
    global _curim_service
    if _curim_service is None:
        _curim_service = CurimService()
    return _curim_service
