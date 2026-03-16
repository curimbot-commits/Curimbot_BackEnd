
from typing import List, Optional, Dict, Any

from typing import List, Optional, Dict, Any 
from datetime import datetime, timezone

from pydantic import BaseModel, Field, conint

# ========================================
#  ESQUEMAS DE RESPUESTA UNIFICADOS
# ========================================
class SuccessResponse(BaseModel):
    """Respuesta de éxito genérica"""
    success: bool = True
    message: str
    data: Optional[Dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ErrorResponse(BaseModel):
    """Respuesta de error genérica"""
    success: bool = False
    error_code: str
    message: str
    details: Optional[Dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ValidationErrorDetail(BaseModel):
    """Detalle de error de validación"""
    field: str = Field(..., description="Field that failed validation")
    message: str = Field(..., description="Validation error message")
    rejected_value: Optional[str] = Field(None, description="The value that was rejected")

class ValidationErrorResponse(BaseModel):
    """Respuesta de errores de validación"""
    error_code: str = "validation_error"
    message: str = "Error de validación"
    details: List[ValidationErrorDetail]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class BulkOperationResponse(BaseModel):
    """Respuesta de operación en lote"""
    operation: str
    requested_count: int
    successful_count: int
    failed_count: int
    successful_ids: List[int]
    failed_operations: List[dict]
    executed_by: str
    executed_at: datetime
class SystemHealthResponse(BaseModel):
    """Respuesta de salud del sistema"""
    status: str = Field(..., pattern="^(healthy|degraded|unhealthy)$")
    service: str
    timestamp: datetime
    database: str
    redis: Optional[str] = None
    external_services: Optional[Dict[str, Any]] = None
    metrics: Optional[Dict[str, Any]] = None

class AssistantQuery(BaseModel):
    query: str
    top_k: Optional[conint(ge=1, le=100)] = 3

# ========================================
# ESQUEMAS PARA API VERSIONING
# ========================================

class APIVersion(BaseModel):
    """Información de versión de la API"""
    version: str
    release_date: datetime
    deprecated: bool = False
    sunset_date: Optional[datetime] = None
    changelog_url: Optional[str] = None

class APIInfoResponse(BaseModel):
    """Información general de la API"""
    service_name: str = "Authentication Service"
    current_version: str
    available_versions: List[APIVersion]
    documentation_url: str
    support_contact: str
    rate_limits: Dict[str, Any]
    terms_of_service_url: Optional[str] = None

class ServiceHealthResponse(BaseModel):
    """Respuesta del health check"""
    status: str = Field(..., description="Estado del servicio")
    service: str = Field(..., description="Nombre del servicio")
    timestamp: str = Field(..., description="Timestamp del check")
    database: str = Field(..., description="Estado de la base de datos")

class LoginAttemptDetails(BaseModel):
    """Detalles de un intento de login"""
    id: int
    email: str
    ip_address: str
    user_stats: Dict[str, Any]
    success: bool
    attempted_at: datetime
    
    class Config:
        from_attributes = True

class LoginStatsResponse(BaseModel):
    """Estadísticas de intentos de login"""
    email: str
    period_hours: int
    total_attempts: int
    successful_attempts: int
    failed_attempts: int
    success_rate: float = Field(..., description="Success rate percentage")
    last_attempt: Optional[datetime] = None

class AuthStatsResponse(BaseModel):
    """Estadísticas generales del servicio de autenticación"""
    service: str
    generated_at: datetime
    user_stats: dict
    activity_stats: Dict[str, Any]
    security_info: Dict[str, Any]
