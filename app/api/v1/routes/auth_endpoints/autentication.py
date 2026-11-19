"""
Módulo de autenticación y seguridad de usuarios.

Proporciona los endpoints de autenticación de la API: inicio y cierre de
sesión, registro de usuarios, renovación de tokens, autenticación de dos
factores y gestión de alertas de inicio de sesión.

Las credenciales se transmiten mediante cookies HttpOnly configuradas a
través de `settings.COOKIE_*`, permitiendo despliegues consistentes entre
entornos de desarrollo (HTTP) y producción (HTTPS).
"""

from fastapi.responses import JSONResponse
from app.services import security_service
from app.services.security_service import verify_password
import logging
from datetime import datetime
from typing import List
from .....schemas.auth_schemas import (
    ActiveSessionsResponse,
    BackupCodesResponse,
    RefreshTokenRequest,
    ResetPasswordRequest,
    Token,
    TwoFactorConfirmRequest,
    TwoFactorDisableRequest,
    TwoFactorSetupResponse,
    TwoFactorVerifyRequest,
)

from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    Request,
    Response,
    status,
    Body,
)
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.enums.enums import NotificationType
from app.models.models import User, LoginAlert
from app.schemas.user_schemas import UserCreate, UserInfoResponse
from app.services.auth_service import (
    AccountLockedError,
    AuthService,
    InvalidCredentialsError,
    TokenBlacklistedError,
    TokenExpiredError,
    TwoFactorAuthService,
    TwoFactorRequiredError,
    UserAlreadyExistsError,
    UserNotFoundError,
    WeakPasswordError,
    get_client_info,
    get_current_user,
    require_admin,
)

from app.services.login_alert_service import LoginAlertService
from app.services.email_service import EmailService
from app.services.notification_service import NotificationService
from app.core.config import settings
from app.core.config import RESEND_API_KEY, FROM_EMAIL


# ========================================
# CONFIGURACIÓN
# ========================================

router = APIRouter(prefix="/auth", tags=["authentication"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
logger = logging.getLogger(__name__)


# ========================================
# HELPERS DE COOKIES
# ========================================

ACCESS_TOKEN_PATH = "/"
REFRESH_TOKEN_PATH = "/auth"

ACCESS_TOKEN_MAX_AGE = 60 * 60 * 24
REFRESH_TOKEN_MAX_AGE = 60 * 60 * 24 * 7


def _set_auth_cookies(
    response: Response, access_token: str, refresh_token: str
) -> None:
    """
    Establece las cookies HttpOnly de acceso y de refresco.

    Los atributos `secure`, `samesite` y `domain` se obtienen de `settings`,
    garantizando que el comportamiento sea el adecuado tanto en entornos de
    desarrollo (HTTP) como en producción (HTTPS).

    Args:
        response: Respuesta sobre la cual se escribirán las cookies.
        access_token: Token JWT de acceso.
        refresh_token: Token JWT de refresco.
    """
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN,
        max_age=ACCESS_TOKEN_MAX_AGE,
        path=ACCESS_TOKEN_PATH,
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN,
        max_age=REFRESH_TOKEN_MAX_AGE,
        path=REFRESH_TOKEN_PATH,
    )


def _clear_auth_cookies(response: Response) -> None:
    """
    Elimina las cookies de autenticación.

    `delete_cookie` debe recibir los mismos `path`, `domain` y `samesite` con
    los que fue creada la cookie; de lo contrario el navegador no la elimina.

    Args:
        response: Respuesta sobre la cual se eliminarán las cookies.
    """
    response.delete_cookie(
        key="access_token",
        path=ACCESS_TOKEN_PATH,
        domain=settings.COOKIE_DOMAIN,
        samesite=settings.COOKIE_SAMESITE,
        secure=settings.COOKIE_SECURE,
        httponly=True,
    )
    response.delete_cookie(
        key="refresh_token",
        path=REFRESH_TOKEN_PATH,
        domain=settings.COOKIE_DOMAIN,
        samesite=settings.COOKIE_SAMESITE,
        secure=settings.COOKIE_SECURE,
        httponly=True,
    )


# ========================================
# ENDPOINTS DE AUTENTICACIÓN BÁSICA
# ========================================

@router.post("/login", summary="Iniciar sesión")
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    request: Request = None,
    db: Session = Depends(get_db),
):
    """
    Autentica al usuario con correo y contraseña, y establece las cookies
    HttpOnly correspondientes. Si la cuenta tiene habilitada la verificación
    en dos pasos, retorna `requires_2fa: true` sin emitir tokens.

    Args:
        form_data: Formulario OAuth2 con `username` (correo) y `password`.
        request: Solicitud HTTP entrante, utilizada para auditar IP y agente.
        db: Sesión de base de datos.

    Returns:
        JSONResponse con los tokens de acceso y refresco, o la indicación de
        que se requiere verificación en dos pasos.

    Raises:
        HTTPException 401: Credenciales inválidas.
        HTTPException 423: Cuenta bloqueada por intentos fallidos.
        HTTPException 500: Error interno durante el procesamiento.
    """
    try:
        ip_address, user_agent = (
            get_client_info(request) if request else ("unknown", "unknown")
        )

        result = AuthService.login_user(
            form_data.username,
            form_data.password,
            db,
            ip_address,
            user_agent,
        )

        if isinstance(result, dict) and result.get("requires_2fa"):
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "requires_2fa": True,
                    "message": "Verificación de dos factores requerida",
                },
            )

        access_token, refresh_token = result

        json_response = JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
            },
        )
        _set_auth_cookies(json_response, access_token, refresh_token)
        return json_response

    except InvalidCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas",
        )
    except AccountLockedError:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Cuenta bloqueada",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unexpected error during login: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno del servidor durante el login",
        )


@router.post(
    "/signup",
    status_code=status.HTTP_201_CREATED,
    summary="Registrar nuevo usuario",
)
def signup(
    user_data: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Crea una nueva cuenta de usuario y establece las cookies de autenticación.

    La contraseña debe cumplir los requisitos de seguridad definidos por
    `AuthService`: longitud mínima, mayúsculas, minúsculas, dígitos y
    caracteres especiales.

    Args:
        user_data: Datos de creación del usuario.
        request: Solicitud HTTP entrante.
        db: Sesión de base de datos.

    Returns:
        JSONResponse con los tokens de acceso y refresco.

    Raises:
        HTTPException 400: Contraseña que no cumple los requisitos.
        HTTPException 409: Correo ya registrado.
        HTTPException 500: Error interno durante el procesamiento.
    """
    try:
        ip_address, _ = get_client_info(request)
        access_token, refresh_token = AuthService.signup_user(
            user_data, db, ip_address
        )

        try:
            user = (
                db.query(User)
                .filter(User.email == user_data.email.lower())
                .first()
            )
            if user:
                email_service = EmailService(
                    api_key=RESEND_API_KEY, from_email=FROM_EMAIL
                )
                notification_service = NotificationService(email_service)
                notification_service.send_notification(
                    db=db,
                    user_id=user.id,
                    event_type=NotificationType.WELCOME,
                    data={},
                )
        except Exception as exc:
            logger.warning("Failed to send welcome notification: %s", exc)

        json_response = JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
            },
        )
        _set_auth_cookies(json_response, access_token, refresh_token)
        return json_response

    except UserAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        )
    except WeakPasswordError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unexpected error during signup: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno del servidor durante el registro",
        )


@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    summary="Cerrar sesión",
)
def logout(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Cierra la sesión del usuario.

    - Blacklistea el refresh_token si está presente y es válido.
    - SIEMPRE limpia las cookies, incluso si el access_token ya expiró
      o si no hay sesión activa.
    - Es idempotente: llamarlo sin sesión devuelve 200 igual.
    """
    try:
        refresh_token = request.cookies.get("refresh_token")
        if refresh_token:
            try:
                AuthService.logout_user(refresh_token, db)
            except (TokenExpiredError, TokenBlacklistedError):
                logger.info("Logout con refresh ya invalidado")
            except Exception as exc:
                # Nunca bloquear el logout por un error de blacklist
                logger.warning(
                    "Error blacklisteando refresh en logout: %s", exc
                )

        json_response = JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"message": "Sesión cerrada correctamente"},
        )
        _clear_auth_cookies(json_response)
        return json_response

    except Exception as exc:
        logger.exception("Unexpected error during logout: %s", exc)
        # Incluso si algo falla, intentamos limpiar cookies
        err_response = JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"message": "Sesión cerrada con advertencias"},
        )
        _clear_auth_cookies(err_response)
        return err_response

@router.post("/refresh", summary="Renovar tokens")
def refresh_token(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Renueva los tokens de acceso y de refresco a partir de una cookie de
    refresco válida. El token de refresco anterior se invalida.

    Args:
        request: Solicitud HTTP entrante.
        db: Sesión de base de datos.

    Returns:
        JSONResponse con los nuevos tokens de acceso y refresco.

    Raises:
        HTTPException 401: Token ausente, expirado o en lista negra.
        HTTPException 404: Usuario no encontrado.
        HTTPException 500: Error interno durante el procesamiento.
    """
    try:
        refresh_token_cookie = request.cookies.get("refresh_token")
        if not refresh_token_cookie:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token ausente",
            )

        access_token, new_refresh_token = AuthService.refresh_tokens(
            refresh_token_cookie, db
        )

        json_response = JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "access_token": access_token,
                "refresh_token": new_refresh_token,
                "token_type": "bearer",
            },
        )
        _set_auth_cookies(json_response, access_token, new_refresh_token)
        return json_response

    except (TokenExpiredError, TokenBlacklistedError) as exc:
        err_response = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": str(exc)},
        )
        _clear_auth_cookies(err_response)
        return err_response

    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unexpected error during token refresh: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Error interno del servidor durante la renovación de tokens"
            ),
        )


# ========================================
# ENDPOINTS DE AUTENTICACIÓN CON 2FA
# ========================================

@router.post("/login-with-2fa", summary="Login con 2FA")
def login_with_2fa(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    totp_code: str = Form(...),
    db: Session = Depends(get_db),
):
    """
    Inicia sesión con credenciales y un código TOTP o código de respaldo.

    Args:
        request: Solicitud HTTP entrante.
        form_data: Formulario OAuth2 con `username` y `password`.
        totp_code: Código TOTP de seis dígitos o código de respaldo.
        db: Sesión de base de datos.

    Returns:
        JSONResponse con los tokens de acceso y refresco.

    Raises:
        HTTPException 401: Credenciales o código inválidos.
        HTTPException 500: Error interno durante el procesamiento.
    """
    try:
        user = (
            db.query(User)
            .filter(User.email == form_data.username)
            .first()
        )
        if not user or not verify_password(
            form_data.password, user.password_hash
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Credenciales inválidas",
            )

        if not TwoFactorAuthService.verify_totp_code(
            user.two_factor_secret, totp_code
        ):
            if not TwoFactorAuthService.verify_backup_code(
                user, totp_code, db
            ):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Código inválido",
                )

        token_data = {
            "sub": str(user.id),
            "role": user.role.name,
            "email": user.email,
        }
        access_token = security_service.create_access_token(token_data)
        refresh_token = security_service.create_refresh_token(token_data)

        ip_address, user_agent = (
            get_client_info(request) if request else ("unknown", "unknown")
        )
        from app.services.session_service import SessionService

        SessionService.create_session(
            user_id=user.id,
            access_token=access_token,
            refresh_token=refresh_token,
            ip_address=ip_address,
            user_agent=user_agent,
            db=db,
            is_current=True,
        )

        AuthService.update_last_login(user, db)

        try:
            email_service = EmailService(
                api_key=RESEND_API_KEY, from_email=FROM_EMAIL
            )
            notification_service = NotificationService(email_service)
            alert_service = LoginAlertService(notification_service)
            alert_service.record_login_and_check(user, request, db)
        except Exception as alert_error:
            logger.warning(
                "Failed to record login alert: %s", alert_error
            )

        logger.info("Successful login (2FA) for user: %s", user.email)

        json_response = JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
            },
        )
        _set_auth_cookies(json_response, access_token, refresh_token)
        return json_response

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error during login with 2FA: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al procesar inicio de sesión",
        )


# ========================================
# ENDPOINTS DE ALERTAS DE LOGIN
# ========================================

@router.get("/login-alerts/recent")
def get_recent_login_alerts(
    days: int = 30,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Retorna las alertas de inicio de sesión recientes del usuario autenticado,
    incluyendo dispositivos desconocidos, ubicaciones nuevas o actividad
    potencialmente sospechosa.

    Args:
        days: Número de días hacia atrás a consultar. Por defecto 30.
        current_user: Usuario autenticado.
        db: Sesión de base de datos.

    Returns:
        Diccionario con el total de alertas y la lista detallada.

    Raises:
        HTTPException 500: Error interno durante el procesamiento.
    """
    try:
        alerts = LoginAlertService.get_recent_login_alerts(
            user=current_user,
            days=days,
            db=db,
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
                    "created_at": alert.created_at.isoformat(),
                }
                for alert in alerts
            ],
        }
    except Exception as exc:
        logger.exception(
            "Error getting login alerts for user %s: %s",
            current_user.id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener alertas de login",
        )


@router.delete("/login-alerts/{alert_id}")
def dismiss_login_alert(
    alert_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Descarta una alerta de inicio de sesión perteneciente al usuario
    autenticado.

    Args:
        alert_id: Identificador de la alerta a descartar.
        current_user: Usuario autenticado.
        db: Sesión de base de datos.

    Returns:
        Diccionario confirmando la eliminación de la alerta.

    Raises:
        HTTPException 404: Alerta no encontrada o no perteneciente al usuario.
        HTTPException 500: Error interno durante el procesamiento.
    """
    try:
        alert = (
            db.query(LoginAlert)
            .filter(
                LoginAlert.id == alert_id,
                LoginAlert.user_id == current_user.id,
            )
            .first()
        )

        if not alert:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Alerta no encontrada",
            )

        db.delete(alert)
        db.commit()
        return {"message": "Alerta descartada exitosamente"}

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "Error dismissing login alert %s: %s", alert_id, exc
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al descartar alerta",
        )