"""
Esquemas Pydantic para preferencias de usuario
app/schemas/user_preferences_schemas.py
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field, field_validator, ConfigDict
from enum import Enum


class ThemeEnum(str, Enum):
    """Temas disponibles para la interfaz"""
    LIGHT = "light"
    DARK = "dark"
    AUTO = "auto"


class LanguageEnum(str, Enum):
    """Idiomas soportados"""
    ES = "es"
    EN = "en"


class WeeklySummaryFormatEnum(str, Enum):
    """Formatos disponibles para el resumen semanal"""
    PDF = "pdf"
    EXCEL = "excel"



# ========================================
# NOTIFICATION PREFERENCES
# ========================================

class NotificationPreferencesUpdate(BaseModel):
    """Actualización de preferencias de notificaciones"""
    email_notifications: Optional[bool] = None
    push_notifications: Optional[bool] = None
    weekly_summary: Optional[bool] = None
    weekly_summary_format: Optional[WeeklySummaryFormatEnum] = Field(None, description="Formato del resumen semanal (pdf, excel)")
    login_alerts: Optional[bool] = Field(None, description="Alertas de inicio de sesión")
    security_alerts: Optional[bool] = Field(None, description="Alertas de seguridad y cambios de cuenta")

    class Config:
        json_schema_extra = {
            "example": {
                "email_notifications": True,
                "push_notifications": False,
                "weekly_summary": True,
                "weekly_summary_format": "pdf",
                "login_alerts": True,
                "security_alerts": True
            }
        }

class InterfacePreferencesUpdate(BaseModel):
    """Actualización de preferencias de interfaz"""
    language: Optional[LanguageEnum] = Field(None, description="Idioma de la interfaz")
    theme: Optional[ThemeEnum] = Field(None, description="Tema visual")

    model_config = ConfigDict(from_attributes=True)

class UserProfileUpdate(BaseModel):
    """Actualización de perfil de usuario"""
    name: Optional[str] = Field(None, min_length=2, max_length=100, description="Nombre completo")
    email: Optional[EmailStr] = Field(None, description="Correo electrónico")
    
    @field_validator('email')
    def email_must_be_lowercase(cls, v):
        if v:
            return v.lower().strip()
        return v
    
    @field_validator('name')
    def name_must_be_clean(cls, v):
        if v:
            v = v.strip()
            if len(v) < 2:
                raise ValueError("El nombre debe tener al menos 2 caracteres")
        return v

    model_config = ConfigDict(from_attributes=True)

class ProfilePhotoResponse(BaseModel):
    """Respuesta de actualización de foto de perfil"""
    message: str
    photo_url: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)

class UserPreferencesResponse(BaseModel):
    """Respuesta completa de preferencias del usuario"""
    # Notificaciones
    email_notifications: bool = True
    push_notifications: bool = False
    weekly_summary: bool = True
    weekly_summary_format: WeeklySummaryFormatEnum = WeeklySummaryFormatEnum.PDF
    login_alerts: bool = True
    security_alerts: bool = True

    
    # Interfaz
    language: LanguageEnum = LanguageEnum.ES
    theme: ThemeEnum = ThemeEnum.LIGHT
    
    # Perfil
    profile_photo_url: Optional[str] = None
    
    # Metadata
    user_id: int
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class EmailNotificationRequest(BaseModel):
    """Request para enviar notificación por email"""
    subject: str = Field(..., min_length=1, max_length=200)
    message: str = Field(..., min_length=1)
    
    model_config = ConfigDict(from_attributes=True)

# ========================================
# LOGIN ALERTS
# ========================================

class LoginAlertConfig(BaseModel):
    """Configuración de alertas de inicio de sesión"""
    enabled: bool = True
    notify_on_new_device: bool = True
    notify_on_new_location: bool = True
    notify_on_suspicious_activity: bool = True

    class Config:
        json_schema_extra = {
            "example": {
                "enabled": True,
                "notify_on_new_device": True,
                "notify_on_new_location": True,
                "notify_on_suspicious_activity": True
            }
        }

class LoginAlertInfo(BaseModel):
    """Información de inicio de sesión para alertas"""
    device: str
    location: str
    ip_address: str
    timestamp: datetime
    is_suspicious: bool = False

    class Config:
        json_schema_extra = {
            "example": {
                "device": "Chrome en Windows",
                "location": "Madrid, España",
                "ip_address": "192.168.1.1",
                "timestamp": "2024-01-15T10:30:00",
                "is_suspicious": False
            }
        }

