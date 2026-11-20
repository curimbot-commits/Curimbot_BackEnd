
from typing import Optional, Dict, Any

from typing import Optional, Dict, Any
from datetime import datetime

from pydantic import BaseModel, Field


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
