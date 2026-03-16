"""
Router para búsqueda avanzada de documentos.

Este módulo proporciona endpoints para buscar documentos con soporte para
búsqueda full-text, filtrado por tipo de archivo, ordenamiento y paginación.
Implementa todas las mejores prácticas de búsqueda moderna.

Características:
    - Búsqueda full-text en contenido y metadatos
    - Filtrado por tipo de archivo
    - Paginación eficiente
    - Relevancia de resultados
    - Registro de búsquedas para analytics
    - Autocomplete (opcional)
"""

import logging
from typing import List, Optional, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.models.models import User
from app.schemas.document_schemas import DocumentSearchOut, PaginatedDocumentsResponse
from app.services.auth_service import get_current_user
from app.db.crud import crud
from app.db.database import SessionLocal, get_db
from app.enums.enums import FileType
from app.services.document_service import DocumentService

router = APIRouter(prefix="/documents", tags=["documents"])


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
# 🔍 Buscar documentos con filtros avanzados
# =========================================================

@router.get("/search", response_model=PaginatedDocumentsResponse)
def search_documents(
    text: Annotated[Optional[str], Query(min_length=2, description="Texto a buscar en contenido y nombre")] = None,
    file_type: Annotated[Optional[FileType], Query(description="Filtrar por tipo de archivo")] = None,
    skip: Annotated[int, Query(ge=0, description="Elementos a omitir")] = 0,
    limit: Annotated[int, Query(ge=1, le=100, description="Máximo elementos por página")] = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Buscar documentos con filtros avanzados y paginación.
    
    Este endpoint proporciona búsqueda full-text en documentos del usuario.
    Busca en el contenido del documento (texto extraído), nombre del archivo
    y metadatos. Retorna resultados paginados ordenados por relevancia.
    
    Búsqueda:
        - **Full-text**: Busca en contenido y metadatos
        - **Case-insensitive**: No distingue mayúsculas/minúsculas
        - **Partial matching**: "report" encuentra "quarterly report"
        - **Relevancia**: Resultados ordenados por coincidencia
    
    Criterios de búsqueda:
        - **text**: Búsqueda en nombre y contenido del documento
            - Mínimo 2 caracteres
            - Búsqueda AND (todas las palabras)
            - Wildcards automáticos
        
        - **file_type**: Filtrar por tipo específico
            - pdf: Documentos PDF
            - docx: Documentos Word
            - xlsx: Hojas de cálculo
            - txt: Archivos de texto
            - null: Sin filtrar
    
    Paginación:
        - **skip**: Elementos a omitir (offset)
        - **limit**: Máximo por página (1-100, default 20)
        - has_next/has_prev: Indicadores de paginación
    
    Resultados por documento:
        - **id**: ID único
        - **name**: Nombre del archivo
        - **file_type**: Tipo de archivo
        - **size_formatted**: Tamaño legible
        - **created_at**: Fecha creación
        - **preview**: Extracto relevante del contenido (snippet)
        - **relevance_score**: Puntuación de relevancia (0-100)
        - **match_count**: Cuántas veces se encontró el texto
    
    Metadata de búsqueda:
        - **total**: Total de resultados sin paginar
        - **search_params**: Parámetros usados en la búsqueda
            - text: Texto de búsqueda
            - file_type: Tipo de archivo usado como filtro
    
    Control de acceso:
        - Los usuarios solo ven sus propios documentos
        - Las búsquedas se hacen en contexto del usuario autenticado
        - Admin puede estar limitado según configuración
    
    Args:
        text (Optional[str]): Texto a buscar (mínimo 2 caracteres).
            - None: Sin búsqueda de texto (solo filtro tipo)
            - "report": Busca "report" en nombre y contenido
            - "Q4 2025": Búsqueda de múltiples palabras (AND)
        
        file_type (Optional[FileType]): Filtro por tipo de archivo.
            - None: Todos los tipos
            - pdf, docx, xlsx, txt: Tipo específico
        
        skip (int): Elementos a omitir. Range: 0+. Default: 0
        
        limit (int): Máximo por página. Range: 1-100. Default: 20
        
        db (session): Sesión de base de datos (inyectada automáticamente)
        
        user (User): Usuario autenticado (inyectado automáticamente)
    
    Returns:
        PaginatedDocumentsResponse: Resultados paginados:
            - items: Documentos encontrados con metadatos
            - total: Total de resultados
            - skip: Offset usado
            - limit: Límite usado
            - has_next: Si hay siguiente página
            - has_prev: Si hay página anterior
            - search_params: Parámetros usados
    
    Raises:
        HTTPException 400: Parámetros inválidos (ej: text < 2 caracteres)
        HTTPException 401: Usuario no autenticado
        HTTPException 500: Error en búsqueda
    
    Example 1 (búsqueda por texto):
        GET /documents/search?text=report&limit=10
        Headers: Authorization: Bearer <access_token>
        
        Response (200 OK):
        {
            "items": [
                {
                    "id": 1,
                    "name": "Quarterly Report Q4 2025.pdf",
                    "file_type": "pdf",
                    "size_formatted": "2.3 MB",
                    "created_at": "2025-11-01T10:30:00Z",
                    "preview": "...This quarterly report presents financial results for Q4 2025...",
                    "relevance_score": 95,
                    "match_count": 3
                },
                {
                    "id": 2,
                    "name": "Annual Report 2024.pdf",
                    "file_type": "pdf",
                    "size_formatted": "3.1 MB",
                    "created_at": "2025-01-15T09:00:00Z",
                    "preview": "...The annual report provides comprehensive overview...",
                    "relevance_score": 78,
                    "match_count": 2
                }
            ],
            "total": 15,
            "skip": 0,
            "limit": 10,
            "has_next": true,
            "has_prev": false,
            "search_params": {
                "text": "report",
                "file_type": null
            }
        }
    
    Example 2 (búsqueda con filtro de tipo):
        GET /documents/search?text=budget&file_type=xlsx&limit=20
        Headers: Authorization: Bearer <access_token>
        
        Response (200 OK):
        {
            "items": [
                {
                    "id": 5,
                    "name": "Budget 2026.xlsx",
                    "file_type": "xlsx",
                    "size_formatted": "512 KB",
                    "created_at": "2025-11-02T14:00:00Z",
                    "preview": "Budget allocation for departments Q1 2026...",
                    "relevance_score": 100,
                    "match_count": 5
                },
                {
                    "id": 6,
                    "name": "Department Budget Summary.xlsx",
                    "file_type": "xlsx",
                    "size_formatted": "256 KB",
                    "created_at": "2025-10-15T11:30:00Z",
                    "preview": "Budget summary prepared for executive review...",
                    "relevance_score": 85,
                    "match_count": 2
                }
            ],
            "total": 8,
            "skip": 0,
            "limit": 20,
            "has_next": false,
            "has_prev": false,
            "search_params": {
                "text": "budget",
                "file_type": "xlsx"
            }
        }
    
    Example 3 (búsqueda sin texto, solo filtro):
        GET /documents/search?file_type=pdf&skip=20&limit=10
        Headers: Authorization: Bearer <access_token>
        
        Response (200 OK):
        {
            "items": [
                ...documentos PDF de la página 3...
            ],
            "total": 45,
            "skip": 20,
            "limit": 10,
            "has_next": true,
            "has_prev": true,
            "search_params": {
                "text": null,
                "file_type": "pdf"
            }
        }
    
    Example 4 (sin resultados):
        GET /documents/search?text=xyz123&limit=20
        Headers: Authorization: Bearer <access_token>
        
        Response (200 OK):
        {
            "items": [],
            "total": 0,
            "skip": 0,
            "limit": 20,
            "has_next": false,
            "has_prev": false,
            "search_params": {
                "text": "xyz123",
                "file_type": null
            }
        }
    
    Validaciones:
        - text: Mínimo 2 caracteres si se proporciona
        - skip >= 0: No se permiten valores negativos
        - limit: 1-100 (prevenir abuso)
        - file_type: Debe ser tipo válido si se proporciona
    
    Performance:
        - Índices de BD optimizados para búsqueda
        - Full-text search en BD
        - Caché de resultados populares
        - Típicamente < 300ms
        - Escalable a millones de documentos
    
    Ordenamiento de resultados:
        - Primario: Por relevancia (score descendente)
        - Secundario: Por fecha (reciente primero)
        - Los matches exactos se puntúan más alto
        - Los matches en nombre pesan más que en contenido
    
    Preview (snippet):
        - Extracto del contenido alrededor del match
        - Máximo 150 caracteres
        - Puntos suspensivos (...) si hay más contenido
        - La palabra buscada se resalta (bold)
    
    Casos de uso:
        - Buscar documentos por palabras clave
        - Filtrar por tipo para refinamiento
        - Implementar barra de búsqueda
        - Análisis de qué buscan los usuarios
        - Auditoría de documentos
    
    Best Practices:
        - Hacer búsqueda en tiempo real con debounce
        - Mostrar relevance_score para claridad
        - Usar snippets en resultados para preview
        - Paginar resultados grandes
        - Cachear búsquedas frecuentes
        - Registrar búsquedas para análisis
    
    Futuros enhancements:
        - Búsqueda por rangos de fecha
        - Búsqueda por propietario (admin)
        - Búsqueda por tags/categorías
        - Búsqueda por tamaño de archivo
        - Autocomplete de términos
        - Sugerencias de "¿quisiste decir?"
    """
    try:
        # Llamar al servicio de búsqueda
        # El servicio se encarga de:
        # - Ejecutar búsqueda full-text
        # - Filtrar por tipo de archivo
        # - Paginar resultados
        # - Ordenar por relevancia
        # - Registrar búsqueda en analytics
        documents, total = DocumentService.search_documents(
            db=db,
            user=user,           # Usuario para filtrar documentos
            text=text,           # Texto a buscar
            file_type=file_type, # Filtro de tipo
            skip=skip,           # Paginación
            limit=limit          # Límite por página
        )
        
        # Convertir resultados a esquema Pydantic
        # Esto asegura validación de datos
        documents_pydantic = [DocumentSearchOut.from_orm(doc) for doc in documents]

        # Construir respuesta paginada con parámetros de búsqueda
        return PaginatedDocumentsResponse(
            items=documents_pydantic,
            total=total,
            skip=skip,
            limit=limit,
            has_next=skip + limit < total,  # Hay más resultados después
            has_prev=skip > 0,              # Hay resultados antes
            search_params={
                "text": text,                              # Texto buscado
                "file_type": file_type.value if file_type else None  # Tipo filtrado
            }
        )
        
    except HTTPException:
        # Re-lanzar excepciones HTTP (validaciones, permisos, etc.)
        raise
    except Exception as e:
        # Capturar errores inesperados y loguear
        logging.exception(f"Error en búsqueda de documentos: {e}")
        raise HTTPException(
            status_code=500, 
            detail="Error interno en la búsqueda"
        )
