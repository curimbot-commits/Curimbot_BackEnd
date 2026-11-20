# app/services/handlers/save_to_db.py
import hashlib
import logging
from fastapi import HTTPException

from app.db.crud import crud
from app.models.models import Document
from app.schemas.document_schemas import DocumentCreate
from .base import DocumentHandler, DocumentContext


class SaveToDBHandler(DocumentHandler):
    """
    Guarda el documento en BD.

    Detecta duplicados por hash SHA-256 del texto extraído, dentro del
    mismo usuario. Si ya existe, lanza HTTPException 409 con el nombre
    del documento existente.
    """

    async def _handle(self, context: DocumentContext):
        try:
            if context.file_type is None:
                raise HTTPException(
                    status_code=400,
                    detail="Tipo de archivo no definido en contexto"
                )

            file_type_value = (
                context.file_type.value
                if hasattr(context.file_type, "value")
                else context.file_type
            )

            if not isinstance(file_type_value, str) or file_type_value not in ("pdf", "docx", "txt"):
                raise HTTPException(
                    status_code=400,
                    detail=f"Tipo de archivo inválido: {file_type_value}"
                )

            if not context.user or not context.db:
                raise HTTPException(
                    status_code=400,
                    detail="Usuario o base de datos no definidos en contexto"
                )

            # Protección: no crear dos veces el mismo documento en la misma request
            if context.document is not None:
                logging.warning(
                    f"[SaveToDBHandler] Documento ya existe con ID "
                    f"{context.document.id}, saltando creación"
                )
                return

            # === DETECCIÓN DE DUPLICADOS POR HASH DEL TEXTO ===
            text_for_hash = (context.text or "").strip()
            content_hash = None
            if text_for_hash:
                content_hash = hashlib.sha256(
                    text_for_hash.encode("utf-8")
                ).hexdigest()

                existing = (
                    context.db.query(Document)
                    .filter(
                        Document.uploaded_by == context.user.id,
                        Document.content_hash == content_hash,
                    )
                    .first()
                )

                if existing:
                    logging.info(
                        f"[SaveToDBHandler] Duplicado detectado para "
                        f"usuario {context.user.id}: coincide con "
                        f"documento {existing.id} ({existing.filename})"
                    )
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"Este documento ya está cargado como "
                            f"'{existing.filename}'."
                        ),
                    )

            encrypted_content = getattr(context, 'encrypted_content', b'')
            if encrypted_content is None:
                encrypted_content = b''
            if not isinstance(encrypted_content, bytes):
                raise HTTPException(
                    status_code=400,
                    detail="El contenido encriptado debe ser bytes"
                )

            if not context.filename or not isinstance(context.filename, str):
                raise HTTPException(
                    status_code=400,
                    detail="Nombre de archivo inválido"
                )

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
                is_public=is_public,
                content_hash=content_hash,
            )

            logging.info(
                f"[SaveToDBHandler] Creando documento con "
                f"file_type: {context.file_type}"
            )

            context.document = crud.create_document(
                db=context.db,
                document=doc_data,
                file_type=context.file_type
            )

            if not context.document:
                raise HTTPException(
                    status_code=500,
                    detail="No se pudo crear el documento en la base de datos"
                )

            try:
                context.db.commit()
                context.db.refresh(context.document)
                logging.info(
                    f"[SaveToDBHandler] Documento creado y confirmado: "
                    f"ID={context.document.id}"
                )
            except Exception as commit_error:
                context.db.rollback()
                logging.exception(
                    f"[SaveToDBHandler] Error en commit: {commit_error}"
                )
                raise HTTPException(
                    status_code=500,
                    detail="Error al confirmar documento en base de datos"
                )

        except HTTPException:
            raise
        except Exception as e:
            logging.exception(f"Error guardando documento en BD: {e}")
            raise HTTPException(
                status_code=500,
                detail="Error al guardar en base de datos"
            )