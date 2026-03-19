import datetime
import logging
import io
import base64
from datetime import date, timedelta
from fastapi import UploadFile, HTTPException, Request, status
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from sqlalchemy.exc import SQLAlchemyError, IntegrityError, DataError
from typing import List, Optional, Tuple
import traceback
from contextlib import contextmanager

from app.db.crud import crud
from app.models import models
from app.models.models import Document, ActivityLog, User
from app.enums.enums import FileType
from app.schemas.dashboard_schemas import ChartDataPoint, DashboardStats
from app.schemas.document_schemas import DocumentWithMetadata
from app.schemas.log_schemas import ActivityLogOut
from app.services.handlers.base import DocumentContext
from app.services.handlers.validate_file import ValidateFileHandler
from app.services.handlers.extract_text import ExtractTextHandler  
from app.services.handlers.encrypt_file import EncryptFileHandler
from app.services.handlers.save_to_db import SaveToDBHandler
from app.services.handlers.log_activity import LogActivityHandler
from sqlalchemy.orm import joinedload
from app.db.crud.crud import (
    get_document_by_id,
    get_documents_list,
    create_activity_log,
    search_documents,
)
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

class DocumentProcessingError(DocumentServiceError):
    """Document processing error"""
    pass

class DocumentEncryptionError(DocumentServiceError):
    """Document encryption/decryption error"""
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
    def _validate_user_access(doc: Document, user) -> None:
        """Validate if user has access to document"""
        if not doc:
            raise DocumentNotFoundError("Documento no encontrado")
        if user.is_admin:
            return
        if doc.uploaded_by != user.id:
            raise DocumentAccessDeniedError("No tiene permisos para acceder a este documento")

    @staticmethod
    def _safe_activity_log(db: Session, user_id: int, document_id: int, action: str, ip_address: str = None):
        """Safely create activity log without affecting main operation"""
        try:
            create_activity_log(db, user_id=user_id, document_id=document_id, action=action, ip_address=ip_address)
        except Exception as e:
            logging.warning(f"Failed to create activity log: {e}")

    @staticmethod
    async def upload_documents(files: List[UploadFile], db: Session, user) -> List[Document]:
        """
        Upload multiple documents with comprehensive error handling
        """
        if not files:
            raise HTTPException(status_code=400, detail="No se proporcionaron archivos")
        
        if len(files) > 10:  # Limitar cantidad de archivos
            raise HTTPException(status_code=400, detail="Máximo 10 archivos por operación")
        
        created_documents = []
        failed_files = []

        for f in files:
            try:
                # Validaciones básicas
                if not f.filename:
                    failed_files.append({"filename": "sin_nombre", "error": "Nombre de archivo vacío"})
                    continue
                
                if f.size and f.size > 50 * 1024 * 1024:  # 50MB limit
                    failed_files.append({"filename": f.filename, "error": "Archivo demasiado grande (máximo 50MB)"})
                    continue

                content = await f.read()
                if not content:
                    failed_files.append({"filename": f.filename, "error": "Archivo vacío"})
                    continue

                # Reset file position
                await f.seek(0)
                
                context = DocumentContext(filename=f.filename, content=content, user=user, db=db)

                handler_chain = (
                    ValidateFileHandler()
                    .set_next(ExtractTextHandler())
                    .set_next(EncryptFileHandler())
                    .set_next(SaveToDBHandler())
                    .set_next(LogActivityHandler())
                )

                with DocumentService.db_transaction(db):
                    handler_chain.handle(context)
                    
                    if context.document:
                        db.refresh(context.document)
                        created_documents.append(context.document)
                        logging.info(f"Documento subido exitosamente: {f.filename} (ID: {context.document.id})")
                    else:
                        failed_files.append({"filename": f.filename, "error": "No se pudo guardar el documento"})

            except HTTPException as e:
                failed_files.append({"filename": f.filename, "error": e.detail})
                logging.error(f"HTTPException procesando {f.filename}: {e.detail}")
            except SQLAlchemyError as e:
                failed_files.append({"filename": f.filename, "error": "Error de base de datos"})
                logging.error(f"Database error procesando {f.filename}: {e}")
            except Exception as e:
                failed_files.append({"filename": f.filename, "error": "Error interno del servidor"})
                logging.exception(f"Error inesperado procesando {f.filename}: {e}")

        # Si todos los archivos fallaron
        if not created_documents and failed_files:
            error_details = "; ".join([f"{item['filename']}: {item['error']}" for item in failed_files])
            raise HTTPException(
                status_code=400, 
                detail=f"No se pudo procesar ningún archivo. Errores: {error_details}"
            )
        
        # Si algunos fallaron, log warnings
        if failed_files:
            error_summary = f"Archivos fallidos: {len(failed_files)}/{len(files)}"
            logging.warning(f"Upload parcialmente exitoso - {error_summary}")

        return created_documents

    @staticmethod
    def list_documents(
        skip: int,
        limit: int,
        db: Session,
        user,
        file_type: Optional[FileType] = None
    ) -> Tuple[List[models.Document], int]:

        # Obtener documentos filtrados por usuario O públicos, y opcionalmente por tipo
        # Un usuario ve sus propios documentos Y los documentos públicos (subidos por admin)
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
            DocumentService._validate_user_access(doc, user)
            
            # Actualizar última vista y contador
            try:
                doc.last_accessed = datetime.datetime.now()
                doc.view_count = (doc.view_count or 0) + 1
                
                DocumentService._safe_activity_log(db, user_id=user.id, document_id=doc.id, action="view")
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
        Admins can download any document, while regular users can only download their own.
        """
        try:
            if doc_id <= 0:
                raise HTTPException(status_code=400, detail="ID de documento inválido")

            doc = get_document_by_id(db, doc_id)
            
            # Validar el acceso del usuario
            DocumentService._validate_user_access(doc, user)

            # Verificar si el documento tiene contenido
            if not doc.blob_enc:
                raise HTTPException(status_code=404, detail="Contenido del documento no encontrado")

            # Desencriptar contenido
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

            # Registrar la descarga y actualizar contadores
            try:
                ip = getattr(request.client, 'host', 'unknown') if request.client else 'unknown'
                doc.download_count = (doc.download_count or 0) + 1
                doc.last_accessed = datetime.datetime.now()
                
                DocumentService._safe_activity_log(
                    db, user_id=user.id, document_id=doc.id, action="download", ip_address=ip
                )
                db.commit()

            except Exception as e:
                logging.warning(f"Failed to log download activity for doc {doc_id}: {e}")

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
            # Base query - filtrar por usuario si se especifica
            base_query = db.query(models.Document)
            if user_id:
                base_query = base_query.filter(models.Document.uploaded_by == user_id)

            total_docs = base_query.count()
            total_size = base_query.with_entities(func.sum(models.Document.size)).scalar() or 0

            today = datetime.date.today()
            start_week = today - datetime.timedelta(days=today.weekday())
            start_month = today.replace(day=1)

            # Stats por período
            docs_today = base_query.filter(func.date(models.Document.created_at) == today).count()
            docs_week = base_query.filter(models.Document.created_at >= start_week).count()
            docs_month = base_query.filter(models.Document.created_at >= start_month).count()

            # Promedio por día
            first_doc_date = base_query.with_entities(func.min(models.Document.created_at)).scalar()
            avg_per_day = 0
            if first_doc_date:
                days_diff = max((today - first_doc_date.date()).days, 1)
                avg_per_day = total_docs / days_diff

            # 🔥 AGREGAR TYPE BREAKDOWN - ESTO ES CRÍTICO
            type_breakdown_query = base_query.with_entities(
                models.Document.file_type,
                func.count(models.Document.id).label('count'),
                func.sum(models.Document.size).label('size')
            ).group_by(models.Document.file_type)
            
            type_breakdown_results = type_breakdown_query.all()
            
            # Convertir a formato del schema
            type_breakdown = [
                {
                    "file_type": str(item.file_type.value) if item.file_type else "unknown",
                    "count": item.count or 0,
                    "size": item.size or 0
                }
                for item in type_breakdown_results
            ]
            
            logging.info(f"📊 Type breakdown generado: {type_breakdown}")

            # Usuario más activo (solo si no hay filtro de usuario)
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

            # Período pico de subidas
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

            # Configurar fechas según período
            if period == "week":
                start_date = today - datetime.timedelta(days=6)
                group_format = "%Y-%m-%d"
            elif period == "month":
                start_date = today - datetime.timedelta(days=29)
                group_format = "%Y-%m-%d"
            elif period == "year":
                start_date = today.replace(month=1, day=1)
                group_format = "%Y-%m"

            # Base query
            base_query = db.query(models.Document).filter(
                models.Document.created_at >= start_date
            )
            
            if user_id:
                base_query = base_query.filter(models.Document.uploaded_by == user_id)

            # Query para datos del gráfico
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
            
            # Formatear resultados
            chart_data = []
            for row in results:
                # Convertir período a formato legible
                label = row.period
                if period == "week" or period == "month":
                    # Convertir "2025-10-10" a "10 Oct"
                    try:
                        date_obj = datetime.datetime.strptime(row.period, "%Y-%m-%d")
                        label = date_obj.strftime("%d %b")
                    except:
                        label = row.period
                elif period == "year":
                    # Convertir "2025-10" a "Oct 2025"
                    try:
                        date_obj = datetime.datetime.strptime(row.period, "%Y-%m")
                        label = date_obj.strftime("%b %Y")
                    except:
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
        Si el usuario es admin, puede ver todos los documentos.
        Si es usuario normal, solo los suyos.
        Retorna lista de documentos como dicts incluyendo uploaded_by_name.
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
                # Usuarios normales ven sus docs O docs públicos
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
                    # Agrega más campos si los necesitas
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
    def get_recent_activities(limit: int, db: Session, user_id: int = None) -> List[ActivityLogOut]:
        try:
            if limit <= 0 or limit > 100:
                raise HTTPException(status_code=400, detail="Limit debe estar entre 1 y 100")

            query = db.query(models.ActivityLog).options(
                joinedload(models.ActivityLog.document),
                joinedload(models.ActivityLog.user)
            )

            if user_id:
                query = query.filter(models.ActivityLog.user_id == user_id)

            activities = (
                query.order_by(models.ActivityLog.timestamp.desc())
                .limit(limit)
                .all()
            )

            result = []

            for act in activities:
                if not act.timestamp:
                    logging.warning(f"Actividad ID {act.id} sin timestamp. Omitida.")
                    continue

                document_name = (
                    act.document_name
                    or (act.document.filename if act.document else None)
                    or "Archivo eliminado"
                )

            
                document_type = (
                    act.document_type
                    or (act.document.file_type if act.document else None)
                    or FileType.txt  # fallback seguro
                )

                user_name = (
                    act.user.name
                    if act.user and act.user.name
                    else "Usuario eliminado"
                )

            
                user_email = (
                    act.user.email
                    if act.user and act.user.email
                    else None
                )

                result.append(ActivityLogOut(
                    id=act.id,
                    action=act.action,
                    document_id=act.document_id,
                    document_name=document_name,
                    document_type=document_type,
                    user_id=act.user_id,
                    user_name=user_name,
                    timestamp=act.timestamp,
                    ip_address=act.ip_address,
                ))

            return result

        except HTTPException:
            raise
        except SQLAlchemyError as e:
            logging.error(f"Database error getting recent activities: {e}")
            raise HTTPException(status_code=500, detail="Error al obtener actividades recientes")
        except Exception as e:
            logging.exception(f"Unexpected error getting recent activities: {e}")
            raise HTTPException(status_code=500, detail="Error interno del servidor")

    @staticmethod
    def delete_document(doc_id: int, user, db: Session, ip: str = None) -> dict:
        """
        Elimina documento con manejo integral de errores y limpieza
        
        Args:
            doc_id: ID del documento a eliminar
            user: Usuario que solicita la eliminación
            db: Sesión de base de datos
            ip: Dirección IP del cliente (opcional)
            
        Returns:
            dict con mensaje de confirmación y detalles del documento eliminado
            
        Raises:
            HTTPException: Si hay errores de validación, permisos o base de datos
        """
        try:
            # Validar ID
            if doc_id <= 0:
                raise HTTPException(status_code=400, detail="ID de documento inválido")

            # Obtener documento
            doc = crud.get_document_by_id(db, doc_id)
            if not doc:
                raise HTTPException(status_code=404, detail="Documento no encontrado")
            
            # Validar permisos
            DocumentService._validate_user_access(doc, user)

            # Guardar información antes de eliminar (para logging y respuesta)
            filename = doc.filename
            doc_size = doc.size
            file_path = getattr(doc, 'file_path', None)  # Si guardas ruta del archivo

            try:
                # 1. Registrar actividad ANTES de eliminar (mientras doc.id aún existe)
                DocumentService._safe_activity_log(
                    db, 
                    user_id=user.id, 
                    document_id=doc.id, 
                    action="delete", 
                    ip_address=ip
                )
                
                # 2. Eliminar de la base de datos
                # Esto automáticamente eliminará registros en Curim_document_index por CASCADE
                db.delete(doc)
                db.commit()
                
            except IntegrityError as e:
                db.rollback()
                raise HTTPException(
                    status_code=409, 
                    detail="No se puede eliminar el documento debido a restricciones de integridad"
                )
            except SQLAlchemyError as e:
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
            # Re-lanzar excepciones HTTP ya manejadas
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail="Error interno del servidor")

    @staticmethod
    def get_documents_with_metadata(db: Session, user_id: int = None) -> List[DocumentWithMetadata]:
        """
        Get documents with complete metadata, optionally filtered by user
        """
        try:
            query = db.query(models.Document).options(joinedload(models.Document.owner))
            if user_id:
                # Si se solicita para un usuario específico, incluir sus docs O los públicos
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
            
            # Estadísticas por tipo de archivo
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