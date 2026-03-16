"""
Handler para indexación de documentos en Curim.

Indexa documentos en el sistema vectorial después de ser guardados en BD.
Parte de la cadena de procesamiento de documentos.

Cadena de handlers:
    ValidateFileHandler → ExtractTextHandler → [EncryptFileHandler] →
    SaveToDBHandler → IndexCurimHandler → LogActivityHandler

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

logger = logging.getLogger(__name__)

# Configuración (mover a settings en producción)
MIN_TEXT_LENGTH = 50


class IndexCurimHandler(DocumentHandler):
    """
    Handler para indexación en Curim.
    
    Toma documento guardado en BD e indexa su contenido en la base de datos
    vectorial para búsqueda semántica. Crea embeddings y registra metadatos.
    
    Principio clave: "Indexación es una mejora, no un requisito"
    Si falla indexación, el upload continúa exitoso.
    
    Atributos de contexto modificados:
        - context.curim_indexed: bool (True si indexado exitosamente)
        - context.curim_chunks: int (cantidad de chunks creados)
        - context.curim_error: str (mensaje de error si aplica)
    """
    
    async def _handle(self, context: DocumentContext) -> None:
        """
        Indexa documento en Curim de forma asíncrona.
        
        Args:
            context: Contexto con documento guardado en BD
            
        Comportamiento:
            - Si falla, NO propaga excepción
            - Documento permanece en BD
            - Se registra error para auditoría
        """
        correlation_id = getattr(context, 'correlation_id', 'unknown')
        
        # Validaciones tempranas
        if not self._should_index(context, correlation_id):
            return
        
        # Intentar indexación con manejo de errores
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
            self._handle_indexing_error(
                context,
                str(e),
                correlation_id
            )
    
    def _should_index(self, context: DocumentContext, correlation_id: str) -> bool:
        """
        Valida si el documento debe ser indexado.
        
        Args:
            context: Contexto del documento
            correlation_id: ID de correlación para trazabilidad
            
        Returns:
            True si debe indexarse, False en caso contrario
            
        Logs:
            - DEBUG: cuando no hay documento
            - WARNING: cuando texto es insuficiente
        """
        # Verificar documento existe
        if not context.document:
            logger.debug(
                f"[{correlation_id}] No document available for Curim indexing"
            )
            return False
        
        document = context.document
        text = document.text or ""
        text_length = len(text.strip())
        
        # Validar texto suficiente
        if text_length < MIN_TEXT_LENGTH:
            logger.warning(
                f"[{correlation_id}] Document {document.id} ({document.filename}) "
                f"has insufficient text for indexing: {text_length} chars "
                f"(minimum: {MIN_TEXT_LENGTH})"
            )
            
            # Marcar como no indexado
            context.curim_indexed = False
            context.curim_chunks = 0
            
            return False
        
        return True
    
    async def _index_document(self, context: DocumentContext, correlation_id: str) -> None:
        """
        Ejecuta la indexación del documento.
        """
        document = context.document
        start_time = time.time()
        
        logger.info(
            f"[{correlation_id}] Starting Curim indexing for document {document.id} "
            f"({document.filename}): {len(document.text)} chars"
        )
        
        # Importación dinámica para evitar dependencias circulares
        from app.services.Curim.document_processor import DocumentProcessor
        
        # Procesar e indexar documento
        processor = DocumentProcessor()
        
        try:
            # El método process_and_index es síncrono, ejecutar en thread pool
            chunks_count = await asyncio.to_thread(
                processor.process_and_index,
                document
            )
            
            # Guardar registro de indexación en BD
            self._save_index_record(context, document.id, chunks_count)
            
            # Actualizar contexto
            context.curim_indexed = True
            context.curim_chunks = chunks_count
            
            # Log éxito con métricas
            duration = time.time() - start_time
            logger.info(
                f"[{correlation_id}] Document {document.id} successfully indexed: "
                f"{chunks_count} chunks created in {duration:.2f}s "
                f"({chunks_count/duration:.1f} chunks/s)"
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
        """
        Guarda registro de indexación exitosa en BD.
        
        Args:
            context: Contexto con sesión de BD
            document_id: ID del documento indexado
            chunks_count: Cantidad de chunks creados
            
        Raises:
            Exception: Si falla guardado (con rollback automático)
            
        Logs:
            - DEBUG: confirmación de guardado
        """
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
        """
        Maneja errores de indexación sin interrumpir el upload.
        
        Args:
            context: Contexto del documento
            error_msg: Mensaje de error
            correlation_id: ID de correlación
            is_import_error: True si es error de importación
            
        Comportamiento:
            - Registra error en logs (ERROR level)
            - Intenta guardar error en BD para auditoría
            - Actualiza contexto con estado de fallo
            - NO propaga excepción (upload debe continuar)
            
        Logs:
            - ERROR: error principal de indexación
            - ERROR: si falla guardado de error en BD
        """
        # Obtener ID de documento de forma segura
        doc_id = context.document.id if context.document else 'unknown'
        doc_name = context.document.filename if context.document else 'unknown'
        
        # Log error principal
        if is_import_error:
            logger.error(
                f"[{correlation_id}] Curim module import failed for document "
                f"{doc_id} ({doc_name}): {error_msg}"
            )
        else:
            logger.error(
                f"[{correlation_id}] Indexing failed for document {doc_id} "
                f"({doc_name}): {error_msg}",
                exc_info=False  # No stack trace completo para evitar spam
            )
        
        # Intentar registrar error en BD para auditoría
        if context.document:
            try:
                error_record = CurimDocumentIndex(
                    document_id=context.document.id,
                    is_indexed=False,
                    chunks_count=0,
                    error_message=error_msg[:500]  # Limitar longitud
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
        
        # Actualizar contexto con estado de error
        context.curim_indexed = False
        context.curim_error = error_msg[:200]  