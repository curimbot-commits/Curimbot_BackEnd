from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.enums.enums import FileType

# =========================================================
# Esquemas de Documentos
# =========================================================

class DocumentCreate(BaseModel):
    filename: str = Field(..., min_length=1, description="Nombre del archivo")
    mimetype: str = Field(..., description="Tipo MIME del archivo")
    size: int = Field(..., gt=0, description="Tamaño en bytes")
    text: Optional[str] = Field(default=None, description="Texto extraído del archivo")
    blob_enc: Optional[bytes] = Field(default=None, description="Contenido binario (encriptado o no)")
    uploaded_by: int = Field(..., gt=0, description="ID del usuario que sube el documento")
    is_public: int = Field(default=0, description="0: privado, 1: público (compartido)")

class DocumentUpdate(BaseModel):
    filename: Optional[str] = None
    category: Optional[str] = None

class DocumentOut(BaseModel):
    id: int
    filename: str
    mimetype: str
    size: int
    file_type: FileType
    text: str
    created_at: datetime
    updated_at: datetime
    is_public: int = Field(default=0)

    Curim_indexed: bool = Field(default=False, description="Si fue indexado en Curim")
    Curim_chunks: int = Field(default=0, description="Número de chunks creados")
    
    model_config = ConfigDict(
        from_attributes=True  
    )
    

class DocumentSearchResults(BaseModel):
    results: List[DocumentOut]

# Actualizar DocumentOut para incluir nuevos campos
class DocumentOutEnhanced(DocumentOut):
    """Versión mejorada de DocumentOut con campos adicionales"""
    download_count: Optional[int] = Field(0, description="Número de descargas")
    view_count: Optional[int] = Field(0, description="Número de visualizaciones")
    last_accessed: Optional[datetime] = Field(None, description="Última vez que se accedió")
    is_encrypted: bool = Field(True, description="Si el documento está encriptado")
    content_preview: Optional[str] = Field(None, description="Preview del contenido (primeros 200 chars)")
    
    class Config:
        from_attributes = True

        # Documento con metadatos completos
class DocumentWithMetadata(BaseModel):
    id: int
    name: str
    file_type: FileType
    size: int
    upload_date: datetime
    last_accessed: Optional[datetime] = None
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    download_count: Optional[int] = 0
    view_count: Optional[int] = 0

    model_config = ConfigDict(from_attributes=True)

class DocumentSearchOut(BaseModel):
    id: int
    filename: str
    size: int
    file_type: FileType
    created_at: datetime
    uploaded_by_name: Optional[str] = Field(None, description="Nombre del usuario que subió el documento")

    model_config = ConfigDict(from_attributes=True)

# Esquema para filtros avanzados de búsqueda
class DocumentSearchFilters(BaseModel):
    """Filtros avanzados para búsqueda de documentos"""
    text: Optional[str] = Field(None, min_length=2, max_length=500)
    file_type: Optional[FileType] = None
    size_min: Optional[int] = Field(None, ge=0, description="Tamaño mínimo en bytes")
    size_max: Optional[int] = Field(None, ge=0, description="Tamaño máximo en bytes")
    date_from: Optional[datetime] = Field(None, description="Fecha de creación desde")
    date_to: Optional[datetime] = Field(None, description="Fecha de creación hasta")
    sort_by: Optional[Literal["created_at", "filename", "size", "file_type"]] = "created_at"
    sort_order: Optional[Literal["asc", "desc"]] = "desc"

class PaginatedDocumentsResponse(BaseModel):
    items: List[DocumentSearchOut]
    total: int = Field(..., description="Total de elementos disponibles")
    skip: int = Field(..., description="Elementos omitidos")
    limit: int = Field(..., description="Límite por página")
    has_next: bool = Field(..., description="Hay más páginas disponibles")
    has_prev: bool = Field(..., description="Hay páginas anteriores")
    search_params: Optional[Dict[str, Any]] = Field(None, description="Parámetros de búsqueda aplicados")
    class Config:
        from_attributes = True

class DocumentUploadResponse(BaseModel):
    """Respuesta de subida de documentos"""
    successful_uploads: List[DocumentOut]
    failed_uploads: Optional[List[Dict[str, str]]] = None
    total_processed: int
    success_count: int
    failure_count: int
    
    Curim_indexed_count: int = Field(default=0, description="Documentos indexados en Curim")
    class Config:
        from_attributes = True

# Esquema para configuración del usuario
class UserDocumentSettings(BaseModel):
    """Configuración de documentos por usuario"""
    max_file_size: int = Field(50 * 1024 * 1024, description="Tamaño máximo de archivo en bytes")
    max_file_types: int = 10
    allowed_file_types: List[FileType] = Field(default_factory=lambda: [FileType.pdf, FileType.docx, FileType.txt])
    auto_extract_text: bool = Field(True, description="Extraer texto automáticamente")
    auto_encrypt: bool = Field(True, description="Encriptar archivos automáticamente")
    retention_days: Optional[int] = Field(None, description="Días de retención (None = ilimitado)")
    
    class Config:
        from_attributes = True

class SearchResult(BaseModel):
    id: int
    title: str
    category: str
    created_at: datetime
    file_type: str
    match_snippet: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

# =========================================================
# Esquemas adicionales para documentos opcionales / checklist
# =========================================================

class DocumentChecklistItem(BaseModel):
    id: Optional[int] = None
    filename: str
    mimetype: Optional[str] = None
    size: Optional[int] = 0
    file_type: Optional[FileType] = None
    text: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    status: Optional[str] = Field("pending", description="Estado del documento: pending, uploaded, verified")

    model_config = ConfigDict(from_attributes=True)

class DocumentUploadResponse(BaseModel):
    """Respuesta de subida o creación de documentos"""
    successful_uploads: List[DocumentChecklistItem]
    failed_uploads: Optional[List[Dict[str, str]]] = []
    total_processed: int
    success_count: int
    failure_count: int
    Curim_indexed_count: int = 0

    model_config = ConfigDict(from_attributes=True)
