from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

class ActiveSessionOut(BaseModel):
    """Schema para retornar información de sesión activa al frontend"""
    id: int
    device: str
    browser: Optional[str] = "Navegador"
    os: Optional[str] = "Sistema Operativo"
    device_type: Optional[str] = "Desktop"
    location: Optional[str] = "Ubicación desconocida"
    ip_address: str
    last_active: datetime
    created_at: datetime
    is_current: bool
    is_active: bool = True
    expires_at: datetime
    
    class Config:
        from_attributes = True  

class RevokeSessionRequest(BaseModel):
    """Request para revocar una sesión específica"""
    session_id: int = Field(..., gt=0, description="ID de la sesión a revocar")


class RevokeAllSessionsRequest(BaseModel):
    """Request para revocar todas las sesiones excepto la actual"""
    except_current: bool = Field(True, description="Mantener la sesión actual activa")


class SessionStatsResponse(BaseModel):
    """Estadísticas de sesiones del usuario"""
    total_sessions: int
    active_sessions: int
    inactive_sessions: int
    current_device: Optional[str]
    last_login: Optional[datetime]