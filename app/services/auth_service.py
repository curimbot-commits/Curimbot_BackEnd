import base64
from io import BytesIO
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple, Dict, Any
from contextlib import contextmanager
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
import pyotp
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from jose import JWTError, jwt
import qrcode
import secrets

from app.core.security import (
    AccountLockedError,
    ActiveSessionInfo,
    ActiveSessionsResponse,
    InvalidCredentialsError,
    PermissionDeniedError,
    RefreshTokenRequest,
    ResetPasswordConfirm,
    ResetPasswordRequest,
    RevokeSessionRequest,
    Token,
    TokenBlacklistedError,
    TokenExpiredError,
    TrustedDeviceRequest,
    TwoFactorSetupRequest,
    TwoFactorVerifyRequest,
    UserAlreadyExistsError,
    UserNotFoundError,
    WeakPasswordError,
)

from app.db.database import get_db
from app.models.models import Log, Role, User, BlacklistedToken, LoginAttempt
from app.enums.enums import LogAction
from app.schemas.user_schemas import UserCreate
from app.services import security_service
from app.services.session_service import SessionService


# ========================================
# CONFIGURACIÓN INICIAL
# ========================================

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
logger = logging.getLogger(__name__)


# ========================================
# SERVICIO DE AUTENTICACIÓN
# ========================================

class AuthService:
    """
    Servicio completo de autenticación y gestión de usuarios.

    Proporciona funcionalidades para:
    - Registro y login de usuarios
    - Gestión de tokens y sesiones
    - Control de seguridad y auditoría
    - Administración de usuarios
    """

    # Configuración de seguridad
    MAX_LOGIN_ATTEMPTS = 5
    LOCKOUT_DURATION = timedelta(minutes=15)
    TOKEN_BLACKLIST_CLEANUP_HOURS = 24
    PASSWORD_MIN_LENGTH = 8

    @staticmethod
    @contextmanager
    def db_transaction(db: Session):
        """Context manager para transacciones con rollback automático."""
        try:
            yield db
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"Database transaction failed: {e}")
            raise

    @staticmethod
    def _validate_password_strength(password: str) -> None:
        """
        Valida que la contraseña cumpla con los requisitos de seguridad.

        Raises:
            WeakPasswordError: Si la contraseña no cumple los requisitos.
        """
        if len(password) < AuthService.PASSWORD_MIN_LENGTH:
            raise WeakPasswordError(
                f"La contraseña debe tener al menos {AuthService.PASSWORD_MIN_LENGTH} caracteres"
            )
        if not any(c.isupper() for c in password):
            raise WeakPasswordError("La contraseña debe contener al menos una letra mayúscula")
        if not any(c.islower() for c in password):
            raise WeakPasswordError("La contraseña debe contener al menos una letra minúscula")
        if not any(c.isdigit() for c in password):
            raise WeakPasswordError("La contraseña debe contener al menos un número")
        special_chars = "!@#$%^&*()_+-=[]{}|;:,.<>?"
        if not any(c in special_chars for c in password):
            raise WeakPasswordError("La contraseña debe contener al menos un carácter especial")

    @staticmethod
    def _check_account_lockout(email: str, db: Session) -> None:
        """
        Verifica si la cuenta está bloqueada por demasiados intentos fallidos.

        Raises:
            AccountLockedError: Si la cuenta está bloqueada.
        """
        cutoff_time = datetime.now(timezone.utc) - AuthService.LOCKOUT_DURATION
        failed_attempts = (
            db.query(LoginAttempt)
            .filter(
                LoginAttempt.email == email,
                LoginAttempt.success == False,
                LoginAttempt.attempted_at > cutoff_time
            )
            .count()
        )
        if failed_attempts >= AuthService.MAX_LOGIN_ATTEMPTS:
            remaining_lockout = AuthService.LOCKOUT_DURATION - (datetime.now(timezone.utc) - cutoff_time)
            raise AccountLockedError(
                f"Cuenta bloqueada por demasiados intentos fallidos. "
                f"Intente nuevamente en {remaining_lockout.seconds // 60} minutos."
            )

    @staticmethod
    def _log_login_attempt(
        email: str,
        success: bool,
        ip_address: str = None,
        user_agent: str = None,
        db: Session = None
    ) -> None:
        """Registra intento de login para auditoría de seguridad."""
        try:
            if db:
                attempt = LoginAttempt(
                    email=email,
                    success=success,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    attempted_at=datetime.now(timezone.utc)
                )
                db.add(attempt)
                db.commit()
        except Exception as e:
            logger.warning(f"Failed to log login attempt: {e}")

    @staticmethod
    def _cleanup_expired_tokens(db: Session) -> None:
        """Limpia tokens en lista negra expirados."""
        try:
            cutoff_time = datetime.now(timezone.utc)
            expired_tokens = db.query(BlacklistedToken).filter(
                BlacklistedToken.expires_at < cutoff_time
            )
            count = expired_tokens.count()
            if count > 0:
                expired_tokens.delete()
                db.commit()
        except Exception as e:
            logger.warning(f"Failed to cleanup expired tokens: {e}")

    @staticmethod
    def decode_and_validate_token(token: str, db: Session) -> Dict[str, Any]:
        """
        Decodifica y valida un token JWT.

        Args:
            token: Token JWT a validar.
            db: Sesión de base de datos.

        Returns:
            Dict[str, Any]: Payload del token decodificado.

        Raises:
            TokenBlacklistedError: Si el token está en lista negra.
            TokenExpiredError: Si el token es inválido o expirado.
        """
        try:
            payload = security_service.decode_token(token)
            jti = payload.get("jti")
            
            # Verificar si el token está en lista negra
            if AuthService.is_token_blacklisted(jti, db):
                raise TokenBlacklistedError("Token ha sido revocado")
            
            # Verificar expiración por inactividad de la sesión
            from app.models.auth_models import ActiveSession
            from app.core.config import settings
            
            session = db.query(ActiveSession).filter(
                (ActiveSession.access_token_jti == jti) | (ActiveSession.refresh_token_jti == jti)
            ).first()
            
            if session:
                # Asegurar que last_active tenga información de zona horaria si la base de datos devuelve naive
                last_active = session.last_active
                if last_active.tzinfo is None:
                    last_active = last_active.replace(tzinfo=timezone.utc)
                
                # Si la sesión no está activa o expiró por inactividad
                inactivity_limit = datetime.now(timezone.utc) - timedelta(minutes=settings.SESSION_INACTIVITY_TIMEOUT_MINUTES)
                
                if not session.is_active or last_active < inactivity_limit:
                    # Si expiró por inactividad, marcar como inactiva en BD si aún no lo está
                    if session.is_active:
                        session.is_active = False
                        db.commit()
                    raise TokenExpiredError("Sesión expirada por inactividad")
                
                # Actualizar actividad si es token de acceso
                if payload.get("type") == "access":
                    SessionService.update_session_activity(jti, db)
            
            return payload

        except JWTError as e:
            logger.warning(f"Invalid token: {e}")
            raise TokenExpiredError("Token inválido o expirado")
        except TokenBlacklistedError:
            raise

    @staticmethod
    def logout_user(refresh_token: str, db: Session) -> bool:
        """
        Añade el refresh token a la lista negra para invalidarlo.

        Args:
            refresh_token: El token de refresco a invalidar.
            db: Sesión de base de datos.

        Returns:
            True si el token fue añadido correctamente a la blacklist.
        """
        try:
            payload = jwt.decode(
                refresh_token,
                security_service.SECRET_KEY,
                algorithms=[security_service.ALGORITHM]
            )
            jti = payload.get("jti")
            exp = payload.get("exp")
            
            if not jti or not exp:
                raise ValueError("Payload no contiene jti o exp")

            blacklisted_token = BlacklistedToken(
                jti=jti,
                expires_at=datetime.fromtimestamp(exp, timezone.utc),
                blacklisted_at=datetime.now(timezone.utc)
            )
            db.add(blacklisted_token)

            # También marcar la sesión activa como inactiva
            from app.models.auth_models import ActiveSession
            db.query(ActiveSession).filter(
                ActiveSession.refresh_token_jti == jti
            ).update({"is_active": False})

            db.commit()
            return True
        except JWTError:
            return False
        except Exception as e:
            logger.error(f"Error during logout (blacklisting token): {e}")
            db.rollback()
            return False

    @staticmethod
    def _record_failed_attempt(user: User, ip_address: str, user_agent: str, db: Session) -> None:
        """Registra un intento fallido de login y bloquea la cuenta si es necesario."""
        try:
            user.failed_attempts += 1
            if user.failed_attempts >= AuthService.MAX_LOGIN_ATTEMPTS:
                user.locked_until = datetime.now(timezone.utc) + AuthService.LOCKOUT_DURATION
                logger.warning(
                    f"Account locked for user {user.email} until {user.locked_until} "
                    f"due to {user.failed_attempts} failed attempts"
                )
            AuthService._log_login_attempt(
                email=user.email,
                success=False,
                ip_address=ip_address,
                user_agent=user_agent,
                db=db
            )
            db.commit()
        except Exception as e:
            logger.error(f"Error recording failed attempt for {user.email}: {e}")
            db.rollback()

    @staticmethod
    def login_user(email: str, password: str, db: Session, ip_address: str, user_agent: str):
        """Autenticar usuario y generar tokens."""
        user = db.query(User).filter(User.email == email).first()
        if not user:
            raise InvalidCredentialsError("Credenciales inválidas")

        if user.locked_until and user.locked_until > datetime.now(timezone.utc):
            remaining_time = user.locked_until - datetime.now(timezone.utc)
            minutes_remaining = int(remaining_time.total_seconds() / 60)
            raise AccountLockedError(
                f"Cuenta bloqueada temporalmente. Intente nuevamente en {minutes_remaining} minutos."
            )

        if user.locked_until and user.locked_until <= datetime.now(timezone.utc):
            user.failed_attempts = 0
            user.locked_until = None
            db.commit()

        if not security_service.verify_password(password, user.password_hash):
            AuthService._record_failed_attempt(user, ip_address, user_agent, db)
            raise InvalidCredentialsError("Credenciales inválidas")

        if not user.is_active:
            raise AccountLockedError("Cuenta desactivada")

        if user.two_factor_enabled:
            return {
                "requires_2fa": True,
                "message": "Verificación de dos factores requerida"
            }

        user.failed_attempts = 0
        user.locked_until = None

        token_data = {
            "sub": str(user.id),
            "role": user.role.name if hasattr(user.role, 'name') else str(user.role),
            "email": user.email
        }

        access_token = security_service.create_access_token(token_data)
        refresh_token = security_service.create_refresh_token(token_data)

        # Crear sesión activa en la base de datos
        SessionService.create_session(
            user_id=user.id,
            access_token=access_token,
            refresh_token=refresh_token,
            ip_address=ip_address,
            user_agent=user_agent,
            db=db,
            is_current=True
        )

        user.last_login = datetime.now(timezone.utc)
        db.commit()

        AuthService._log_login_attempt(
            email=user.email,
            success=True,
            ip_address=ip_address,
            user_agent=user_agent,
            db=db
        )

        return access_token, refresh_token

    @staticmethod
    def update_last_login(user: User, db: Session) -> None:
        """Actualiza la fecha y hora del último login del usuario."""
        try:
            user.last_login = datetime.now(timezone.utc)
            db.add(user)
            db.commit()
        except Exception as e:
            logger.warning(f"Failed to update last login for user {user.email}: {e}")
            db.rollback()


# ========================================
# MÉTODOS PRINCIPALES DE USUARIO
# ========================================

    @staticmethod
    def signup_user(
        user_data: UserCreate,
        db: Session,
        ip_address: str = None
    ) -> Tuple[str, str]:
        """
        Registra un nuevo usuario con validación completa.

        Args:
            user_data: Datos del usuario a registrar.
            db: Sesión de base de datos.
            ip_address: Dirección IP del cliente.

        Returns:
            Tuple[str, str]: Token de acceso y token de refresh.

        Raises:
            UserAlreadyExistsError: Si el usuario ya existe.
            WeakPasswordError: Si la contraseña es débil.
        """
        try:
            AuthService._validate_password_strength(user_data.password)

            if user_data.password != user_data.password_confirm:
                raise WeakPasswordError("Las contraseñas no coinciden")

            existing_user = db.query(User).filter(User.email == user_data.email.lower()).first()
            if existing_user:
                raise UserAlreadyExistsError("Ya existe un usuario con este email")

            with AuthService.db_transaction(db):
                admin_role = db.query(Role).filter(Role.name == "admin").first()
                user_role = db.query(Role).filter(Role.name == "user").first()
                if not admin_role:
                    admin_role = Role(name="admin", description="Administrator role")
                    db.add(admin_role)
                    db.flush()
                if not user_role:
                    user_role = Role(name="user", description="Regular user role")
                    db.add(user_role)
                    db.flush()
                is_first_user = db.query(User).count() == 0

                hashed_password = security_service.hash_password(user_data.password)
                new_user = User(
                    name=user_data.name.strip(),
                    email=user_data.email.lower().strip(),
                    password_hash=hashed_password,
                    role_id=admin_role.id if is_first_user else user_role.id,
                    created_at=datetime.now(timezone.utc),
                    is_active=True
                )

                db.add(new_user)
                db.flush()

                access_token = security_service.create_access_token({
                    "sub": str(new_user.id),
                    "role": new_user.role.name,
                    "email": new_user.email
                })
                refresh_token = security_service.create_refresh_token({
                    "sub": str(new_user.id),
                    "role": new_user.role.name
                })

                # Crear sesión activa para el nuevo usuario
                SessionService.create_session(
                    user_id=new_user.id,
                    access_token=access_token,
                    refresh_token=refresh_token,
                    ip_address=ip_address or "unknown",
                    user_agent="unknown",  # signup_user no recibe user_agent actualmente
                    db=db,
                    is_current=True
                )

                AuthService._log_login_attempt(
                    new_user.email, True, ip_address, db=db
                )

                return access_token, refresh_token

        except (UserAlreadyExistsError, WeakPasswordError):
            raise
        except IntegrityError as e:
            logger.error(f"Database integrity error during signup: {e}")
            raise UserAlreadyExistsError("Error al crear el usuario - email ya existe")
        except SQLAlchemyError as e:
            logger.error(f"Database error during signup: {e}")
            raise HTTPException(
                status_code=500,
                detail="Error interno del servidor durante el registro"
            )
        except Exception as e:
            logger.exception(f"Unexpected error during signup: {e}")
            raise HTTPException(
                status_code=500,
                detail="Error interno del servidor"
            )

    @staticmethod
    def refresh_tokens(refresh_token: str, db: Session) -> Tuple[str, str]:
        """
        Renueva tokens de acceso y refresh.

        Args:
            refresh_token: Token de refresh actual.
            db: Sesión de base de datos.

        Returns:
            Tuple[str, str]: Nuevo token de acceso y refresh.

        Raises:
            TokenExpiredError: Si el token está expirado.
            TokenBlacklistedError: Si el token está en lista negra.
        """
        try:
            try:
                payload = jwt.decode(
                    refresh_token,
                    security_service.SECRET_KEY,
                    algorithms=[security_service.ALGORITHM]
                )
            except JWTError as e:
                logger.warning(f"Invalid refresh token: {e}")
                raise TokenExpiredError("Refresh token inválido o expirado")

            if AuthService.is_token_blacklisted(payload.get("jti"), db):
                raise TokenBlacklistedError("Refresh token ha sido revocado")

            user_id = payload.get("sub")
            if not user_id:
                raise TokenExpiredError("Token inválido")

            user = db.query(User).filter(User.id == user_id).first()
            if not user or not user.is_active:
                raise UserNotFoundError("Usuario no encontrado o desactivado")

            token_data = {
                "sub": str(user.id),
                "role": user.role.value,
                "email": user.email
            }

            new_access_token = security_service.create_access_token(token_data)
            new_refresh_token = security_service.create_refresh_token(token_data)

            with AuthService.db_transaction(db):
                blacklisted_token = BlacklistedToken(
                    jti=payload.get("jti"),
                    expires_at=datetime.fromtimestamp(payload.get("exp"), timezone.utc),
                    blacklisted_at=datetime.now(timezone.utc)
                )
                db.add(blacklisted_token)

                # Actualizar los JTIs en la sesión activa correspondiente
                from app.models.auth_models import ActiveSession
                from app.services.session_service import SessionService
                
                new_access_jti = SessionService.extract_jti_from_token(new_access_token)
                new_refresh_jti = SessionService.extract_jti_from_token(new_refresh_token)
                
                db.query(ActiveSession).filter(
                    ActiveSession.refresh_token_jti == payload.get("jti")
                ).update({
                    "access_token_jti": new_access_jti,
                    "refresh_token_jti": new_refresh_jti,
                    "last_active": datetime.now(timezone.utc)
                })

            return new_access_token, new_refresh_token

        except (TokenExpiredError, TokenBlacklistedError, UserNotFoundError):
            raise
        except SQLAlchemyError as e:
            logger.error(f"Database error during token refresh: {e}")
            raise HTTPException(
                status_code=500,
                detail="Error interno del servidor durante la renovación de tokens"
            )
        except Exception as e:
            logger.exception(f"Unexpected error during token refresh: {e}")
            raise HTTPException(
                status_code=500,
                detail="Error interno del servidor"
            )


# ========================================
# MÉTODOS DE SEGURIDAD
# ========================================

    @staticmethod
    def change_password(
        user: User,
        old_password: str,
        new_password: str,
        db: Session
    ) -> None:
        """
        Cambia la contraseña del usuario con validación.

        Args:
            user: Usuario actual.
            old_password: Contraseña actual.
            new_password: Nueva contraseña.
            db: Sesión de base de datos.

        Raises:
            InvalidCredentialsError: Si la contraseña actual es incorrecta.
            WeakPasswordError: Si la nueva contraseña es débil.
        """
        try:
            if not security_service.verify_password(old_password, user.password_hash):
                raise InvalidCredentialsError("Contraseña actual incorrecta")

            AuthService._validate_password_strength(new_password)

            if security_service.verify_password(new_password, user.password_hash):
                raise WeakPasswordError("La nueva contraseña debe ser diferente a la actual")

            with AuthService.db_transaction(db):
                user.password_hash = security_service.hash_password(new_password)
                user.password_changed_at = datetime.now(timezone.utc)

        except (InvalidCredentialsError, WeakPasswordError):
            raise
        except SQLAlchemyError as e:
            logger.error(f"Database error during password change: {e}")
            raise HTTPException(
                status_code=500,
                detail="Error interno del servidor durante el cambio de contraseña"
            )
        except Exception as e:
            logger.exception(f"Unexpected error during password change: {e}")
            raise HTTPException(
                status_code=500,
                detail="Error interno del servidor"
            )

    @staticmethod
    def is_token_blacklisted(jti: str, db: Session) -> bool:
        """Verifica si un token (por su JTI) está en lista negra."""
        if not jti:
            return False
        try:
            return db.query(BlacklistedToken).filter(
                BlacklistedToken.jti == jti
            ).first() is not None
        except SQLAlchemyError as e:
            logger.error(f"Database error checking blacklisted token: {e}")
            return False

    @staticmethod
    def get_user_from_token(token: str, db: Session) -> User:
        """
        Obtiene usuario desde un token válido.

        Args:
            token: Token JWT.
            db: Sesión de base de datos.

        Returns:
            User: Usuario autenticado.

        Raises:
            TokenExpiredError: Si el token es inválido.
            UserNotFoundError: Si el usuario no existe o está inactivo.
        """
        try:
            payload = AuthService.decode_and_validate_token(token, db)

            user_id = payload.get("sub")
            if not user_id:
                raise TokenExpiredError("Token inválido")

            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise UserNotFoundError("Usuario no encontrado")

            if not user.is_active:
                raise UserNotFoundError("Usuario desactivado")

            return user

        except (TokenExpiredError, TokenBlacklistedError, UserNotFoundError):
            raise
        except Exception as e:
            logger.exception(f"Unexpected error getting user from token: {e}")
            raise HTTPException(
                status_code=500,
                detail="Error interno del servidor"
            )


# ========================================
# MÉTODOS DE ADMINISTRACIÓN
# ========================================

    @staticmethod
    def update_user_role(
        admin_user: User,
        target_user_id: int,
        new_role_name: str,
        db: Session
    ) -> User:
        """
        Actualiza el rol de usuario con validación de permisos.

        Args:
            admin_user: Usuario administrador que realiza la acción.
            target_user_id: ID del usuario objetivo.
            new_role_name: Nuevo rol a asignar.
            db: Sesión de base de datos.

        Returns:
            User: Usuario actualizado.

        Raises:
            PermissionDeniedError: Si no tiene permisos de administrador.
            UserNotFoundError: Si el usuario objetivo no existe.
        """
        try:
            if admin_user.role.name != "admin":
                raise PermissionDeniedError("Se requieren permisos de administrador")

            target_user = db.query(User).filter(User.id == target_user_id).first()
            if not target_user:
                raise UserNotFoundError("Usuario objetivo no encontrado")

            if admin_user.id == target_user_id and new_role_name != "admin":
                raise PermissionDeniedError("No puede modificar su propio rol de administrador")

            new_role = db.query(Role).filter(Role.name == new_role_name).first()
            if not new_role:
                raise HTTPException(status_code=400, detail="Rol inválido")

            with AuthService.db_transaction(db):
                target_user.role_id = new_role.id

            db.refresh(target_user)
            return target_user

        except (PermissionDeniedError, UserNotFoundError):
            raise
        except SQLAlchemyError as e:
            logger.error(f"Database error during role update: {e}")
            raise HTTPException(
                status_code=500,
                detail="Error interno del servidor durante la actualización de rol"
            )

    @staticmethod
    def deactivate_user(admin_user: User, target_user_id: int, db: Session) -> User:
        """
        Desactiva cuenta de usuario.

        Args:
            admin_user: Usuario administrador que realiza la acción.
            target_user_id: ID del usuario a desactivar.
            db: Sesión de base de datos.

        Returns:
            User: Usuario desactivado.

        Raises:
            PermissionDeniedError: Si no tiene permisos de administrador.
            UserNotFoundError: Si el usuario no existe.
        """
        try:
            if admin_user.role.name != "admin":
                raise PermissionDeniedError("Se requieren permisos de administrador")

            target_user = db.query(User).filter(User.id == target_user_id).first()
            if not target_user:
                raise UserNotFoundError("Usuario no encontrado")

            if admin_user.id == target_user_id:
                raise PermissionDeniedError("No puede desactivar su propia cuenta")

            with AuthService.db_transaction(db):
                target_user.is_active = False
                target_user.deactivated_at = datetime.now(timezone.utc)
                target_user.deactivated_by = admin_user.id

            return target_user

        except (PermissionDeniedError, UserNotFoundError):
            raise
        except Exception as e:
            logger.exception(f"Error deactivating user: {e}")
            raise HTTPException(status_code=500, detail="Error interno del servidor")

    @staticmethod
    def activate_user(admin_user: User, target_user_id: int, db: Session) -> User:
        """
        Reactiva la cuenta de un usuario previamente desactivado.

        Args:
            admin_user: Usuario administrador que realiza la acción.
            target_user_id: ID del usuario a reactivar.
            db: Sesión de base de datos.

        Returns:
            User: Usuario reactivado.

        Raises:
            PermissionDeniedError: Si no tiene permisos de administrador.
            UserNotFoundError: Si el usuario no existe.
        """
        try:
            if admin_user.role.name != "admin":
                raise PermissionDeniedError("Se requieren permisos de administrador")

            target_user = db.query(User).filter(User.id == target_user_id).first()
            if not target_user:
                raise UserNotFoundError("Usuario no encontrado")

            with AuthService.db_transaction(db):
                target_user.is_active = True
                target_user.activated_at = datetime.now(timezone.utc)
                target_user.activated_by = admin_user.id
                
            return target_user

        except (PermissionDeniedError, UserNotFoundError):
            raise
        except Exception as e:
            logger.exception(f"Error activating user: {e}")
            raise HTTPException(status_code=500, detail="Error interno del servidor")


# ========================================
# MÉTODOS DE MONITOREO Y AUDITORÍA
# ========================================

    @staticmethod
    def get_login_attempts_stats(
        email: str,
        db: Session,
        hours: int = 24
    ) -> Dict[str, Any]:
        """
        Obtiene estadísticas de intentos de login para monitoreo.

        Args:
            email: Email del usuario.
            db: Sesión de base de datos.
            hours: Período de tiempo en horas.

        Returns:
            Dict[str, Any]: Estadísticas de intentos de login.
        """
        try:
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

            attempts = db.query(LoginAttempt).filter(
                LoginAttempt.email == email,
                LoginAttempt.attempted_at > cutoff_time
            ).all()

            total_attempts = len(attempts)
            successful_attempts = len([a for a in attempts if a.success])
            failed_attempts = total_attempts - successful_attempts

            return {
                "email": email,
                "period_hours": hours,
                "total_attempts": total_attempts,
                "successful_attempts": successful_attempts,
                "failed_attempts": failed_attempts,
                "success_rate": (successful_attempts / total_attempts * 100) if total_attempts > 0 else 0,
                "last_attempt": max([a.attempted_at for a in attempts]) if attempts else None
            }

        except Exception as e:
            logger.error(f"Error getting login stats for {email}: {e}")
            return {"error": "Could not retrieve stats"}


# ========================================
# DEPENDENCIAS DE SEGURIDAD
# ========================================

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    """
    Dependencia para obtener usuario autenticado desde token.

    Raises:
        HTTPException 401: Si hay error de autenticación.
    """
    try:
        user = AuthService.get_user_from_token(token, db)
        return user
    except TokenExpiredError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expirado o inválido",
            headers={"WWW-Authenticate": "Bearer"}
        )
    except TokenBlacklistedError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token revocado",
            headers={"WWW-Authenticate": "Bearer"}
        )
    except UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado o desactivado",
            headers={"WWW-Authenticate": "Bearer"}
        )
    except Exception as e:
        logger.exception(f"Unexpected error in get_current_user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno del servidor"
        )


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """
    Dependencia que requiere rol de administrador.

    Raises:
        HTTPException 403: Si no tiene permisos de administrador.
    """
    if current_user.role.name != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requieren permisos de administrador"
        )
    return current_user


def get_client_info(request: Request) -> tuple[str, str]:
    """
    Extrae información del cliente desde la request.

    Returns:
        tuple[str, str]: Dirección IP y User-Agent.
    """
    ip_address = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    return ip_address, user_agent


# ========================================
# SERVICIO DE AUTENTICACIÓN 2FA
# ========================================

class TwoFactorAuthService:
    """Servicio para manejar autenticación de dos factores."""

    @staticmethod
    def generate_secret() -> str:
        """Genera un secreto aleatorio para TOTP."""
        return pyotp.random_base32()

    @staticmethod
    def generate_qr_code(user_email: str, secret: str, issuer_name: str = "SecureDocApp") -> str:
        """
        Genera un código QR para configurar 2FA en Google Authenticator.

        Args:
            user_email: Email del usuario.
            secret: Secreto TOTP.
            issuer_name: Nombre de la aplicación.

        Returns:
            String base64 de la imagen QR.
        """
        totp_uri = pyotp.totp.TOTP(secret).provisioning_uri(
            name=user_email,
            issuer_name=issuer_name
        )

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(totp_uri)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")

        buffer = BytesIO()
        img.save(buffer, format="PNG")
        img_str = base64.b64encode(buffer.getvalue()).decode()

        return img_str

    @staticmethod
    def verify_totp_code(secret: str, code: str, window: int = 1) -> bool:
        """
        Verifica un código TOTP.

        Args:
            secret: Secreto TOTP del usuario.
            code: Código ingresado por el usuario.
            window: Ventana de tiempo para validación.

        Returns:
            True si el código es válido.
        """
        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=window)

    @staticmethod
    def enable_2fa_for_user(user: 'User', db: 'Session') -> Tuple[str, str]:
        """
        Habilita 2FA para un usuario.

        Returns:
            Tupla (secret, qr_code_base64).
        """
        secret = TwoFactorAuthService.generate_secret()

        user.two_factor_secret_temp = secret
        user.two_factor_enabled = False
        db.commit()

        qr_code = TwoFactorAuthService.generate_qr_code(user.email, secret)

        return secret, qr_code

    @staticmethod
    def confirm_2fa_setup(user: 'User', code: str, db: 'Session') -> bool:
        """
        Confirma la configuración de 2FA verificando el primer código.

        Returns:
            True si la configuración fue exitosa.
        """
        if not user.two_factor_secret_temp:
            raise ValueError("No hay configuración de 2FA pendiente")

        if TwoFactorAuthService.verify_totp_code(user.two_factor_secret_temp, code):
            user.two_factor_secret = user.two_factor_secret_temp
            user.two_factor_secret_temp = None
            user.two_factor_enabled = True
            user.two_factor_enabled_at = datetime.now(timezone.utc)

            log = Log(
                user_id=user.id,
                action=LogAction.ENABLE_2FA,
                detail="Activación de autenticación en dos pasos"
            )
            db.add(log)
            db.commit()
            return True

        return False

    @staticmethod
    def disable_2fa_for_user(user: 'User', code: str, db: 'Session') -> bool:
        """
        Deshabilita 2FA para un usuario (requiere código válido).

        Returns:
            True si se deshabilitó exitosamente.
        """
        if not user.two_factor_enabled or not user.two_factor_secret:
            raise ValueError("2FA no está habilitado")

        if TwoFactorAuthService.verify_totp_code(user.two_factor_secret, code):
            user.two_factor_enabled = False
            user.two_factor_secret = None
            user.two_factor_disabled_at = datetime.now(timezone.utc)
            db.commit()
            return True

        return False

    @staticmethod
    def generate_backup_codes(count: int = 8) -> List[str]:
        """
        Genera códigos de respaldo para 2FA.

        Args:
            count: Número de códigos a generar.

        Returns:
            Lista de códigos de respaldo.
        """
        return [secrets.token_hex(4).upper() for _ in range(count)]

    @staticmethod
    def save_backup_codes(user: 'User', codes: List[str], db: 'Session'):
        """Guarda códigos de respaldo hasheados."""
        from app.core.security import get_password_hash
        hashed_codes = [get_password_hash(code) for code in codes]
        user.backup_codes = ",".join(hashed_codes)
        db.commit()

    @staticmethod
    def verify_backup_code(user: 'User', code: str, db: 'Session') -> bool:
        """
        Verifica y consume un código de respaldo.

        Returns:
            True si el código es válido.
        """
        from app.core.security import verify_password

        if not user.backup_codes:
            return False

        codes = user.backup_codes.split(",")

        for i, hashed_code in enumerate(codes):
            if verify_password(code, hashed_code):
                codes.pop(i)
                user.backup_codes = ",".join(codes) if codes else None
                db.commit()
                return True

        return False


class TwoFactorRequiredError(Exception):
    """Excepción lanzada cuando se requiere verificación de dos factores."""
    pass