# auth_schemas.py 
"""
Este archivo contiene todos los esquemas Pydantic para autenticación y autorización.
"""

from pydantic import BaseModel, Field, EmailStr, field_validator, ConfigDict
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, EmailStr

# ========================================
#  EXCEPCIONES PERSONALIZADAS
# ========================================
class AuthServiceError(Exception):
    """Base exception for authentication service errors"""
    pass


class InvalidCredentialsError(AuthServiceError):
    """Invalid credentials error"""
    pass


class TokenExpiredError(AuthServiceError):
    """Token expired error"""
    pass


class TokenBlacklistedError(AuthServiceError):
    """Token blacklisted error"""
    pass


class UserNotFoundError(AuthServiceError):
    """User not found error"""
    pass


class UserAlreadyExistsError(AuthServiceError):
    """User already exists error"""
    pass


class WeakPasswordError(AuthServiceError):
    """Weak password error"""
    pass


class AccountLockedError(AuthServiceError):
    """Account locked due to too many failed attempts"""
    pass


class PermissionDeniedError(AuthServiceError):
    """Permission denied error"""
    pass


# ========================================
#  ESQUEMAS DE AUTENTICACIÓN
# ========================================

class Token(BaseModel):
    """Respuesta de token de acceso"""
    access_token: str = Field(..., description="JWT access token")
    refresh_token: str = Field(..., description="JWT refresh token")
    token_type: str = Field(default="bearer", description="Token type")

    model_config = ConfigDict(from_attributes=True)


class RefreshTokenRequest(BaseModel):
    """Request para renovar token"""
    refresh_token: str = Field(..., description="Valid refresh token")
    model_config = ConfigDict(from_attributes=True)

class LoginRequest(BaseModel):
    """Request de login alternativo (para casos que no usen OAuth2PasswordRequestForm)"""
    email: EmailStr = Field(..., description="User email")
    password: str = Field(..., description="User password")

    @field_validator('email')
    def email_must_be_lowercase(cls, v):
        return v.lower().strip()

    model_config = ConfigDict(from_attributes=True)


# ========================================
#  ESQUEMAS DE CAMBIO DE CONTRASEÑA
# ========================================

class ChangePasswordRequest(BaseModel):
    """Request para cambio de contraseña"""
    old_password: str = Field(..., description="Current password")
    new_password: str = Field(
        ...,
        min_length=8,
        description="New password (must meet security requirements)"
    )
    confirm_password: str = Field(..., description="Confirm new password")

    @field_validator('confirm_password')
    def passwords_match(cls, v, info):
        if 'new_password' in info.data and v != info.data['new_password']:
            raise ValueError('Las contraseñas no coinciden')
        return v

    model_config = ConfigDict(from_attributes=True)


class ResetPasswordRequest(BaseModel):
    """Request para reset de contraseña"""
    email: EmailStr = Field(..., description="User email for password reset")

    @field_validator('email')
    def email_must_be_lowercase(cls, v):
        return v.lower().strip()

    model_config = ConfigDict(from_attributes=True)


class ResetPasswordConfirm(BaseModel):
    """Confirmación de reset de contraseña"""
    token: str = Field(..., description="Reset token")
    new_password: str = Field(
        ...,
        min_length=8,
        description="New password"
    )
    confirm_password: str = Field(..., description="Confirm new password")

    @field_validator('confirm_password')
    def passwords_match(cls, v, info):
        if 'new_password' in info.data and v != info.data['new_password']:
            raise ValueError('Las contraseñas no coinciden')
        return v

    model_config = ConfigDict(from_attributes=True)


# ========================================
#  ESQUEMAS DE SESIÓN Y SEGURIDAD
# ========================================

class ActiveSessionInfo(BaseModel):
    """Información de sesión activa"""
    session_id: str
    user_id: int
    ip_address: str
    user_agent: str
    created_at: datetime
    last_activity: datetime
    is_current: bool = False

    model_config = ConfigDict(from_attributes=True)

class ActiveSessionsResponse(BaseModel):
    """Lista de sesiones activas del usuario"""
    user_id: int
    sessions: List[ActiveSessionInfo]
    total_sessions: int
    current_session_id: str

    model_config = ConfigDict(from_attributes=True)

class RevokeSessionRequest(BaseModel):
    """Request para revocar sesión"""
    session_id: Optional[str] = Field(None, description="Session ID to revoke (if None, revokes all)")
    revoke_all_except_current: bool = Field(False, description="Revoke all sessions except current")

    model_config = ConfigDict(from_attributes=True)


# ========================================
#  ESQUEMAS PARA FEATURES AVANZADAS
# ========================================
class TwoFactorSetupRequest(BaseModel):
    """Request para configurar 2FA"""
    method: str = Field(..., pattern="^(totp|sms|email)$")
    phone: Optional[str] = Field(None, pattern=r'^\+?1?\d{9,15}$')

    model_config = ConfigDict(from_attributes=True)

class TwoFactorVerifyRequest(BaseModel):
    """Request para verificar 2FA"""
    code: str = Field(..., min_length=6, max_length=8)
    method: str = Field(..., pattern="^(totp|sms|email)$")

    model_config = ConfigDict(from_attributes=True)


class TrustedDeviceRequest(BaseModel):
    """Request para marcar dispositivo como confiable"""
    device_id: str
    trust: bool = True
    remember_for_days: int = Field(30, ge=1, le=365)

    model_config = ConfigDict(from_attributes=True)

# ========================================
#  ESQUEMAS PARA 2FA
# ========================================

class TwoFactorSetupResponse(BaseModel):
    """Respuesta al iniciar configuración de 2FA"""
    secret: str = Field(..., description="Secret key (para entrada manual)")
    qr_code: str = Field(..., description="Código QR en formato data URL")
    backup_codes: List[str] = Field(..., description="Códigos de respaldo")
    message: str = Field(..., description="Instrucciones para el usuario")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "secret": "JBSWY3DPEHPK3PXP",
                "qr_code": "data:image/png;base64,iVBORw0KGgoAAAANS...",
                "backup_codes": [
                    "A1B2C3D4",
                    "E5F6G7H8",
                    "I9J0K1L2",
                    "M3N4O5P6",
                    "Q7R8S9T0",
                    "U1V2W3X4",
                    "Y5Z6A7B8",
                    "C9D0E1F2"
                ],
                "message": "Escanea el código QR con Google Authenticator"
            }
        }
    )

class TwoFactorConfirmRequest(BaseModel):
    """Request para confirmar configuración de 2FA"""
    code: str = Field(..., min_length=6, max_length=6, pattern="^[0-9]{6}$")

    @field_validator('code')
    def code_must_be_numeric(cls, v):
        if not v.isdigit():
            raise ValueError('El código debe contener solo dígitos')
        return v

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "code": "123456"
            }
        }
    )


class TwoFactorDisableRequest(BaseModel):
    """Request para deshabilitar 2FA"""
    code: str = Field(..., description="Código TOTP o código de respaldo")

    @field_validator('code')
    def validate_code_format(cls, v):
        # Permitir código TOTP (6 dígitos) o código de respaldo (8 caracteres)
        if not (len(v) == 6 and v.isdigit()) and not (len(v) == 8):
            raise ValueError('Código inválido')
        return v.upper()

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "code": "123456"
            }
        }
    )


class BackupCodesResponse(BaseModel):
    """Respuesta con códigos de respaldo"""
    backup_codes: List[str] = Field(..., description="Códigos de respaldo generados")
    message: str = Field(..., description="Mensaje informativo")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "backup_codes": [
                    "A1B2C3D4",
                    "E5F6G7H8",
                    "I9J0K1L2",
                    "M3N4O5P6",
                    "Q7R8S9T0",
                    "U1V2W3X4",
                    "Y5Z6A7B8",
                    "C9D0E1F2"
                ],
                "message": "Guarda estos códigos en un lugar seguro"
            }
        }
    )


class TwoFactorStatusResponse(BaseModel):
    """Estado de 2FA del usuario"""
    enabled: bool = Field(..., description="Si 2FA está habilitado")
    enabled_at: Optional[datetime] = Field(None, description="Cuándo se habilitó")
    has_backup_codes: bool = Field(..., description="Si tiene códigos de respaldo")

    model_config = ConfigDict(from_attributes=True)


class LoginWith2FARequest(BaseModel):
    """Request de login con 2FA"""
    email: EmailStr = Field(..., description="Email del usuario")
    password: str = Field(..., description="Contraseña")
    totp_code: Optional[str] = Field(None, description="Código 2FA si está habilitado")

    @field_validator('email')
    def email_must_be_lowercase(cls, v):
        return v.lower().strip()

    @field_validator('totp_code')
    def validate_totp_code(cls, v):
        if v is not None:
            # Permitir código TOTP (6 dígitos) o código de respaldo (8 caracteres)
            if not (len(v) == 6 and v.isdigit()) and not (len(v) == 8):
                raise ValueError('Código 2FA inválido')
        return v.upper() if v else None

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "email": "usuario@example.com",
                "password": "MiPassword123!",
                "totp_code": "123456"
            }
        }
    )
# ========================================
#  ESQUEMAS DE PasswordResetRequest
# ========================================
class PasswordResetRequest(BaseModel):
    email: EmailStr
