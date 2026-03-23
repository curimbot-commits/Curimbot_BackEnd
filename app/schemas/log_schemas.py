# =========================================================
# IMPORTACIONES NECESARIAS
# =========================================================
from .auth_schemas import Token
from typing import List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator
from datetime import datetime
from app.schemas.auth_schemas import ChangePasswordRequest
from app.enums.enums import FileType, LogAction
from app.schemas.common_schemas import AuthStatsResponse, LoginStatsResponse
from app.schemas.user_schemas import SecurityAlert, UserCreate, UserInfoResponse

# =========================================================
# ESQUEMAS DE LOGS
# =========================================================

class LogCreate(BaseModel):
    """Esquema para crear un nuevo log"""
    user_id: int
    action: LogAction  
    detail: str  

class LogOut(BaseModel):
    """Esquema para un log de salida con más detalles"""
    id: int
    user_id: int
    action: LogAction
    detail: str
    created_at: datetime  

    model_config = ConfigDict(from_attributes=True)  

# =========================================================
# ESQUEMAS DE ACTIVIDADES RECIENTES
# =========================================================
class ActivityLogOut(BaseModel):
    """Esquema para registrar una actividad de un usuario"""
    id: int
    action: str  
    document_id: Optional[int] = None  
    document_name: str  
    document_type: Union[FileType, str]  
    user_id: Optional[int] = None  
    user_name: Optional[str] = None  
    timestamp: datetime  
    ip_address: Optional[str] = None  

    model_config = ConfigDict(from_attributes=True)  

    @field_validator("document_type", mode="before")
    @classmethod
    def validate_file_type(cls, v):
        """Valida si el tipo de documento es un valor válido de FileType o una cadena"""
        if isinstance(v, str):
            try:
                return FileType(v)  
            except ValueError:
                raise ValueError(f"Tipo de archivo inválido: {v}")  
        return v

    @field_validator("document_type", mode="after")
    @classmethod
    def file_type_to_enum(cls, v):
        """Convierte el tipo de documento a un enum si es una cadena"""
        if isinstance(v, str):
            try:
                return FileType(v)  
            except ValueError:
                return v  
        return v

class ActivityLogFilters(BaseModel):
    """Filtros para consultar logs de actividades"""
    action: Optional[str] = Field(None, pattern="^(upload|download|view|delete)$")  
    date_from: Optional[datetime] = None  
    date_to: Optional[datetime] = None  
    document_id: Optional[int] = None  
    ip_address: Optional[str] = None  


# =========================================================
# RESPUESTAS PAGINADAS DE ACTIVIDADES
# =========================================================

class PaginatedActivitiesResponse(BaseModel):
    """Respuesta paginada con los resultados de actividades"""
    items: List[ActivityLogOut]  
    total: int  
    skip: int  
    limit: int  
    has_next: bool  
    has_prev: bool  
    filters_applied: Optional[ActivityLogFilters] = None  
    
    class Config:
        from_attributes = True  


# =========================================================
# CONFIGURACIÓN FINAL DE ESQUEMAS
# =========================================================

# Configuración adicional para asegurar la correcta serialización y documentación
for schema_class in [
    UserCreate, UserInfoResponse, Token, ChangePasswordRequest,
    LoginStatsResponse, AuthStatsResponse, SecurityAlert
]:
    if hasattr(schema_class, 'Config'):
        schema_class.Config.json_encoders = {
            datetime: lambda v: v.isoformat() if v else None  
        }
        schema_class.Config.allow_population_by_field_name = True  
        schema_class.Config.use_enum_values = True  