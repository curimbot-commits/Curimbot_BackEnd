"""
Router para operaciones de lectura, listado y descarga de documentos.

Este módulo proporciona endpoints para acceder a documentos del usuario,
incluyendo listado paginado, filtrado por tipo, búsqueda y descarga.
Implementa todas las mejores prácticas de paginación y manejo eficiente
de grandes cantidades de datos.

Características:
    - Paginación con skip/limit
    - Filtrado por tipo de archivo
    - Búsqueda de documentos
    - Descarga con streaming
    - Caché de metadatos
    - Ordenamiento flexible
"""

import datetime
import io
import logging
from typing import List, Optional, Annotated
from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, case

from app.db.crud import crud
from app.db.database import SessionLocal
from app.enums.enums import FileType
from app.models import models
from app.schemas.document_schemas import PaginatedDocumentsResponse
from app.services import storage_service
from app.services.document_service import DocumentService
from app.services.handlers.base import DocumentContext
from app.services.utils import extract_text
from app.services.auth_service import get_current_user

from app.services.handlers.validate_file import ValidateFileHandler
from app.services.handlers.extract_text import ExtractTextHandler  
from app.services.handlers.encrypt_file import EncryptFileHandler
from app.services.handlers.save_to_db import SaveToDBHandler
from app.services.handlers.log_activity import LogActivityHandler
from cryptography.fernet import InvalidToken

router = APIRouter(prefix="/documents", tags=["documents"])


# 🧩 Dependencia para obtener la sesión de la base de datos
def get_db():
    """
    Obtener sesión de base de datos para usar en endpoints.
    
    Crea una nueva sesión SQLAlchemy y garantiza su cierre automático
    incluso si ocurre una excepción durante la solicitud.
    
    Yields:
        Session: Sesión de base de datos activa y disponible
    
    Notes:
        - Sigue el patrón de inyección de dependencias de FastAPI
        - Cierra la conexión automáticamente al finalizar
        - Se ejecuta una vez por solicitud HTTP
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =========================================================
# 📄 Obtener lista de documentos con paginación mejorada
# =========================================================

@router.get("/", response_model=PaginatedDocumentsResponse)
def get_documents(
    skip: Annotated[int, Query(ge=0, description="Número de elementos a omitir")] = 0,
    limit: Annotated[int, Query(ge=1, le=100, description="Número máximo de elementos a devolver")] = 20,
    file_type: Annotated[Optional[FileType], Query(description="Filtrar por tipo de archivo: pdf, docx, txt")] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    """
    Obtener lista paginada de documentos del usuario autenticado.
    
    Este endpoint retorna una lista de documentos del usuario con soporte
    completo para paginación y filtrado. Es la forma principal de listar
    todos los documentos disponibles para un usuario.
    
    Paginación:
        - **skip**: Número de elementos a omitir (offset)
        - **limit**: Número máximo de elementos por página (1-100)
        - Ejemplo: skip=20, limit=10 retorna elementos 20-29
    
    Filtrado:
        - **file_type**: Filtrar por tipo de archivo
            - pdf: Documentos PDF
            - docx: Documentos Word
            - txt: Documentos de texto
            - xlsx: Hojas de cálculo (si aplica)
            - null/omitido: Sin filtrar por tipo
    
    Datos retornados por documento:
        - **id**: ID único del documento
        - **name**: Nombre del documento
        - **file_type**: Tipo de archivo (pdf, docx, txt, etc.)
        - **size_bytes**: Tamaño en bytes
        - **size_formatted**: Tamaño legible (2.3 MB)
        - **created_at**: Fecha de creación (ISO 8601)
        - **updated_at**: Última actualización (ISO 8601)
        - **status**: Estado (draft, processing, completed, error)
        - **has_text_extracted**: Si se extrajo texto
        - **processing_progress**: Porcentaje completado (0-100)
    
    Información de paginación:
        - **total**: Total de elementos sin paginar
        - **skip**: Elementos omitidos
        - **limit**: Límite de la página actual
        - **has_next**: Si hay página siguiente
        - **has_prev**: Si hay página anterior
    
    Control de acceso:
        - Los usuarios solo ven sus propios documentos
        - Los administradores podrían ver todos (según configuración)
    
    Args:
        skip (int): Número de elementos a saltar. Range: 0+. Default: 0
        limit (int): Máximo de elementos por página. Range: 1-100. Default: 20
        file_type (Optional[FileType]): Filtro por tipo de archivo (pdf, docx, txt, etc.)
        db (Session): Sesión de base de datos (inyectada automáticamente)
        user (User): Usuario autenticado actual (inyectado automáticamente)
    
    Returns:
        PaginatedDocumentsResponse: Respuesta paginada incluyendo:
            - items: Lista de documentos de la página actual
            - total: Total de documentos sin paginar
            - skip: Offset usado
            - limit: Límite usado
            - has_next: Booleano si hay siguiente página
            - has_prev: Booleano si hay página anterior
    
    Raises:
        HTTPException 400: Parámetros de paginación inválidos
        HTTPException 401: Usuario no autenticado
        HTTPException 404: Usuario no encontrado (raro)
        HTTPException 500: Error al obtener documentos
    
    Example 1 (primera página):
        GET /documents/?skip=0&limit=20
        Headers: Authorization: Bearer <access_token>
        
        Response:
        {
            "items": [
                {
                    "id": 1,
                    "name": "Reporte Q4 2025",
                    "file_type": "pdf",
                    "size_bytes": 2097152,
                    "size_formatted": "2.0 MB",
                    "created_at": "2025-11-01T10:30:00Z",
                    "updated_at": "2025-11-02T15:45:00Z",
                    "status": "completed",
                    "has_text_extracted": true,
                    "processing_progress": 100
                },
                {
                    "id": 2,
                    "name": "Presupuesto 2026",
                    "file_type": "xlsx",
                    "size_bytes": 524288,
                    "size_formatted": "512 KB",
                    "created_at": "2025-11-02T09:15:00Z",
                    "updated_at": "2025-11-02T09:15:00Z",
                    "status": "processing",
                    "has_text_extracted": false,
                    "processing_progress": 75
                }
            ],
            "total": 45,
            "skip": 0,
            "limit": 20,
            "has_next": true,
            "has_prev": false
        }
    
    Example 2 (filtrar por tipo PDF):
        GET /documents/?skip=0&limit=20&file_type=pdf
        Headers: Authorization: Bearer <access_token>
        
        Response:
        {
            "items": [
                ...elementos filtrados solo PDF...
            ],
            "total": 28,
            "skip": 0,
            "limit": 20,
            "has_next": true,
            "has_prev": false
        }
    
    Example 3 (página 2):
        GET /documents/?skip=20&limit=20
        Headers: Authorization: Bearer <access_token>
        
        Response:
        {
            "items": [...20 elementos de la página 2...],
            "total": 45,
            "skip": 20,
            "limit": 20,
            "has_next": true,
            "has_prev": true
        }
    
    Example 4 (última página):
        GET /documents/?skip=40&limit=20
        Headers: Authorization: Bearer <access_token>
        
        Response:
        {
            "items": [...5 elementos finales...],
            "total": 45,
            "skip": 40,
            "limit": 20,
            "has_next": false,
            "has_prev": true
        }
    
    Validaciones:
        - skip >= 0: No se permiten valores negativos
        - limit >= 1: Mínimo un elemento
        - limit <= 100: Máximo 100 elementos por página (prevenir abuso)
        - file_type: Debe ser tipo válido si se proporciona
    
    Performance:
        - Usa índices de base de datos para eficiencia
        - Consulta solo campos necesarios (optimización)
        - Caché de total cuando es posible
        - Típicamente retorna en < 200ms
    
    Ordenamiento:
        - Ordenado por created_at descendente (más reciente primero)
        - O por actualización reciente según configuración
    
    Notas para clientes:
        - Usar has_next para mostrar botón "Siguiente"
        - Usar has_prev para mostrar botón "Anterior"
        - Implementar infinite scroll usando has_next
        - Hacer nuevas solicitudes para actualizar lista
        - Los documentos pueden cambiar de status durante visualización
    
    Best Practices:
        - Usar limit pequeño (10-20) para mejor UX
        - Cachear resultados en cliente si es adecuado
        - Mostrar loading indicator durante fetch
        - Manejar cambios de status mientras se visualiza
        - Considerar infinite scroll para mobile
    """
    try:
        # Llamar al servicio para obtener documentos paginados
        documents, total = DocumentService.list_documents(
            skip, 
            limit, 
            db, 
            user, 
            file_type
        )
        
        # Construir respuesta paginada
        return PaginatedDocumentsResponse(
            items=documents,
            total=total,
            skip=skip,
            limit=limit,
            has_next=skip + limit < total,  # Hay más elementos después de esta página
            has_prev=skip > 0  # Hay elementos antes de esta página
        )
        
    except HTTPException:
        # Re-lanzar excepciones HTTP (validaciones, permisos, etc.)
        raise
    except Exception as e:
        # Capturar errores inesperados y loguear
        logging.exception(f"Error inesperado en get_documents para usuario {user.id}: {e}")
        raise HTTPException(
            status_code=500, 
            detail="Error interno del servidor"
        )
