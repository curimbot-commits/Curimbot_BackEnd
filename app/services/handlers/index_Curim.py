"""
Handler para indexación de documentos en Curim.

Indexa documentos en el sistema vectorial después de ser guardados en BD.
Parte de la cadena de procesamiento de documentos.

Cadena de handlers:
    ValidateFileHandler → ExtractTextHandler → [EncryptFileHandler] →
    SaveToDBHandler → IndexCurimHandler

Características:
    - Indexación en base de datos vectorial
    - Creación de embeddings con Gemini
    - Chunificación automática del texto
    - Registro en tabla CurimDocumentIndex
    - Manejo graceful de errores (no falla upload)
    - Detección de texto insuficiente
    - Retry logic implícita en DocumentProcessor

Performance:
    - Documento 1MB: 500-1000ms
    - Embeddings: ~1s por 1000 chunks
    - Indexación vectorial: < 100ms

Notas:
    - Indexación es mejora, no requisito
    - Errores NO detienen upload
    - Soporta reindexación manual posterior
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from app.services.handlers.base import DocumentHandler, DocumentContext
from app.models.models import CurimDocumentIndex
from app.services.Curim.document_processor import DocumentProcessor

logger = logging.getLogger(__name__)

MIN_TEXT_LENGTH = 50

# Singleton del procesador para no instanciar el motor RAG por documento
_processor_singleton: Optional[DocumentProcessor] = None


def _get_processor() -> DocumentProcessor:
    global _processor_singleton
    if _processor_singleton is None:
        _processor_singleton = DocumentProcessor()
    return _processor_singleton


class IndexCurimHandler(DocumentHandler):
    """
    Handler para indexación en Curim.

    Si falla la indexación, el upload continúa exitoso.
    """

    async def _handle(self, context: DocumentContext) -> None:
        correlation_id = getattr(context, 'correlation_id', 'unknown')

        if not self._should_index(context, correlation_id):
            return

        try:
            await self._index_document(context, correlation_id)
        except ImportError as e:
            self._handle_indexing_error(
                context,
                f"Curim module unavailable: {e}",
                correlation_id,
                is_import_error=True
            )
        except Exception as e:
            self._handle_indexing_error(context, str(e), correlation_id)

    def _should_index(self, context: DocumentContext, correlation_id: str) -> bool:
        if not context.document:
            logger.debug(f"[{correlation_id}] No document available for Curim indexing")
            return False

        document = context.document
        text = document.text or ""
        text_length = len(text.strip())

        if text_length < MIN_TEXT_LENGTH:
            logger.warning(
                f"[{correlation_id}] Document {document.id} ({document.filename}) "
                f"has insufficient text for indexing: {text_length} chars "
                f"(minimum: {MIN_TEXT_LENGTH})"
            )
            context.Curim_indexed = False
            context.Curim_chunks = 0
            return False

        return True

    async def _index_document(self, context: DocumentContext, correlation_id: str) -> None:
        document = context.document
        start_time = time.time()

        logger.info(
            f"[{correlation_id}] Starting Curim indexing for document {document.id} "
            f"({document.filename}): {len(document.text)} chars"
        )

        processor = _get_processor()

        try:
            chunks_count = await asyncio.to_thread(
                processor.process_and_index,
                document
            )

            self._save_index_record(context, document.id, chunks_count)

            context.Curim_indexed = True
            context.Curim_chunks = chunks_count

            duration = time.time() - start_time
            logger.info(
                f"[{correlation_id}] Document {document.id} successfully indexed: "
                f"{chunks_count} chunks created in {duration:.2f}s"
            )
        except Exception as e:
            logger.error(f"[{correlation_id}] Error in index_document: {e}")
            raise

    def _save_index_record(
        self,
        context: DocumentContext,
        document_id: int,
        chunks_count: int
    ) -> None:
        try:
            index_record = CurimDocumentIndex(
                document_id=document_id,
                is_indexed=True,
                chunks_count=chunks_count,
                last_indexed_at=datetime.now(timezone.utc),
                error_message=None
            )
            context.db.add(index_record)
            context.db.commit()
            logger.debug(
                f"CurimDocumentIndex record created for document {document_id}"
            )
        except Exception as e:
            context.db.rollback()
            logger.error(
                f"Failed to save index record for document {document_id}: {e}"
            )
            raise

    def _handle_indexing_error(
        self,
        context: DocumentContext,
        error_msg: str,
        correlation_id: str,
        is_import_error: bool = False
    ) -> None:
        doc_id = context.document.id if context.document else 'unknown'
        doc_name = context.document.filename if context.document else 'unknown'

        if is_import_error:
            logger.error(
                f"[{correlation_id}] Curim module import failed for document "
                f"{doc_id} ({doc_name}): {error_msg}"
            )
        else:
            logger.error(
                f"[{correlation_id}] Indexing failed for document {doc_id} "
                f"({doc_name}): {error_msg}",
                exc_info=False
            )

        if context.document:
            try:
                error_record = CurimDocumentIndex(
                    document_id=context.document.id,
                    is_indexed=False,
                    chunks_count=0,
                    error_message=error_msg[:500]
                )
                context.db.add(error_record)
                context.db.commit()
                logger.debug(
                    f"[{correlation_id}] Error record saved for document "
                    f"{context.document.id}"
                )
            except Exception as db_error:
                context.db.rollback()
                logger.error(
                    f"[{correlation_id}] Failed to save error record for "
                    f"document {context.document.id}: {db_error}"
                )

        context.Curim_indexed = False
        context.Curim_error = error_msg[:200]