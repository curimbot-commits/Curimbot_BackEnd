# =========================================================
# IMPORTACIONES NECESARIAS
# =========================================================
from .auth_schemas import Token
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, field_validator
from datetime import datetime, timezone

from app.schemas.auth_schemas import ChangePasswordRequest
from app.enums.enums import LogAction, AIChannel, AIInteractionStatus
from app.schemas.common_schemas import AuthStatsResponse, LoginStatsResponse
from app.schemas.user_schemas import SecurityAlert, UserCreate, UserInfoResponse


# =========================================================
# ESQUEMAS DE LOGS DE SISTEMA (no cambian)
# =========================================================

class LogCreate(BaseModel):
    """Esquema para crear un nuevo log de sistema"""
    user_id: int
    action: LogAction
    detail: str


# =========================================================
# ESQUEMAS DE INTERACCIONES IA
# =========================================================

class AIInteractionLogOut(BaseModel):
    """Esquema de salida para una interacción con la IA"""
    id: int
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    question: str
    answer: Optional[str] = None
    channel: AIChannel
    confidence: Optional[float] = None
    status: AIInteractionStatus
    error_message: Optional[str] = None
    sources: Optional[List[int]] = None
    sources_info: Optional[List[dict]] = None
    processing_time_ms: Optional[int] = None
    from_cache: bool = False
    conversation_id: Optional[int] = None
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("timestamp")
    @classmethod
    def _timestamp_utc(cls, v: datetime) -> datetime:
        # MySQL devuelve DATETIME sin zona; se guarda en UTC (utc_now).
        # Sin zona, el navegador lo interpretaría como hora local.
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v


class AIInteractionFilters(BaseModel):
    """Filtros para consultar interacciones IA"""
    channel: Optional[AIChannel] = None
    status: Optional[AIInteractionStatus] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    user_id: Optional[int] = None
    from_cache: Optional[bool] = None

    @classmethod
    def validate_channel(cls, v):
        if isinstance(v, str):
            try:
                return AIChannel(v)
            except ValueError:
                raise ValueError(f"Canal inválido: {v}")
        return v


# =========================================================
# CONFIGURACIÓN FINAL DE ESQUEMAS
# =========================================================

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
