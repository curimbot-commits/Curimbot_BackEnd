from datetime import datetime
import re
from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field, field_validator, ConfigDict, model_validator



# ========================================
# 📝 ESQUEMAS BASE DE USUARIO
# ========================================

class UserBase(BaseModel):
    """Esquema base de usuario"""
    email: EmailStr = Field(..., description="Email address of the user")
    name: str = Field(..., min_length=2, max_length=100, description="Full name of the user")

class UserCreate(UserBase):
    """Esquema para creación de usuario"""
    password: str = Field(
        ..., 
        min_length=8, 
        max_length=128,
        description="Password (min 8 chars, must include uppercase, lowercase, digit, special char)"
    )
    password_confirm: str = Field(
        ..., 
        description="Password confirmation (must match password)"
    )
    
    @field_validator('email')
    def email_must_be_lowercase(cls, v):
        return v.lower().strip()
    
    @field_validator('name')
    def name_must_be_clean(cls, v):
        v = v.strip()
        if len(v) < 2:
            raise ValueError("El nombre es demasiado corto")
        return v
    
    @field_validator('password_confirm')
    def passwords_match(cls, v, info):
        if 'password' in info.data and v != info.data['password']:
            raise ValueError('Las contraseñas no coinciden')
        return v

    @field_validator("password")
    def password_must_be_strong(cls, v):
        if (
            not re.search(r"[A-Z]", v) or       # Mayúscula
            not re.search(r"[a-z]", v) or       # Minúscula
            not re.search(r"\d", v) or          # Dígito
            not re.search(r"[^\w\s]", v)        # Carácter especial
        ):
            raise ValueError("La contraseña debe incluir al menos una mayúscula, una minúscula, un número y un carácter especial")
        return v


class UserUpdate(BaseModel):
    """Esquema para actualización de usuario"""
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    email: Optional[EmailStr] = None

    @model_validator(mode="before")
    @classmethod
    def at_least_one_field(cls, data):
        if not data.get('name') and not data.get('email'):
            raise ValueError("Debes proporcionar al menos 'name' o 'email'")
        return data


class UserInfoResponse(BaseModel):
    """Esquema de respuesta con información del usuario"""
    id: int
    email: str
    name: str
    role: str  
    created_at: datetime
    last_login: Optional[datetime] = None
    is_active: bool = True
    two_factor_enabled: bool
    profile_photo_url: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)

class UserManagementResponse(BaseModel):
    """Respuesta para operaciones de gestión de usuarios"""
    message: str
    user_id: int
    user_email: str
    new_role: str  
    updated_by: str
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


# ========================================
# ESQUEMAS DE ADMINISTRACIÓN
# ========================================
class RoleUpdateRequest(BaseModel):
    """Request para actualizar rol de usuario"""
    new_role: str = Field(
        ..., 
        description="New role for the user",
        pattern="^(admin|user)$"  # Validar que solo sean estos valores
    )
    
    model_config = ConfigDict(from_attributes=True)

class UserListFilters(BaseModel):
    """Filtros para listado de usuarios"""
    active_only: bool = Field(True, description="Only return active users")
    role: Optional[str] = Field(
        None, 
        description="Filter by role",
        pattern="^(admin|user)$"
    )
    search: Optional[str] = Field(
        None, 
        min_length=2,
        description="Search in name or email"
    )
    created_after: Optional[datetime] = Field(None, description="Filter users created after date")
    created_before: Optional[datetime] = Field(None, description="Filter users created before date")
    
    model_config = ConfigDict(from_attributes=True)

class UserListResponse(BaseModel):
    """Respuesta paginada de usuarios"""
    users: List[UserInfoResponse]
    total: int = Field(..., description="Total number of users")
    skip: int = Field(..., description="Number of users skipped")
    limit: int = Field(..., description="Maximum number of users returned")
    has_next: bool = Field(..., description="Whether there are more users")
    has_prev: bool = Field(..., description="Whether there are previous users")
    filters_applied: Optional[UserListFilters] = None


class SecuritySettings(BaseModel):
    """Configuración de seguridad del usuario"""
    two_factor_enabled: bool = False
    login_notifications: bool = True
    suspicious_activity_alerts: bool = True
    session_timeout_minutes: int = 30
    require_password_change_days: Optional[int] = None

class SecuritySettingsUpdate(BaseModel):
    """Actualización de configuración de seguridad"""
    login_notifications: Optional[bool] = None
    suspicious_activity_alerts: Optional[bool] = None
    session_timeout_minutes: Optional[int] = Field(None, ge=5, le=1440)  # 5 min to 24 hours
    require_password_change_days: Optional[int] = Field(None, ge=1, le=365)


# ========================================
# ESQUEMAS PARA NOTIFICACIONES
# ========================================

class NotificationPreferences(BaseModel):
    """Preferencias de notificaciones del usuario"""
    login_alerts: bool = True
    suspicious_activity: bool = True
    password_expiry_warning: bool = True
    security_updates: bool = True
    marketing_communications: bool = False
    email_notifications: bool = True
    push_notifications: bool = False

class SecurityAlert(BaseModel):
    """Alerta de seguridad"""
    alert_id: str
    user_id: int
    alert_type: str = Field(..., pattern="^(login|suspicious_activity|password_change|account_locked)$")
    severity: str = Field(..., pattern="^(low|medium|high|critical)$")
    message: str
    details: dict
    created_at: datetime
    acknowledged: bool = False
    acknowledged_at: Optional[datetime] = None

