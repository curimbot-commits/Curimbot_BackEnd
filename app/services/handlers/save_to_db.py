# app/services/handlers/save_to_db.py
import logging
from app.db.crud import crud
from app.schemas.document_schemas import DocumentCreate
from .base import DocumentHandler, DocumentContext
from fastapi import HTTPException

# SaveToDBHandler.py - VERSIÓN CORREGIDA
class SaveToDBHandler(DocumentHandler):
    async def _handle(self, context: DocumentContext):
        try:
            if context.file_type is None:
                raise HTTPException(status_code=400, detail="Tipo de archivo no definido en contexto")

            file_type_value = (
                context.file_type.value if hasattr(context.file_type, "value") else context.file_type
            )

            if not isinstance(file_type_value, str) or file_type_value not in ("pdf", "docx", "txt"):
                raise HTTPException(status_code=400, detail=f"Tipo de archivo inválido: {file_type_value}")

            if not context.user or not context.db:
                raise HTTPException(status_code=400, detail="Usuario o base de datos no definidos en contexto")

            # PROTECCIÓN: Verificar si el documento ya fue creado
            if context.document is not None:
                logging.warning(f"[SaveToDBHandler] Documento ya existe con ID {context.document.id}, saltando creación")
                return  # Salir sin llamar al siguiente (la clase base lo hará)

            encrypted_content = getattr(context, 'encrypted_content', b'')
            if encrypted_content is None:
                encrypted_content = b''
            if not isinstance(encrypted_content, bytes):
                raise HTTPException(status_code=400, detail="El contenido encriptado debe ser bytes")

            if not context.filename or not isinstance(context.filename, str):
                raise HTTPException(status_code=400, detail="Nombre de archivo inválido")

            mimetype = getattr(context, 'mimetype', 'application/octet-stream')
            if not isinstance(mimetype, str) or not mimetype:
                mimetype = 'application/octet-stream'

            size = getattr(context, 'size', len(context.content) if context.content else 0)
            text = context.text or ''

            blob_content = encrypted_content if encrypted_content else context.content

            is_public = 1 if context.user.is_admin else 0
            
            doc_data = DocumentCreate(
                filename=context.filename,
                mimetype=mimetype,
                size=size,
                text=text,
                blob_enc=blob_content,
                uploaded_by=context.user.id,
                is_public=is_public
            )

            logging.info(f"[SaveToDBHandler] Creando documento con file_type: {context.file_type}")
            
            context.document = crud.create_document(
                db=context.db,
                document=doc_data,
                file_type=context.file_type
            )
            
            if not context.document:
                raise HTTPException(status_code=500, detail="No se pudo crear el documento en la base de datos")
            
            try:
                context.db.commit()
                context.db.refresh(context.document)
                logging.info(f"[SaveToDBHandler] Documento creado y confirmado: ID={context.document.id}")
            except Exception as commit_error:
                context.db.rollback()
                logging.exception(f"[SaveToDBHandler] Error en commit: {commit_error}")
                raise HTTPException(status_code=500, detail="Error al confirmar documento en base de datos")

        except HTTPException:
            raise
        except Exception as e:
            logging.exception(f"Error guardando documento en BD: {e}")
            raise HTTPException(status_code=500, detail="Error al guardar en base de datos")
        