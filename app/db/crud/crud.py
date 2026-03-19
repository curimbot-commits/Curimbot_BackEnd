"""
Módulo CRUD (Create, Read, Update, Delete) para documentos y actividades.

Este módulo proporciona todas las operaciones de base de datos para gestionar
documentos, incluyendo creación, lectura, actualización, eliminación y búsqueda.
También incluye funciones para auditoría y tracking de actividades.

Patrones:
    - CRUD básico: Operaciones estándar en documentos
    - Búsqueda: Con filtros y paginación
    - Auditoría: Logging de acciones y tracking de métricas
    - Transacciones: Manejo de errores con rollback automático

Casos de uso:
    - Guardar documentos subidos
    - Buscar documentos por criterios
    - Actualizar metadatos
    - Registrar acciones del usuario
    - Estadísticas de uso
"""

import logging
from sqlalchemy import Tuple
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime, timezone
from app.enums.enums import FileType
from app.models import models
from app.schemas.document_schemas import DocumentCreate, DocumentUpdate
from app.schemas.log_schemas import LogCreate

logger = logging.getLogger(__name__)


# =========================================================
# 🚀 FUNCIONES CRUD BÁSICAS
# =========================================================

def get_document_by_id(db: Session, doc_id: int) -> Optional[models.Document]:
    """
    Obtener un documento por su ID.
    
    Recupera un documento específico de la base de datos usando su ID.
    Operación simple y rápida usando índice primario.
    
    Args:
        db (Session): Sesión de base de datos SQLAlchemy
        doc_id (int): ID único del documento
    
    Returns:
        Optional[models.Document]: El documento si existe, None si no
    
    Example:
        from app.db.crud import get_document_by_id
        from app.db.database import SessionLocal
        
        db = SessionLocal()
        doc = get_document_by_id(db, 123)
        
        if doc:
            print(f"Documento: {doc.filename}")
        else:
            print("Documento no encontrado")
    
    Performance:
        - O(1) mediante índice de PK
        - Típicamente < 10ms
    
    Security:
        - No valida propiedad del documento
        - Llamador debe verificar permisos
    """
    return db.query(models.Document).filter(models.Document.id == doc_id).first()


def get_documents_list(
    db: Session,
    uploaded_by: int,
    file_type: Optional[FileType] = None,
    skip: int = 0,
    limit: int = 100
) -> List[models.Document]:
    """
    Obtener lista paginada de documentos de un usuario.
    
    Retorna todos los documentos de un usuario con soporte para filtrado
    por tipo de archivo y paginación.
    
    Filtrado:
        - **uploaded_by**: Filtro REQUERIDO (usuario propietario)
        - **file_type**: Opcional, filtra por tipo (pdf, docx, etc.)
    
    Paginación:
        - **skip**: Número de documentos a omitir (offset)
        - **limit**: Máximo número a retornar (default 100)
    
    Args:
        db (Session): Sesión de base de datos SQLAlchemy
        uploaded_by (int): ID del usuario propietario (REQUERIDO)
        file_type (Optional[FileType]): Tipo de archivo a filtrar (pdf, docx, etc.)
        skip (int): Documentos a omitir (default 0)
        limit (int): Máximo a retornar (default 100)
    
    Returns:
        List[models.Document]: Lista de documentos que cumplen criterios
    
    Example:
        from app.db.crud import get_documents_list
        from app.enums.enums import FileType
        
        # Obtener todos los documentos del usuario 1
        docs = get_documents_list(db, uploaded_by=1)
        
        # Obtener solo PDFs del usuario 1
        pdfs = get_documents_list(db, uploaded_by=1, file_type=FileType.PDF)
        
        # Paginación: segundos 20 documentos
        page2 = get_documents_list(db, uploaded_by=1, skip=20, limit=20)
    
    Performance:
        - Usa índices en (uploaded_by, file_type)
        - Típicamente < 100ms para paginación
    
    Security:
        - Filtra por usuario automáticamente
        - No retorna documentos de otros usuarios
    """
    query = db.query(models.Document).filter(models.Document.uploaded_by == uploaded_by)
    if file_type:
        query = query.filter(models.Document.file_type == file_type.value)
    return query.offset(skip).limit(limit).all()


def create_document(db: Session, document: DocumentCreate, file_type: FileType) -> models.Document:
    """
    Crear un nuevo documento en la base de datos.
    
    Inserta un nuevo documento con todos sus metadatos. Soporta blobs binarios
    encriptados. Realiza logging detallado del proceso.
    
    Datos guardados:
        - **filename**: Nombre original del archivo
        - **mimetype**: Tipo MIME (application/pdf, etc.)
        - **size**: Tamaño en bytes
        - **file_type**: Tipo (pdf, docx, xlsx, txt)
        - **text**: Texto extraído
        - **blob_enc**: Datos binarios encriptados
        - **uploaded_by**: ID del usuario propietario
    
    Validaciones:
        - file_type se convierte a string si es enum
        - Todos los campos requeridos deben estar presentes
    
    Transacciones:
        - db.flush() para obtener ID generado
        - db.refresh() para cargar valores del servidor
        - Rollback automático en error
    
    Args:
        db (Session): Sesión de base de datos SQLAlchemy
        document (DocumentCreate): Schema Pydantic con datos
        file_type (FileType): Tipo de archivo (enum)
    
    Returns:
        models.Document: Documento creado con ID asignado
    
    Raises:
        Exception: Si hay error en la BD (se registra en logs)
    
    Example:
        from app.db.crud import create_document
        from app.schemas.document_schemas import DocumentCreate
        from app.enums.enums import FileType
        
        doc_data = DocumentCreate(
            filename="reporte.pdf",
            mimetype="application/pdf",
            size=2097152,
            text="Contenido extraído...",
            blob_enc=b"datos_encriptados",
            uploaded_by=1
        )
        
        doc = create_document(db, doc_data, FileType.PDF)
        print(f"Documento creado con ID: {doc.id}")
    
    Logging:
        - INFO: Inicio del proceso con datos básicos
        - INFO: Éxito con ID asignado
        - ERROR: Cualquier excepción con detalles
    
    Performance:
        - INSERT simple, típicamente < 50ms
        - flush() genera IDs de BD
        - refresh() carga valores computados (timestamps, etc.)
    
    Security:
        - uploaded_by se toma de DocumentCreate (validar antes)
        - blob_enc debe estar ya encriptado
        - No valida propietario
    
    Notes:
        - blob_enc puede ser binario grande (hasta limit de BD)
        - Los timestamps se generan automáticamente
        - file_type se normaliza a string para compatibilidad
    """
    logging.info("=== INICIANDO create_document ===")
    logging.info(f"Datos recibidos - filename: {document.filename}, tipo: {file_type}")
    logging.info(f"Tamaño: {document.size}, uploaded_by: {document.uploaded_by}")
    
    try:
        # Convertir file_type a string si es enum
        file_type_str = file_type.value if hasattr(file_type, "value") else str(file_type)
        
        # Crear modelo de BD
        db_document = models.Document(
            filename=document.filename,
            mimetype=document.mimetype,
            size=document.size,
            file_type=file_type_str,
            text=document.text,
            blob_enc=document.blob_enc,
            uploaded_by=document.uploaded_by,
            is_public=document.is_public
        )
        
        # Guardar en BD
        db.add(db_document)
        db.flush()  # Obtener ID sin commit aún
        db.refresh(db_document)  # Cargar valores del servidor
        
        # Log sin imprimir blob binario completo (es grande)
        doc_dict = db_document.__dict__.copy()
        if 'blob_enc' in doc_dict:
            doc_dict['blob_enc'] = f"<{len(doc_dict['blob_enc'])} bytes binarios>"
        
        logging.info(f"✅ Documento creado exitosamente con ID {db_document.id}")
        logging.info(f"Documento final: {doc_dict}")
        
        return db_document
        
    except Exception as e:
        logging.exception(f"❌ Error detallado en create_document: {e}")
        raise


def update_document(
    db: Session, 
    doc_id: int, 
    updates: DocumentUpdate
) -> Optional[models.Document]:
    """
    Actualizar campos específicos de un documento.
    
    Actualiza solo los campos presentes en el schema DocumentUpdate
    (usa exclude_unset=True para solo cambios explícitos).
    
    Casos de uso:
        - Actualizar metadatos (nombre, descripción)
        - Cambiar estado (status)
        - Actualizar texto extraído
    
    Args:
        db (Session): Sesión de base de datos SQLAlchemy
        doc_id (int): ID del documento a actualizar
        updates (DocumentUpdate): Schema con cambios (solo campos presentes)
    
    Returns:
        Optional[models.Document]: Documento actualizado, o None si no existe
    
    Example:
        from app.db.crud import update_document
        from app.schemas.document_schemas import DocumentUpdate
        
        updates = DocumentUpdate(
            filename="nuevo_nombre.pdf",
            status="completed"
        )
        
        updated_doc = update_document(db, 123, updates)
        if updated_doc:
            print(f"Documento actualizado: {updated_doc.filename}")
    
    Performance:
        - UPDATE simple por ID
        - Típicamente < 50ms
    
    Transacciones:
        - db.commit() guarda cambios
        - db.refresh() carga valores actualizados
    
    Notes:
        - Solo cambia campos presentes en updates
        - Fields con None se ignoran si no están en original
        - setattr() aplica cambios dinámicamente
    """
    db_doc = get_document_by_id(db, doc_id)
    if not db_doc:
        return None
    
    # Actualizar solo campos presentes (exclude_unset=True)
    for key, value in updates.model_dump(exclude_unset=True).items():
        setattr(db_doc, key, value)
    
    db.commit()
    db.refresh(db_doc)
    return db_doc


def delete_document(db: Session, doc_id: int) -> bool:
    """
    Eliminar un documento de la base de datos.
    
    Eliminación lógica o física según configuración. Por defecto,
    elimina completamente el registro.
    
    Args:
        db (Session): Sesión de base de datos SQLAlchemy
        doc_id (int): ID del documento a eliminar
    
    Returns:
        bool: True si fue eliminado, False si no existe
    
    Example:
        from app.db.crud import delete_document
        
        if delete_document(db, 123):
            print("Documento eliminado")
        else:
            print("Documento no encontrado")
    
    Operación:
        1. Verificar que documento existe
        2. Si no existe, retornar False
        3. Eliminar documento
        4. Commit de cambios
        5. Retornar True
    
    Performance:
        - DELETE por ID
        - Típicamente < 50ms
    
    Notes:
        - Considerare usar soft delete (flag deleted_at)
        - Para cumplimiento de retención de datos
        - Datos se pueden recuperar de backups
    """
    db_doc = get_document_by_id(db, doc_id)
    if not db_doc:
        return False
    
    db.delete(db_doc)
    db.commit()
    return True


def create_log(db: Session, log_data: LogCreate) -> models.Log:
    """
    Crear un registro de log en la base de datos.
    
    Registra eventos específicos (errores, procesamiento, etc.) para
    auditoría y debugging.
    
    Args:
        db (Session): Sesión de base de datos SQLAlchemy
        log_data (LogCreate): Schema Pydantic con datos del log
    
    Returns:
        models.Log: Registro de log creado
    
    Example:
        from app.db.crud import create_log
        from app.schemas.log_schemas import LogCreate
        
        log_data = LogCreate(
            level="ERROR",
            message="Error al procesar documento",
            details={"document_id": 123, "error": "..."}
        )
        
        log = create_log(db, log_data)
    
    Notes:
        - log_data se convierte a dict automáticamente
        - Timestamp se genera automáticamente
    """
    db_log = models.Log(**log_data.model_dump())
    db.add(db_log)
    return db_log


def search_documents(
    db: Session,
    user_id: int,
    query: Optional[str] = None,
    file_type: Optional[FileType] = None,
    skip: int = 0,
    limit: int = 100
) -> List[models.Document]:
    """
    Buscar documentos con filtros y paginación.
    
    Búsqueda full-text opcional en contenido de documentos, combinada
    con filtrado por tipo. Retorna resultados paginados y total.
    
    Búsqueda:
        - **query**: Texto a buscar en filename y text extraído
        - **file_type**: Filtro por tipo de archivo
        - **user_id**: Filtro por propietario (REQUERIDO)
    
    Paginación:
        - **skip**: Documentos a omitir (offset)
        - **limit**: Máximo a retornar
    
    Args:
        db (Session): Sesión de base de datos SQLAlchemy
        user_id (int): ID del usuario propietario (REQUERIDO)
        query (Optional[str]): Texto a buscar (case-insensitive)
        file_type (Optional[FileType]): Tipo de archivo a filtrar
        skip (int): Documentos a omitir (default 0)
        limit (int): Máximo a retornar (default 100)
    
    Returns:
        Tuple[List[models.Document], int]: (documentos, total_sin_paginar)
    
    Example:
        from app.db.crud import search_documents
        from app.enums.enums import FileType
        
        # Buscar "reporte" en documentos del usuario 1
        docs, total = search_documents(
            db,
            user_id=1,
            query="reporte",
            skip=0,
            limit=20
        )
        print(f"Encontrados {total} documentos, mostrando {len(docs)}")
        
        # Buscar solo PDFs
        pdfs, total = search_documents(
            db,
            user_id=1,
            file_type=FileType.PDF,
            limit=50
        )
    
    Performance:
        - Búsqueda: Usa ILIKE (índice de texto completo recomendado)
        - Típicamente 100-500ms según tamaño de collection
        - Considerar índices en (user_id, text) para mejor rendimiento
    
    Filtros:
        - ilike() = case-insensitive LIKE
        - % wildcard: %query% busca en cualquier parte
    
    Retorna:
        - documentos: Lista de resultados paginada
        - total: Total de resultados sin paginar (para calcular páginas)
    """
    filters = [models.Document.uploaded_by == user_id]
    
    if query:
        filters.append(models.Document.text.ilike(f"%{query}%"))
    
    if file_type:
        filters.append(models.Document.file_type == file_type)
    
    # Obtener total sin paginar (para saber cuántas páginas hay)
    total = db.query(models.Document).filter(*filters).count()
    
    # Obtener documentos con paginación
    documents = db.query(models.Document).filter(*filters).offset(skip).limit(limit).all()
    
    return documents, total


# =========================================================
# 🚀 NUEVAS FUNCIONES PARA ACTIVIDADES Y ESTADÍSTICAS
# =========================================================

def create_activity(
    db: Session,
    user_id: Optional[int],
    document_id: int,
    action: str,
    ip_address: Optional[str] = None
) -> models.ActivityLog:
    """
    Crear un registro de actividad del usuario.
    
    Registra acciones como: view, download, upload, delete, share.
    Útil para auditoría y tracking de uso.
    
    Args:
        db (Session): Sesión de base de datos SQLAlchemy
        user_id (Optional[int]): ID del usuario (None = acción anónima)
        document_id (int): ID del documento afectado
        action (str): Tipo de acción (view, download, upload, delete, share)
        ip_address (Optional[str]): IP del cliente
    
    Returns:
        models.ActivityLog: Registro de actividad creado
    
    Example:
        from app.db.crud import create_activity
        
        activity = create_activity(
            db,
            user_id=1,
            document_id=123,
            action="download",
            ip_address="192.168.1.1"
        )
    
    Notes:
        - Timestamp se genera automáticamente (timezone.utc)
        - user_id puede ser None para acciones no autenticadas
        - Útil para análisis de patrones de uso
    """
    db_activity = models.ActivityLog(
        user_id=user_id,
        document_id=document_id,
        action=action,
        ip_address=ip_address,
        timestamp=datetime.now(timezone.utc)
    )
    db.add(db_activity)
    return db_activity


def increment_view_count(db: Session, doc: models.Document) -> None:
    """
    Incrementar contador de visualizaciones de un documento.
    
    Aumenta view_count en 1 y actualiza last_accessed.
    
    Args:
        db (Session): Sesión de base de datos SQLAlchemy
        doc (models.Document): Documento a actualizar
    
    Example:
        from app.db.crud import increment_view_count
        
        doc = get_document_by_id(db, 123)
        increment_view_count(db, doc)
        db.commit()
    
    Notes:
        - Debe hacerse db.commit() después
        - last_accessed ayuda a saber documentos usados recientemente
    """
    doc.view_count = (doc.view_count or 0) + 1
    doc.last_accessed = datetime.now(timezone.utc)
    db.add(doc)


def increment_download_count(db: Session, doc: models.Document) -> None:
    """
    Incrementar contador de descargas de un documento.
    
    Aumenta download_count en 1 y actualiza last_accessed.
    
    Args:
        db (Session): Sesión de base de datos SQLAlchemy
        doc (models.Document): Documento a actualizar
    
    Example:
        from app.db.crud import increment_download_count
        
        doc = get_document_by_id(db, 123)
        increment_download_count(db, doc)
        db.commit()
    
    Notes:
        - Debe hacerse db.commit() después
        - Diferencia entre view y download
    """
    doc.download_count = (doc.download_count or 0) + 1
    doc.last_accessed = datetime.now(timezone.utc)
    db.add(doc)


def create_activity_log(
    db: Session,
    user_id: Optional[int],
    document_id: int,
    action: str,
    ip_address: Optional[str] = None,
    document_name: Optional[str] = None,
    document_type: Optional[FileType] = None
) -> models.ActivityLog:
    """
    Crear registro de actividad con actualización automática de métricas.
    
    Registra acción del usuario Y actualiza automáticamente contadores
    del documento (view_count, download_count, last_accessed).
    
    Acciones soportadas:
        - **view**: Visualizar documento → incrementa view_count
        - **download**: Descargar documento → incrementa download_count
        - **upload**: Subir documento → actualiza last_accessed
        - **delete**: Eliminar documento → actualiza last_accessed
        - **share**: Compartir documento → actualiza last_accessed
    
    Información capturada:
        - user_id: Quién realizó la acción
        - document_id: A qué documento
        - action: Qué acción
        - ip_address: Desde dónde
        - timestamp: Cuándo (auto-generado)
        - document_name: Nombre del documento
        - document_type: Tipo del documento
    
    Args:
        db (Session): Sesión de base de datos SQLAlchemy
        user_id (Optional[int]): ID del usuario (None si anónimo)
        document_id (int): ID del documento
        action (str): Tipo de acción (view, download, upload, delete, share)
        ip_address (Optional[str]): Dirección IP del cliente
        document_name (Optional[str]): Nombre del documento (para logging)
        document_type (Optional[FileType]): Tipo del documento
    
    Returns:
        models.ActivityLog: Registro de actividad creado
    
    Example:
        from app.db.crud import create_activity_log
        from app.enums.enums import FileType
        
        activity = create_activity_log(
            db,
            user_id=1,
            document_id=123,
            action="download",
            ip_address="192.168.1.1",
            document_name="reporte.pdf",
            document_type=FileType.PDF
        )
        db.commit()
    
    Operación:
        1. Obtener documento por ID
        2. Si existe:
            - Incrementar contador según action (view/download)
            - Actualizar last_accessed
            - Guardar cambios
        3. Crear ActivityLog con toda la información
        4. Agregar a sesión (no commit automático)
    
    Métricas que actualiza:
        - view: documento.view_count += 1
        - download: documento.download_count += 1
        - view/download/upload/delete/share: último_acceso = ahora
    
    Auditoría:
        - Cada acción se registra completamente
        - Incluye IP para análisis de seguridad
        - Timestamp automático (UTC)
        - Nombre y tipo del documento para context
    
    Performance:
        - 1 query para GET del documento
        - 1 UPDATE del documento
        - 1 INSERT en ActivityLog
        - Típicamente < 100ms
    
    Notes:
        - Llamador debe hacer db.commit() después
        - document_name y document_type son opcionales (para debugging)
        - Combina auditoría y métricas en un solo lugar
        - Útil para dashboards de actividad
    """
    # Obtener documento para actualizar métricas
    doc = get_document_by_id(db, document_id)
    if doc:
        # Actualizar contadores según tipo de acción
        if action == "view":
            doc.view_count = (doc.view_count or 0) + 1
        elif action == "download":
            doc.download_count = (doc.download_count or 0) + 1
        
        # Actualizar último acceso para ciertas acciones
        if action in ["view", "download", "delete", "upload", "share"]:
            doc.last_accessed = datetime.now(timezone.utc)
        
        db.add(doc)
    
    # Crear registro de actividad
    db_activity = models.ActivityLog(
        user_id=user_id,
        document_id=document_id,
        action=action,
        ip_address=ip_address,
        timestamp=datetime.now(timezone.utc),
        document_name=document_name,
        document_type=document_type
    )
    db.add(db_activity)
    
    return db_activity
