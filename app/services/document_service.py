import datetime
import json
import logging
import base64
from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from typing import List, Optional, Tuple
from contextlib import contextmanager

from app.db.crud import crud
from app.models import models
from app.models.models import Document, User
from app.enums.enums import FileType, AIChannel, AIInteractionStatus
from app.schemas.dashboard_schemas import ChartDataPoint, DashboardStats
from app.schemas.document_schemas import DocumentWithMetadata
from app.schemas.log_schemas import AIInteractionLogOut
from sqlalchemy.orm import joinedload
from app.db.crud.crud import get_document_by_id
from app.services import storage_service
from cryptography.fernet import InvalidToken


class DocumentServiceError(Exception):
    """Base exception for DocumentService errors"""
    pass

class DocumentNotFoundError(DocumentServiceError):
    """Document not found error"""
    pass

class DocumentAccessDeniedError(DocumentServiceError):
    """Document access denied error"""
    pass


class DocumentService:

    @staticmethod
    @contextmanager
    def db_transaction(db: Session):
        """Context manager for database transactions with rollback on error"""
        try:
            yield db
            db.commit()
        except Exception as e:
            db.rollback()
            logging.error(f"Database transaction failed: {e}")
            raise

    @staticmethod
    def _validate_user_access(doc: Document, user, allow_public: bool = False) -> None:
        """
        Validate if user has access to document.

        allow_public=True (lectura: metadata/descarga): cualquier usuario puede
        acceder a documentos públicos (is_public=1, los que sube un admin).
        Las operaciones de escritura (borrar) siguen limitadas a propietario o admin.
        """
        if not doc:
            raise DocumentNotFoundError("Documento no encontrado")
        if user.is_admin:
            return
        if allow_public and doc.is_public == 1:
            return
        if doc.uploaded_by != user.id:
            raise DocumentAccessDeniedError("No tiene permisos para acceder a este documento")

    # =========================================================
    # NOTA: _safe_activity_log ELIMINADO (ya no existe ActivityLog)
    # =========================================================

    @staticmethod
    def list_documents(
        skip: int,
        limit: int,
        db: Session,
        user,
        file_type: Optional[FileType] = None
    ) -> Tuple[List[models.Document], int]:

        query = db.query(models.Document).filter(
            (models.Document.uploaded_by == user.id) | (models.Document.is_public == 1)
        )

        if file_type:
            query = query.filter(models.Document.file_type == file_type.value)

        total = query.count()
        documents = query.order_by(models.Document.created_at.desc()).offset(skip).limit(limit).all()

        return documents, total

    @staticmethod
    def get_metadata(doc_id: int, db: Session, user) -> Document:
        """
        Get document metadata with access control
        """
        try:
            if doc_id <= 0:
                raise HTTPException(status_code=400, detail="ID de documento inválido")

            doc = get_document_by_id(db, doc_id)
            DocumentService._validate_user_access(doc, user, allow_public=True)

            # Actualizar última vista y contador (SIN activity log)
            try:
                doc.last_accessed = datetime.datetime.now()
                doc.view_count = (doc.view_count or 0) + 1
                db.commit()
                db.refresh(doc)
            except Exception as e:
                logging.warning(f"Failed to update view metadata for doc {doc_id}: {e}")

            return doc

        except DocumentNotFoundError:
            raise HTTPException(status_code=404, detail="Documento no encontrado")
        except DocumentAccessDeniedError:
            raise HTTPException(status_code=403, detail="No autorizado para acceder a este documento")
        except SQLAlchemyError as e:
            logging.error(f"Database error getting metadata for doc {doc_id}: {e}")
            raise HTTPException(status_code=500, detail="Error de base de datos")
        except Exception as e:
            logging.exception(f"Unexpected error getting metadata for doc {doc_id}: {e}")
            raise HTTPException(status_code=500, detail="Error interno del servidor")

    @staticmethod
    def download_document(doc_id: int, request: Request, db: Session, user) -> Tuple[bytes, Document]:
        """
        Download document with comprehensive error handling.
        """
        try:
            if doc_id <= 0:
                raise HTTPException(status_code=400, detail="ID de documento inválido")

            doc = get_document_by_id(db, doc_id)
            DocumentService._validate_user_access(doc, user, allow_public=True)

            if not doc.blob_enc:
                raise HTTPException(status_code=404, detail="Contenido del documento no encontrado")

            try:
                encrypted_data = doc.blob_enc
                if isinstance(encrypted_data, str):
                    try:
                        encrypted_data = base64.b64decode(encrypted_data)
                    except Exception as e:
                        logging.error(f"Base64 decode error for doc {doc_id}: {e}")
                        raise HTTPException(status_code=400, detail="Formato de datos cifrados inválido")

                raw_data = storage_service.decrypt_bytes(encrypted_data)

                if not raw_data:
                    raise HTTPException(status_code=404, detail="No se pudo recuperar el contenido del documento")

            except InvalidToken:
                logging.error(f"Decryption failed for doc {doc_id} - Invalid token")
                raise HTTPException(status_code=400, detail="Error al descifrar el documento")
            except Exception as e:
                logging.error(f"Decryption error for doc {doc_id}: {e}")
                raise HTTPException(status_code=500, detail="Error interno al procesar el documento")

            # Actualizar contadores (SIN activity log)
            try:
                doc.download_count = (doc.download_count or 0) + 1
                doc.last_accessed = datetime.datetime.now()
                db.commit()
            except Exception as e:
                logging.warning(f"Failed to update download metrics for doc {doc_id}: {e}")

            return raw_data, doc

        except DocumentNotFoundError:
            raise HTTPException(status_code=404, detail="Documento no encontrado")
        except DocumentAccessDeniedError:
            raise HTTPException(status_code=403, detail="No autorizado para descargar este documento")
        except HTTPException:
            raise
        except SQLAlchemyError as e:
            logging.error(f"Database error downloading doc {doc_id}: {e}")
            raise HTTPException(status_code=500, detail="Error de base de datos")
        except Exception as e:
            logging.exception(f"Unexpected error downloading doc {doc_id}: {e}")
            raise HTTPException(status_code=500, detail="Error interno del servidor")


    @staticmethod
    def get_dashboard_stats(db: Session, user_id: int = None) -> DashboardStats:
        """
        Get dashboard statistics with TYPE BREAKDOWN
        """
        try:
            base_query = db.query(models.Document)
            if user_id:
                base_query = base_query.filter(models.Document.uploaded_by == user_id)

            total_docs = base_query.count()
            total_size = base_query.with_entities(func.sum(models.Document.size)).scalar() or 0

            today = datetime.date.today()
            start_week = today - datetime.timedelta(days=today.weekday())
            start_month = today.replace(day=1)

            docs_today = base_query.filter(func.date(models.Document.created_at) == today).count()
            docs_week = base_query.filter(models.Document.created_at >= start_week).count()
            docs_month = base_query.filter(models.Document.created_at >= start_month).count()

            first_doc_date = base_query.with_entities(func.min(models.Document.created_at)).scalar()
            avg_per_day = 0
            if first_doc_date:
                days_diff = max((today - first_doc_date.date()).days, 1)
                avg_per_day = total_docs / days_diff

            type_breakdown_query = base_query.with_entities(
                models.Document.file_type,
                func.count(models.Document.id).label('count'),
                func.sum(models.Document.size).label('size')
            ).group_by(models.Document.file_type)

            type_breakdown_results = type_breakdown_query.all()

            type_breakdown = [
                {
                    "file_type": str(item.file_type.value) if item.file_type else "unknown",
                    "count": item.count or 0,
                    "size": item.size or 0
                }
                for item in type_breakdown_results
            ]

            logging.info(f"📊 Type breakdown generado: {type_breakdown}")

            most_active_user = None
            if not user_id:
                try:
                    most_active = (
                        db.query(models.User.name, func.count(models.Document.id).label("uploads"))
                        .join(models.Document, models.User.id == models.Document.uploaded_by)
                        .group_by(models.User.name)
                        .order_by(func.count(models.Document.id).desc())
                        .first()
                    )
                    most_active_user = most_active[0] if most_active else None
                except Exception as e:
                    logging.warning(f"Failed to get most active user: {e}")

            peak_upload_time = None
            try:
                peak_time = (
                    base_query.with_entities(
                        func.date_format(models.Document.created_at, "%Y-%m").label("period"),
                        func.count().label("count")
                    )
                    .group_by(func.date_format(models.Document.created_at, "%Y-%m"))
                    .order_by(func.count(models.Document.id).desc())
                    .first()
                )
                peak_upload_time = f"{peak_time[0]}-01" if peak_time else None
            except Exception as e:
                logging.warning(f"Failed to get peak upload time: {e}")

            return DashboardStats(
                totalDocuments=total_docs,
                totalSize=total_size,
                documentsToday=docs_today,
                documentsThisWeek=docs_week,
                documentsThisMonth=docs_month,
                averagePerDay=round(avg_per_day, 2),
                mostActiveUser=most_active_user,
                peakUploadTime=peak_upload_time,
                typeBreakdown=type_breakdown
            )

        except SQLAlchemyError as e:
            logging.error(f"Database error getting dashboard stats: {e}")
            raise HTTPException(status_code=500, detail="Error al obtener estadísticas del dashboard")
        except Exception as e:
            logging.exception(f"Unexpected error getting dashboard stats: {e}")
            raise HTTPException(status_code=500, detail="Error interno del servidor")

    @staticmethod
    def get_chart_data(period: str, db: Session, user_id: int = None) -> List[ChartDataPoint]:
        """
        Get chart data with improved formatting
        """
        try:
            today = datetime.date.today()
            valid_periods = ["week", "month", "year"]

            if period not in valid_periods:
                raise HTTPException(
                    status_code=400,
                    detail=f"Período inválido. Use: {', '.join(valid_periods)}"
                )

            if period == "week":
                start_date = today - datetime.timedelta(days=6)
                group_format = "%Y-%m-%d"
            elif period == "month":
                start_date = today - datetime.timedelta(days=29)
                group_format = "%Y-%m-%d"
            elif period == "year":
                start_date = today.replace(month=1, day=1)
                group_format = "%Y-%m"

            base_query = db.query(models.Document).filter(
                models.Document.created_at >= start_date
            )

            if user_id:
                base_query = base_query.filter(models.Document.uploaded_by == user_id)

            query = (
                base_query.with_entities(
                    func.date_format(models.Document.created_at, group_format).label("period"),
                    func.count(models.Document.id).label("total"),
                    func.sum(
                        case((models.Document.file_type == FileType.pdf, 1), else_=0)
                    ).label("pdf"),
                    func.sum(
                        case((models.Document.file_type == FileType.docx, 1), else_=0)
                    ).label("docx"),
                    func.sum(
                        case((models.Document.file_type == FileType.txt, 1), else_=0)
                    ).label("txt"),
                )
                .group_by(func.date_format(models.Document.created_at, group_format))
                .order_by("period")
            )

            results = query.all()

            chart_data = []
            for row in results:
                label = row.period
                if period in ("week", "month"):
                    try:
                        date_obj = datetime.datetime.strptime(row.period, "%Y-%m-%d")
                        label = date_obj.strftime("%d %b")
                    except Exception:
                        label = row.period
                elif period == "year":
                    try:
                        date_obj = datetime.datetime.strptime(row.period, "%Y-%m")
                        label = date_obj.strftime("%b %Y")
                    except Exception:
                        label = row.period

                chart_data.append(
                    ChartDataPoint(
                        period=row.period,
                        label=label,
                        value=row.total or 0,
                        pdf=row.pdf or 0,
                        docx=row.docx or 0,
                        txt=row.txt or 0,
                        total=row.total or 0
                    )
                )

            logging.info(f"📊 Chart data generado: {len(chart_data)} puntos para período '{period}'")

            return chart_data

        except HTTPException:
            raise
        except SQLAlchemyError as e:
            logging.error(f"Database error getting chart data for period {period}: {e}")
            raise HTTPException(status_code=500, detail="Error al obtener datos del gráfico")
        except Exception as e:
            logging.exception(f"Unexpected error getting chart data for period {period}: {e}")
            raise HTTPException(status_code=500, detail="Error interno del servidor")

    @staticmethod
    def search_documents(
        db: Session,
        user: Optional[User],
        text: Optional[str],
        file_type: Optional[FileType],
        skip: int,
        limit: int
    ) -> Tuple[List[dict], int]:
        """
        Busca documentos con filtros y paginación.
        """
        try:
            if skip < 0:
                raise HTTPException(status_code=400, detail="Skip no puede ser negativo")
            if limit <= 0 or limit > 100:
                raise HTTPException(status_code=400, detail="Limit debe estar entre 1 y 100")
            if text and len(text.strip()) < 2:
                raise HTTPException(status_code=400, detail="Texto de búsqueda debe tener al menos 2 caracteres")

            query = db.query(Document).options(joinedload(Document.owner))

            if not user or not user.is_admin:
                if not user:
                    raise HTTPException(status_code=401, detail="Usuario no autenticado")
                query = query.filter(
                    (Document.uploaded_by == user.id) | (Document.is_public == 1)
                )

            if text:
                like_pattern = f"%{text}%"
                query = query.filter(
                    (Document.filename.ilike(like_pattern)) |
                    (Document.text.ilike(like_pattern))
                )

            if file_type:
                query = query.filter(Document.file_type == file_type)

            total = query.count()

            documents = (
                query.order_by(Document.created_at.desc())
                .offset(skip)
                .limit(limit)
                .all()
            )

            result = []
            for doc in documents:
                result.append({
                    "id": doc.id,
                    "filename": doc.filename,
                    "size": doc.size,
                    "file_type": doc.file_type.value if hasattr(doc.file_type, 'value') else doc.file_type,
                    "created_at": doc.created_at.isoformat() if doc.created_at else None,
                    "uploaded_by_name": doc.owner.name if doc.owner else None,
                })

            return result, total

        except HTTPException:
            raise
        except SQLAlchemyError as e:
            logging.error(f"Database error searching documents: {e}")
            raise HTTPException(status_code=500, detail="Error en la búsqueda de documentos")
        except Exception as e:
            logging.exception(f"Unexpected error searching documents: {e}")
            raise HTTPException(status_code=500, detail="Error interno del servidor")

    @staticmethod
    def get_recent_ai_interactions(
        limit: int,
        db: Session,
        user_id: int = None,
        channel: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[AIInteractionLogOut]:
        """
        Obtener últimas interacciones del usuario con la IA.
        """
        try:
            if limit <= 0 or limit > 100:
                raise HTTPException(status_code=400, detail="Limit debe estar entre 1 y 100")

            query = db.query(models.AIInteractionLog).options(
                joinedload(models.AIInteractionLog.user)
            )

            if user_id:
                query = query.filter(models.AIInteractionLog.user_id == user_id)

            if channel:
                try:
                    channel_enum = AIChannel(channel)
                    query = query.filter(models.AIInteractionLog.channel == channel_enum)
                except ValueError:
                    raise HTTPException(status_code=400, detail=f"Canal inválido: {channel}")

            if status:
                try:
                    status_enum = AIInteractionStatus(status)
                    query = query.filter(models.AIInteractionLog.status == status_enum)
                except ValueError:
                    raise HTTPException(status_code=400, detail=f"Estado inválido: {status}")

            rows = (
                query.order_by(models.AIInteractionLog.timestamp.desc())
                .limit(limit)
                .all()
            )

            result: List[AIInteractionLogOut] = []
            for r in rows:
                if not r.timestamp:
                    logging.warning(f"AIInteractionLog ID {r.id} sin timestamp. Omitida.")
                    continue

                user_name = (
                    r.user.name if r.user and r.user.name else "Usuario eliminado"
                )

                sources_parsed = None
                if r.sources:
                    try:
                        sources_parsed = json.loads(r.sources)
                    except Exception:
                        sources_parsed = None

                sources_info_parsed = None
                if r.sources_info:
                    try:
                        sources_info_parsed = json.loads(r.sources_info)
                    except Exception:
                        sources_info_parsed = None

                result.append(AIInteractionLogOut(
                    id=r.id,
                    user_id=r.user_id,
                    user_name=user_name,
                    question=r.question,
                    answer=r.answer,
                    channel=r.channel,
                    confidence=r.confidence,
                    status=r.status,
                    error_message=r.error_message,
                    sources=sources_parsed,
                    sources_info=sources_info_parsed,
                    processing_time_ms=r.processing_time_ms,
                    from_cache=r.from_cache,
                    conversation_id=r.conversation_id,
                    timestamp=r.timestamp,
                ))

            return result

        except HTTPException:
            raise
        except SQLAlchemyError as e:
            logging.error(f"Database error getting recent AI interactions: {e}")
            raise HTTPException(status_code=500, detail="Error al obtener interacciones recientes")
        except Exception as e:
            logging.exception(f"Unexpected error getting recent AI interactions: {e}")
            raise HTTPException(status_code=500, detail="Error interno del servidor")

    @staticmethod
    def delete_document(doc_id: int, user, db: Session, ip: str = None) -> dict:
        """
        Elimina documento con manejo integral de errores y limpieza
        """
        try:
            if doc_id <= 0:
                raise HTTPException(status_code=400, detail="ID de documento inválido")

            doc = crud.get_document_by_id(db, doc_id)
            if not doc:
                raise HTTPException(status_code=404, detail="Documento no encontrado")

            DocumentService._validate_user_access(doc, user)

            filename = doc.filename
            doc_size = doc.size

            try:
                # SIN activity log: solo eliminar
                db.delete(doc)
                db.commit()

                # Quitar sus fragmentos del índice RAG y vaciar cachés de
                # respuestas: si no, el asistente seguiría usando el contenido
                # borrado. Si falla, el documento ya está borrado y la búsqueda
                # filtra por documentos existentes; solo se registra.
                try:
                    from app.services.Curim.Curim_service import get_curim_service
                    get_curim_service().on_document_deleted(doc_id)
                except Exception as e:
                    logging.warning(f"No se pudo limpiar el índice del documento {doc_id}: {e}")

            except IntegrityError:
                db.rollback()
                raise HTTPException(
                    status_code=409,
                    detail="No se puede eliminar el documento debido a restricciones de integridad"
                )
            except SQLAlchemyError:
                db.rollback()
                raise HTTPException(
                    status_code=500,
                    detail="Error de base de datos al eliminar documento"
                )

            return {
                "message": "Documento eliminado correctamente",
                "document_id": doc_id,
                "filename": filename,
                "size": doc_size
            }

        except DocumentNotFoundError:
            raise HTTPException(status_code=404, detail="Documento no encontrado")
        except DocumentAccessDeniedError:
            raise HTTPException(status_code=403, detail="No autorizado para eliminar este documento")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=500, detail="Error interno del servidor")

    @staticmethod
    def get_documents_with_metadata(db: Session, user_id: int = None) -> List[DocumentWithMetadata]:
        """
        Get documents with complete metadata, optionally filtered by user
        """
        try:
            query = db.query(models.Document).options(joinedload(models.Document.owner))
            if user_id:
                query = query.filter(
                    (models.Document.uploaded_by == user_id) | (models.Document.is_public == 1)
                )

            documents = query.all()

            return [
                DocumentWithMetadata(
                    id=doc.id,
                    name=doc.filename,
                    file_type=doc.file_type,
                    size=doc.size,
                    upload_date=doc.created_at,
                    last_accessed=doc.last_accessed,
                    user_id=doc.uploaded_by,
                    user_name=doc.owner.name if doc.owner else "Usuario eliminado",
                    download_count=doc.download_count or 0,
                    view_count=doc.view_count or 0,
                )
                for doc in documents
            ]

        except SQLAlchemyError as e:
            logging.error(f"Database error getting documents with metadata: {e}")
            raise HTTPException(status_code=500, detail="Error al obtener metadatos de documentos")
        except Exception as e:
            logging.exception(f"Unexpected error getting documents with metadata: {e}")
            raise HTTPException(status_code=500, detail="Error interno del servidor")

    @staticmethod
    def get_user_storage_stats(db: Session, user_id: int) -> dict:
        """
        Get storage statistics for a specific user
        """
        try:
            user_docs = db.query(models.Document).filter(models.Document.uploaded_by == user_id)

            total_documents = user_docs.count()
            total_size = user_docs.with_entities(func.sum(models.Document.size)).scalar() or 0

            type_stats = (
                user_docs.with_entities(
                    models.Document.file_type,
                    func.count().label('count'),
                    func.sum(models.Document.size).label('size')
                )
                .group_by(models.Document.file_type)
                .all()
            )

            return {
                "user_id": user_id,
                "total_documents": total_documents,
                "total_size": total_size,
                "type_breakdown": [
                    {
                        "file_type": stat.file_type.value if stat.file_type else "unknown",
                        "count": stat.count,
                        "size": stat.size or 0
                    }
                    for stat in type_stats
                ]
            }

        except SQLAlchemyError as e:
            logging.error(f"Database error getting user storage stats for user {user_id}: {e}")
            raise HTTPException(status_code=500, detail="Error al obtener estadísticas de almacenamiento")
        except Exception as e:
            logging.exception(f"Unexpected error getting user storage stats for user {user_id}: {e}")
            raise HTTPException(status_code=500, detail="Error interno del servidor")