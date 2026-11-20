"""
Esquemas Pydantic para preferencias de usuario
app/schemas/user_preferences_schemas.py
"""
from datetime import datetime
from typing import Optional
from enum import Enum

from pydantic import BaseModel, EmailStr, Field, field_validator, ConfigDict


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
    weekly_summary_format: Optional[WeeklySummaryFormatEnum] = Field(
        None, description="Formato del resumen semanal (pdf, excel)"
    )
    login_alerts: Optional[bool] = Field(None, description="Alertas de inicio de sesión")
    security_alerts: Optional[bool] = Field(
        None, description="Alertas de seguridad y cambios de cuenta"
    )

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "email_notifications": True,
                "push_notifications": False,
                "weekly_summary": True,
                "weekly_summary_format": "pdf",
                "login_alerts": True,
                "security_alerts": True,
            }
        },
    )


class InterfacePreferencesUpdate(BaseModel):
    """Actualización de preferencias de interfaz"""
    language: Optional[LanguageEnum] = Field(None, description="Idioma de la interfaz")
    theme: Optional[ThemeEnum] = Field(None, description="Tema visual")

    model_config = ConfigDict(from_attributes=True)


class UserProfileUpdate(BaseModel):
    """Actualización de perfil de usuario"""
    name: Optional[str] = Field(
        None, min_length=2, max_length=100, description="Nombre completo"
    )
    email: Optional[EmailStr] = Field(None, description="Correo electrónico")

    @field_validator("email")
    @classmethod
    def email_must_be_lowercase(cls, v):
        if v:
            return v.lower().strip()
        return v

    @field_validator("name")
    @classmethod
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

    # Módulos
    convocatoria_enabled: bool = False

    # Metadata
    user_id: int
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
