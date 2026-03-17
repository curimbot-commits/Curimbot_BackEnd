"""
Módulo de autenticación y seguridad de usuarios.

Endpoints de login/logout, registro, renovación de tokens, 2FA y alertas de login.
"""

from fastapi.responses import JSONResponse
from app.services import security_service
from app.services.security_service import verify_password
import logging
from datetime import datetime
from typing import List
from .....schemas.auth_schemas import (
    ActiveSessionsResponse, BackupCodesResponse, RefreshTokenRequest,
    ResetPasswordRequest, Token, TwoFactorConfirmRequest, TwoFactorDisableRequest,
    TwoFactorSetupResponse, TwoFactorVerifyRequest
)

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status, Body
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.models import User, LoginAlert
from app.schemas.user_schemas import UserCreate, UserInfoResponse
from app.services.auth_service import (
    AccountLockedError, AuthService, InvalidCredentialsError,
    TokenBlacklistedError, TokenExpiredError, TwoFactorAuthService, TwoFactorRequiredError,
    UserAlreadyExistsError, UserNotFoundError, WeakPasswordError, get_client_info,
    get_current_user, require_admin
)

from app.services.login_alert_service import LoginAlertService
from app.services.email_service import EmailService
from app.services.notification_service import NotificationService
from app.core.config import RESEND_API_KEY, FROM_EMAIL


# ========================================
# CONFIGURACIÓN
# ========================================

router = APIRouter(prefix="/auth", tags=["authentication"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
logger = logging.getLogger(__name__)


# ========================================
# ENDPOINTS DE AUTENTICACIÓN BÁSICA
# ========================================

@router.post("/login", response_model=Token, summary="Iniciar sesión")
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    request: Request = None,
    db: Session = Depends(get_db)
):
    """
    Autentica usuario con email y contraseña, retorna tokens de acceso.
    Si el usuario tiene 2FA habilitado, retorna `requires_2fa: true`.

    Raises:
        HTTPException 401: Credenciales inválidas.
        HTTPException 423: Cuenta bloqueada por múltiples intentos fallidos.
    """
    try:
        ip_address, user_agent = get_client_info(request) if request else ("unknown", "unknown")

        result = AuthService.login_user(
            form_data.username,
            form_data.password,
            db,
            ip_address,
            user_agent
        )

        if isinstance(result, dict) and result.get("requires_2fa"):
            return JSONResponse(
                status_code=200,
                content={
                    "requires_2fa": True,
                    "message": "Verificación de dos factores requerida"
                }
            )

        access_token, refresh_token = result
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer"
        }

    except InvalidCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas"
        )
    except AccountLockedError:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Cuenta bloqueada"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Unexpected error during login: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno del servidor durante el login"
        )


@router.post("/signup", response_model=Token, status_code=status.HTTP_201_CREATED, summary="Registrar nuevo usuario")
def signup(
    user_data: UserCreate,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Crea una nueva cuenta de usuario y retorna tokens de autenticación.
    La contraseña debe tener mayúsculas, minúsculas, números y caracteres especiales.

    Raises:
        HTTPException 400: Contraseña no cumple requisitos de seguridad.
        HTTPException 409: Usuario ya existe con ese email.
    """
    try:
        ip_address, _ = get_client_info(request)
        access_token, refresh_token = AuthService.signup_user(user_data, db, ip_address)
        
        # Enviar notificación de bienvenida / seguridad
        try:
            user = db.query(User).filter(User.email == user_data.email.lower()).first()
            if user:
                email_service = EmailService(api_key=RESEND_API_KEY, from_email=FROM_EMAIL)
                notification_service = NotificationService(email_service)
                notification_service.send_notification(
                    user_id=user.id,
                    notification_type=NotificationType.SECURITY_ALERT,
                    subject="🚀 ¡Bienvenido a Curim AI!",
                    content=f"Hola {user.name}, tu cuenta ha sido creada exitosamente.",
                    db=db
                )
        except Exception as e:
            logger.warning(f"Failed to send welcome notification: {e}")

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer"
        }

    except UserAlreadyExistsError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except WeakPasswordError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Unexpected error during signup: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno del servidor durante el registro"
        )


@router.post("/logout", status_code=status.HTTP_200_OK, summary="Cerrar sesión")
def logout(
    response: Response,
    token: str = Depends(oauth2_scheme),
    data: RefreshTokenRequest = Body(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Invalida el refresh token del usuario agregándolo a la blacklist.

    Raises:
        HTTPException 401: Token ya estaba invalidado.
    """
    try:
        was_blacklisted = AuthService.logout_user(data.refresh_token, db)

        if not was_blacklisted:
            raise HTTPException(status_code=401, detail="Token ya estaba invalidado")

        logger.info(f"User logged out: {current_user.email}")
        return {"message": "Sesión cerrada correctamente"}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Unexpected error during logout: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno del servidor durante el logout"
        )


@router.post("/refresh", response_model=Token, summary="Renovar tokens")
def refresh_token(
    data: RefreshTokenRequest,
    db: Session = Depends(get_db)
):
    """
    Renueva tokens de acceso usando un refresh token válido.
    El refresh token antiguo se invalida automáticamente.

    Raises:
        HTTPException 401: Token expirado o en lista negra.
        HTTPException 404: Usuario no encontrado.
    """
    try:
        access_token, refresh_token = AuthService.refresh_tokens(data.refresh_token, db)
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer"
        }

    except (TokenExpiredError, TokenBlacklistedError) as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except UserNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Unexpected error during token refresh: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno del servidor durante la renovación de tokens"
        )


# ========================================
# ENDPOINTS DE AUTENTICACIÓN CON 2FA
# ========================================

@router.post("/login-with-2fa", response_model=Token)
def login_with_2fa(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    totp_code: str = Form(...),
    db: Session = Depends(get_db)
):
    """
    Inicia sesión con credenciales + código TOTP (o código de respaldo).
    Envía alerta por email si el login proviene de un dispositivo o ubicación nueva.

    Raises:
        HTTPException 401: Credenciales inválidas o código 2FA expirado/incorrecto.
    """
    try:
        user = db.query(User).filter(User.email == form_data.username).first()
        if not user or not verify_password(form_data.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Credenciales inválidas")

        if not TwoFactorAuthService.verify_totp_code(user.two_factor_secret, totp_code):
            if not TwoFactorAuthService.verify_backup_code(user, totp_code, db):
                raise HTTPException(status_code=401, detail="Código inválido")

        token_data = {
            "sub": str(user.id),
            "role": user.role.name,
            "email": user.email
        }
        access_token = security_service.create_access_token(token_data)
        refresh_token = security_service.create_refresh_token(token_data)

        # Crear sesión activa
        ip_address, user_agent = get_client_info(request) if request else ("unknown", "unknown")
        from app.services.session_service import SessionService
        SessionService.create_session(
            user_id=user.id,
            access_token=access_token,
            refresh_token=refresh_token,
            ip_address=ip_address,
            user_agent=user_agent,
            db=db,
            is_current=True
        )

        AuthService.update_last_login(user, db)

        try:
            email_service = EmailService(api_key=RESEND_API_KEY, from_email=FROM_EMAIL)
            notification_service = NotificationService(email_service)
            alert_service = LoginAlertService(notification_service)
            alert_service.record_login_and_check(user, request, db)
        except Exception as alert_error:
            logger.warning(f"Failed to record login alert: {alert_error}")

        logger.info(f"Successful login for user: {user.email}")
        return Token(access_token=access_token, refresh_token=refresh_token)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error during login: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al procesar inicio de sesión"
        )


# ========================================
# ENDPOINTS DE ALERTAS DE LOGIN
# ========================================

@router.get("/login-alerts/recent")
def get_recent_login_alerts(
    days: int = 30,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Retorna alertas de inicio de sesión recientes del usuario (nuevos dispositivos,
    ubicaciones o actividad sospechosa).

    Args:
        days: Número de días hacia atrás a consultar (default 30).
    """
    try:
        alerts = LoginAlertService.get_recent_login_alerts(
            user=current_user,
            days=days,
            db=db
        )
        return {
            "total": len(alerts),
            "alerts": [
                {
                    "id": alert.id,
                    "device": alert.device,
                    "location": alert.location,
                    "ip_address": alert.ip_address,
                    "is_suspicious": alert.is_suspicious,
                    "is_new_device": alert.is_new_device,
                    "is_new_location": alert.is_new_location,
                    "created_at": alert.created_at.isoformat()
                }
                for alert in alerts
            ]
        }
    except Exception as e:
        logger.exception(f"Error getting login alerts for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener alertas de login"
        )


@router.delete("/login-alerts/{alert_id}")
def dismiss_login_alert(
    alert_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Descarta una alerta de inicio de sesión del usuario autenticado.

    Raises:
        HTTPException 404: Alerta no encontrada o no pertenece al usuario.
    """
    try:
        alert = db.query(LoginAlert).filter(
            LoginAlert.id == alert_id,
            LoginAlert.user_id == current_user.id
        ).first()

        if not alert:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Alerta no encontrada"
            )

        db.delete(alert)
        db.commit()
        return {"message": "Alerta descartada exitosamente"}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error dismissing login alert {alert_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al descartar alerta"
        )
