# app/services/handlers/validate_file.py
from fastapi import HTTPException
from app.enums.enums import FileType
from .base import DocumentHandler, DocumentContext
import logging
# ValidateFileHandler.py

class ValidateFileHandler(DocumentHandler):
    async def _handle(self, context: DocumentContext):
        filename = context.filename

        if not filename or '.' not in filename:
            logging.error("[ValidateFileHandler] Archivo sin extensión válida")
            raise HTTPException(status_code=400, detail="El archivo no tiene una extensión válida.")

        ext = filename.rsplit('.', 1)[-1].lower()
        context.extension = ext

        try:
            file_type_enum = FileType(ext)
        except ValueError:
            logging.error(f"[ValidateFileHandler] Tipo de archivo no soportado: .{ext}")
            raise HTTPException(status_code=400, detail=f"Tipo de archivo no soportado: .{ext}")

        context.file_type = file_type_enum

        if not context.mimetype:
            if ext == 'pdf':
                context.mimetype = 'application/pdf'
            elif ext == 'txt':
                context.mimetype = 'text/plain'
            elif ext == 'docx':
                context.mimetype = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            else:
                context.mimetype = 'application/octet-stream'

