"""
Procesador de documentos para Curim.

Maneja extracción de texto, validación, chunificación e indexación
de documentos en la base de datos vectorial para búsqueda semántica.

Flow:
    1. Documento se sube (con texto extraído)
    2. DocumentProcessor.validate_document() verifica
    3. DocumentProcessor.process_and_index() chunifica e indexa
    4. Se crea CurimDocumentIndex en BD
    5. Documento es searchable en Curim

Supported formats:
    - PDF
    - DOCX (Word)
    - DOC (Word legacy)
    - TXT (plain text)

Typical usage:
    processor = DocumentProcessor()
    if processor.validate_document(doc):
        chunks = processor.process_and_index(doc)
"""

import logging
from typing import Optional, TYPE_CHECKING

from app.models.models import Document

if TYPE_CHECKING:
    from app.services.Curim.rag_engine import VoiceRAGEngine

logger = logging.getLogger(__name__)


class ValidationResult:
    """Resultado de validación con detalles."""

    def __init__(self, is_valid: bool, reason: Optional[str] = None):
        self.is_valid = is_valid
        self.reason = reason

    def __bool__(self) -> bool:
        return self.is_valid

    def __str__(self) -> str:
        if self.is_valid:
            return "Valid document"
        return f"Invalid document: {self.reason}"


class DocumentProcessor:
    """
    Procesador de documentos para indexación en Curim.

    Usa el VoiceRAGEngine singleton para evitar cargar el modelo de
    embeddings y el cliente Gemini una vez por documento.
    """

    MIN_TEXT_LENGTH = 50
    SUPPORTED_TYPES = ['pdf', 'txt', 'docx', 'doc']

    def __init__(self, rag_engine: Optional["VoiceRAGEngine"] = None):
        if rag_engine is not None:
            self.rag_engine = rag_engine
        else:
            # Import diferido: evita cargar Gemini/HuggingFace en import time
            # y garantiza que se reutiliza el singleton del motor.
            from app.services.Curim.voice_rag_service import get_rag_engine
            self.rag_engine = get_rag_engine()
        logger.info("DocumentProcessor initialized (engine id=%s)", id(self.rag_engine))

    def process_and_index(self, document: Document) -> int:
        """Procesar documento e indexar en vectorstore."""
        validation = self.validate_document(document, raise_on_invalid=False)
        if not validation:
            raise ValueError(
                f"Cannot index document {document.id}: {validation.reason}"
            )

        try:
            chunks_count = self.rag_engine.index_document(document)
            logger.info(
                f"Document {document.id} ({document.filename}) "
                f"indexed successfully with {chunks_count} chunks"
            )
            return chunks_count
        except Exception as e:
            logger.error(
                f"Failed to index document {document.id}: {str(e)}",
                exc_info=True
            )
            raise

    def validate_document(
        self,
        document: Document,
        raise_on_invalid: bool = False
    ) -> ValidationResult:
        """Validar que un documento sea procesable."""
        try:
            if not document.text:
                reason = "Document has no text extracted"
                return self._handle_validation_result(False, reason, raise_on_invalid)

            text_length = len(document.text.strip())
            if text_length < self.MIN_TEXT_LENGTH:
                reason = (
                    f"Document text too short: {text_length} chars. "
                    f"Minimum required: {self.MIN_TEXT_LENGTH}"
                )
                return self._handle_validation_result(False, reason, raise_on_invalid)

            if document.file_type.value not in self.SUPPORTED_TYPES:
                reason = (
                    f"Unsupported file type: {document.file_type.value}. "
                    f"Supported types: {', '.join(self.SUPPORTED_TYPES)}"
                )
                return self._handle_validation_result(False, reason, raise_on_invalid)

            if not self._has_meaningful_content(document.text):
                reason = "Document text lacks meaningful content (only whitespace/symbols)"
                return self._handle_validation_result(False, reason, raise_on_invalid)

            logger.debug(f"Document {document.id} passed validation")
            return ValidationResult(True)

        except Exception as e:
            reason = f"Validation error: {str(e)}"
            logger.error(f"Document validation failed: {reason}", exc_info=True)
            return self._handle_validation_result(False, reason, raise_on_invalid)

    def _handle_validation_result(
        self,
        is_valid: bool,
        reason: str,
        raise_on_invalid: bool
    ) -> ValidationResult:
        if not is_valid and raise_on_invalid:
            raise ValueError(reason)
        if not is_valid:
            logger.warning(f"Document validation failed: {reason}")
        return ValidationResult(is_valid, reason)

    def _has_meaningful_content(self, text: str) -> bool:
        stripped = text.strip()
        alpha_count = sum(1 for c in stripped if c.isalpha())
        return alpha_count > 0
