"""
Servicio de autenticación y gestión de usuarios.

Este módulo centraliza la lógica de negocio relacionada con la autenticación
de usuarios: registro, inicio y cierre de sesión, renovación de tokens,
cambio de contraseña, verificación en dos pasos, administración de cuentas
y auditoría de intentos de acceso.

Depende de `security_service` para la generación y validación de tokens JWT
y para el hashing de contraseñas, y de `SessionService` para el registro y
seguimiento de sesiones activas.
"""

from qrcode.image.pil import PilImage
import base64
import logging
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

import pyotp
import qrcode
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.enums.enums import LogAction
from app.models.models import BlacklistedToken, Log, LoginAttempt, Role, User
from app.schemas.auth_schemas import (
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
from app.schemas.user_schemas import UserCreate
from app.services import security_service
from app.services.session_service import SessionService


# ========================================
# CONFIGURACIÓN INICIAL
# ========================================

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
logger = logging.getLogger(__name__)


# ========================================
# EXCEPCIÓN AUXILIAR
# ========================================

class TwoFactorRequiredError(Exception):
    """
    Señala que la cuenta requiere verificación en dos pasos antes de
    emitir los tokens definitivos.
    """
    pass


# ========================================
# SERVICIO DE AUTENTICACIÓN
# ========================================

class AuthService:
    """
    Servicio de autenticación y gestión de usuarios.

    Agrupa las operaciones de negocio relacionadas con las cuentas de
    usuario y la emisión de credenciales. Todos los métodos son estáticos
    para facilitar su uso como utilidades sin necesidad de instanciar la
    clase.
    """

    MAX_LOGIN_ATTEMPTS = 5
    LOCKOUT_DURATION = timedelta(minutes=15)
    TOKEN_BLACKLIST_CLEANUP_HOURS = 24
    PASSWORD_MIN_LENGTH = 8
    BCRYPT_SHA256_PREFIX = "$bcrypt-sha256$v=2,t=2b,r=12$"

    # ========================================
    # UTILIDADES INTERNAS
    # ========================================

    @staticmethod
    @contextmanager
    def db_transaction(db: Session):
        """
        Gestiona una transacción de base de datos con rollback automático.

        Uso:
            with AuthService.db_transaction(db):
                db.add(obj)

        Si el bloque finaliza sin excepciones, se realiza `commit`. En caso
        contrario, se ejecuta `rollback` y se propaga la excepción original.

        Args:
            db: Sesión de SQLAlchemy sobre la que operar.
        """
        try:
            yield db
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.error("Fallo en transacción de base de datos: %s", exc)
            raise

    @staticmethod
    def _get_role_name(user: User) -> str:
        """
        Obtiene el nombre del rol asociado al usuario.

        Devuelve un valor por defecto (`"user"`) si el usuario no tiene un
        rol asignado o si la relación no está cargada, evitando errores
        por acceso a `None` al construir el payload del token.

        Args:
            user: Instancia de usuario.

        Returns:
            Nombre del rol, o `"user"` si no está disponible.
        """
        if user.role and user.role.name:
            return user.role.name
        return "user"

    @staticmethod
    def _validate_password_strength(password: str) -> None:
        """
        Valida que la contraseña cumpla los requisitos de seguridad.

        Requisitos:
            - Longitud mínima de `PASSWORD_MIN_LENGTH` caracteres.
            - Al menos una letra mayúscula.
            - Al menos una letra minúscula.
            - Al menos un dígito.
            - Al menos un carácter especial del conjunto permitido.

        Args:
            password: Contraseña en texto plano.

        Raises:
            WeakPasswordError: Si no cumple alguno de los requisitos.
        """
        if len(password) < AuthService.PASSWORD_MIN_LENGTH:
            raise WeakPasswordError(
                f"La contraseña debe tener al menos "
                f"{AuthService.PASSWORD_MIN_LENGTH} caracteres"
            )
        if not any(c.isupper() for c in password):
            raise WeakPasswordError(
                "La contraseña debe contener al menos una letra mayúscula"
            )
        if not any(c.islower() for c in password):
            raise WeakPasswordError(
                "La contraseña debe contener al menos una letra minúscula"
            )
        if not any(c.isdigit() for c in password):
            raise WeakPasswordError(
                "La contraseña debe contener al menos un número"
            )
        special_chars = "!@#$%^&*()_+-=[]{}|;:,.<>?"
        if not any(c in special_chars for c in password):
            raise WeakPasswordError(
                "La contraseña debe contener al menos un carácter especial"
            )

    @staticmethod
    def _log_login_attempt(
        email: str,
        success: bool,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> None:
        """
        Registra un intento de acceso para auditoría de seguridad.

        Args:
            email: Correo del usuario involucrado.
            success: Resultado del intento.
            ip_address: Dirección IP del cliente.
            user_agent: Identificador del agente de usuario.
            db: Sesión de base de datos. Si no se proporciona, no se
                persiste el intento.
        """
        try:
            if db:
                attempt = LoginAttempt(
                    email=email,
                    success=success,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    attempted_at=datetime.now(timezone.utc),
                )
                db.add(attempt)
                db.commit()
        except Exception as exc:
            logger.warning("No se pudo registrar intento de login: %s", exc)

    @staticmethod
    def _cleanup_expired_tokens(db: Session) -> None:
        """
        Elimina los tokens en lista negra cuya expiración ya ha ocurrido.

        Args:
            db: Sesión de base de datos.
        """
        try:
            now = datetime.now(timezone.utc)
            query = db.query(BlacklistedToken).filter(
                BlacklistedToken.expires_at < now
            )
            if query.count() > 0:
                query.delete()
                db.commit()
        except Exception as exc:
            logger.warning("No se pudo limpiar tokens expirados: %s", exc)

    @staticmethod
    def _record_failed_attempt(
        user: User,
        ip_address: str,
        user_agent: str,
        db: Session,
    ) -> None:
        """
        Registra un intento fallido de acceso y aplica bloqueo temporal si
        se alcanza el umbral configurado.

        Args:
            user: Usuario afectado.
            ip_address: Dirección IP del cliente.
            user_agent: Identificador del agente de usuario.
            db: Sesión de base de datos.
        """
        try:
            user.failed_attempts += 1
            if user.failed_attempts >= AuthService.MAX_LOGIN_ATTEMPTS:
                user.locked_until = (
                    datetime.now(timezone.utc) + AuthService.LOCKOUT_DURATION
                )
                logger.warning(
                    "Cuenta bloqueada para %s hasta %s tras %s intentos",
                    user.email,
                    user.locked_until,
                    user.failed_attempts,
                )
            AuthService._log_login_attempt(
                email=user.email,
                success=False,
                ip_address=ip_address,
                user_agent=user_agent,
                db=db,
            )
            db.commit()
        except Exception as exc:
            logger.error(
                "Error al registrar intento fallido para %s: %s",
                user.email,
                exc,
            )
            db.rollback()

    # ========================================
    # TOKENS Y SESIONES
    # ========================================

    @staticmethod
    def decode_and_validate_token(token: str, db: Session) -> Dict[str, Any]:
        """
        Decodifica un token JWT y valida su vigencia y estado.

        Comprueba:
            - Firma y expiración del token.
            - Presencia del identificador único (`jti`) en la lista negra.
            - Estado de la sesión asociada (activa, no expirada por
              inactividad).

        Args:
            token: Token JWT codificado.
            db: Sesión de base de datos.

        Returns:
            Diccionario con el payload del token.

        Raises:
            TokenBlacklistedError: Si el token fue revocado.
            TokenExpiredError: Si el token es inválido o expiró.
        """
        try:
            payload = security_service.decode_token(token)

            # Solo los access tokens autentican peticiones; un refresh token
            # (30 días) no debe servir como credencial de acceso.
            if payload.get("type") != "access":
                raise TokenExpiredError("Tipo de token inválido")

            jti = payload.get("jti")

            if AuthService.is_token_blacklisted(jti, db):
                raise TokenBlacklistedError("Token ha sido revocado")

            from app.core.config import settings
            from app.models.auth_models import ActiveSession

            session = (
                db.query(ActiveSession)
                .filter(
                    (ActiveSession.access_token_jti == jti)
                    | (ActiveSession.refresh_token_jti == jti)
                )
                .first()
            )

            if session:
                last_active = session.last_active
                if last_active.tzinfo is None:
                    last_active = last_active.replace(tzinfo=timezone.utc)

                inactivity_limit = datetime.now(timezone.utc) - timedelta(
                    minutes=settings.SESSION_INACTIVITY_TIMEOUT_MINUTES
                )

                if not session.is_active or last_active < inactivity_limit:
                    if session.is_active:
                        session.is_active = False
                        db.commit()
                    raise TokenExpiredError(
                        "Sesión expirada por inactividad"
                    )

                if payload.get("type") == "access":
                    SessionService.update_session_activity(jti, db)

            return payload

        except JWTError as exc:
            logger.warning("Token inválido: %s", exc)
            raise TokenExpiredError("Token inválido o expirado")
        except HTTPException:
            # security_service.decode_token señala firma inválida o expiración
            # con HTTPException 401; se traduce para que llegue como 401 y no
            # como 500 a través de get_user_from_token.
            raise TokenExpiredError("Token inválido o expirado")
        except TokenBlacklistedError:
            raise

    @staticmethod
    def is_token_blacklisted(jti: str, db: Session) -> bool:
        """
        Comprueba si un `jti` figura en la lista negra.

        Args:
            jti: Identificador único del token.
            db: Sesión de base de datos.

        Returns:
            `True` si el token está revocado, `False` en caso contrario.
        """
        if not jti:
            return False
        try:
            return (
                db.query(BlacklistedToken)
                .filter(BlacklistedToken.jti == jti)
                .first()
                is not None
            )
        except SQLAlchemyError as exc:
            logger.error("Error al consultar lista negra de tokens: %s", exc)
            return False

    @staticmethod
    def get_user_from_token(token: str, db: Session) -> User:
        """
        Recupera el usuario asociado a un token válido.

        Args:
            token: Token JWT codificado.
            db: Sesión de base de datos.

        Returns:
            Instancia del usuario autenticado.

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
        except Exception as exc:
            logger.exception(
                "Error inesperado al obtener usuario desde token: %s", exc
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error interno del servidor",
            )

    # ========================================
    # LOGIN Y LOGOUT
    # ========================================

    @staticmethod
    def _ensure_not_locked(user: User, db: Session) -> None:
        """
        Lanza `AccountLockedError` si la cuenta está bloqueada temporalmente.
        Si el bloqueo ya expiró, reinicia el contador de intentos fallidos.

        MySQL devuelve `locked_until` sin zona horaria; se interpreta como UTC.
        """
        if not user.locked_until:
            return

        locked_until = user.locked_until
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        if locked_until > now:
            remaining = locked_until - now
            raise AccountLockedError(
                f"Cuenta bloqueada temporalmente. Intente nuevamente en "
                f"{int(remaining.total_seconds() / 60)} minutos."
            )

        user.failed_attempts = 0
        user.locked_until = None
        db.commit()

    @staticmethod
    def authenticate_with_2fa(
        email: str,
        password: str,
        code: str,
        db: Session,
        ip_address: str,
        user_agent: str,
    ) -> User:
        """
        Valida credenciales y segundo factor aplicando las mismas reglas que
        `login_user`: bloqueo temporal, cuenta activa y registro de intentos
        fallidos (tanto por contraseña como por código TOTP/respaldo).

        Returns:
            Usuario autenticado, con el contador de intentos reiniciado.

        Raises:
            InvalidCredentialsError: Credenciales o código inválidos.
            AccountLockedError: Cuenta bloqueada o desactivada.
        """
        user = db.query(User).filter(User.email == email).first()
        if not user:
            raise InvalidCredentialsError("Credenciales inválidas")

        AuthService._ensure_not_locked(user, db)

        if not security_service.verify_password(password, user.password_hash):
            AuthService._record_failed_attempt(user, ip_address, user_agent, db)
            raise InvalidCredentialsError("Credenciales inválidas")

        if not user.is_active:
            raise AccountLockedError("Cuenta desactivada")

        if not user.two_factor_enabled or not user.two_factor_secret:
            raise InvalidCredentialsError("Código inválido")

        code_ok = TwoFactorAuthService.verify_totp_code(
            user.two_factor_secret, code
        ) or TwoFactorAuthService.verify_backup_code(user, code, db)
        if not code_ok:
            AuthService._record_failed_attempt(user, ip_address, user_agent, db)
            raise InvalidCredentialsError("Código inválido")

        user.failed_attempts = 0
        user.locked_until = None
        db.commit()
        AuthService._log_login_attempt(
            email=user.email,
            success=True,
            ip_address=ip_address,
            user_agent=user_agent,
            db=db,
        )
        return user

    @staticmethod
    def login_user(
        email: str,
        password: str,
        db: Session,
        ip_address: str,
        user_agent: str,
    ):
        """
        Autentica un usuario y emite los tokens correspondientes.

        Flujo:
            1. Localiza al usuario por correo.
            2. Verifica si la cuenta está bloqueada temporalmente.
            3. Valida la contraseña.
            4. Migra el formato del hash si procede.
            5. Comprueba el estado de la cuenta.
            6. Si 2FA está habilitado, señala que se requiere verificación.
            7. Genera tokens y registra la sesión activa.

        Args:
            email: Correo del usuario.
            password: Contraseña en texto plano.
            db: Sesión de base de datos.
            ip_address: Dirección IP del cliente.
            user_agent: Identificador del agente de usuario.

        Returns:
            Tupla `(access_token, refresh_token)` o un diccionario con
            `{"requires_2fa": True, ...}` si la cuenta tiene 2FA activo.

        Raises:
            InvalidCredentialsError: Si las credenciales no son válidas.
            AccountLockedError: Si la cuenta está bloqueada o desactivada.
        """
        user = db.query(User).filter(User.email == email).first()
        if not user:
            raise InvalidCredentialsError("Credenciales inválidas")

        AuthService._ensure_not_locked(user, db)

        if not security_service.verify_password(password, user.password_hash):
            AuthService._record_failed_attempt(
                user, ip_address, user_agent, db
            )
            raise InvalidCredentialsError("Credenciales inválidas")

        # Migración transparente de hashes generados por esquemas previos.
        if not user.password_hash.startswith(AuthService.BCRYPT_SHA256_PREFIX):
            try:
                user.password_hash = security_service.hash_password(password)
                db.commit()
                logger.info(
                    "Hash de contraseña migrado a formato actual para %s",
                    user.email,
                )
            except Exception as exc:
                logger.warning(
                    "No se pudo migrar el hash de contraseña de %s: %s",
                    user.email,
                    exc,
                )
                db.rollback()

        if not user.is_active:
            raise AccountLockedError("Cuenta desactivada")

        if user.two_factor_enabled:
            return {
                "requires_2fa": True,
                "message": "Verificación de dos factores requerida",
            }

        user.failed_attempts = 0
        user.locked_until = None

        token_data = {
            "sub": str(user.id),
            "role": AuthService._get_role_name(user),
            "email": user.email,
        }

        access_token = security_service.create_access_token(token_data)
        refresh_token = security_service.create_refresh_token(token_data)

        SessionService.create_session(
            user_id=user.id,
            access_token=access_token,
            refresh_token=refresh_token,
            ip_address=ip_address,
            user_agent=user_agent,
            db=db,
            is_current=True,
        )

        user.last_login = datetime.now(timezone.utc)
        db.commit()

        AuthService._log_login_attempt(
            email=user.email,
            success=True,
            ip_address=ip_address,
            user_agent=user_agent,
            db=db,
        )

        return access_token, refresh_token

    @staticmethod
    def logout_user(refresh_token: str, db: Session) -> bool:
        """
        Invalida el token de refresco y desactiva la sesión asociada.

        Añade el `jti` del token a la lista negra y marca la sesión
        correspondiente como inactiva.

        Args:
            refresh_token: Token de refresco a invalidar.
            db: Sesión de base de datos.

        Returns:
            `True` si el token fue invalidado correctamente, `False` en
            caso contrario.
        """
        try:
            payload = jwt.decode(
                refresh_token,
                security_service.SECRET_KEY,
                algorithms=[security_service.ALGORITHM],
            )
            jti = payload.get("jti")
            exp = payload.get("exp")

            if not jti or not exp:
                raise ValueError("Payload sin jti o exp")

            db.add(
                BlacklistedToken(
                    jti=jti,
                    expires_at=datetime.fromtimestamp(exp, timezone.utc),
                    blacklisted_at=datetime.now(timezone.utc),
                )
            )

            from app.models.auth_models import ActiveSession

            db.query(ActiveSession).filter(
                ActiveSession.refresh_token_jti == jti
            ).update({"is_active": False})

            db.commit()
            return True
        except JWTError:
            return False
        except Exception as exc:
            logger.error("Error durante el cierre de sesión: %s", exc)
            db.rollback()
            return False

    @staticmethod
    def update_last_login(user: User, db: Session) -> None:
        """
        Actualiza la marca temporal del último acceso del usuario.

        Args:
            user: Usuario a actualizar.
            db: Sesión de base de datos.
        """
        try:
            user.last_login = datetime.now(timezone.utc)
            db.add(user)
            db.commit()
        except Exception as exc:
            logger.warning(
                "No se pudo actualizar el último acceso de %s: %s",
                user.email,
                exc,
            )
            db.rollback()

    # ========================================
    # REGISTRO Y RENOVACIÓN
    # ========================================

    @staticmethod
    def signup_user(
        user_data: UserCreate,
        db: Session,
        ip_address: Optional[str] = None,
    ) -> Tuple[str, str]:
        """
        Registra una nueva cuenta de usuario.

        El primer usuario registrado en el sistema recibe el rol de
        administrador; los siguientes reciben el rol de usuario estándar.

        Args:
            user_data: Datos de creación del usuario.
            db: Sesión de base de datos.
            ip_address: Dirección IP del cliente.

        Returns:
            Tupla `(access_token, refresh_token)`.

        Raises:
            UserAlreadyExistsError: Si el correo ya está registrado.
            WeakPasswordError: Si la contraseña no cumple los requisitos.
        """
        try:
            AuthService._validate_password_strength(user_data.password)

            if user_data.password != user_data.password_confirm:
                raise WeakPasswordError("Las contraseñas no coinciden")

            existing_user = (
                db.query(User)
                .filter(User.email == user_data.email.lower())
                .first()
            )
            if existing_user:
                raise UserAlreadyExistsError(
                    "Ya existe un usuario con este correo"
                )

            with AuthService.db_transaction(db):
                admin_role = (
                    db.query(Role).filter(Role.name == "admin").first()
                )
                user_role = (
                    db.query(Role).filter(Role.name == "user").first()
                )
                if not admin_role:
                    admin_role = Role(
                        name="admin", description="Administrator role"
                    )
                    db.add(admin_role)
                    db.flush()
                if not user_role:
                    user_role = Role(
                        name="user", description="Regular user role"
                    )
                    db.add(user_role)
                    db.flush()

                is_first_user = db.query(User).count() == 0
                hashed_password = security_service.hash_password(
                    user_data.password
                )

                new_user = User(
                    name=user_data.name.strip(),
                    email=user_data.email.lower().strip(),
                    password_hash=hashed_password,
                    role_id=admin_role.id if is_first_user else user_role.id,
                    created_at=datetime.now(timezone.utc),
                    is_active=True,
                )
                db.add(new_user)
                db.flush()

                token_data = {
                    "sub": str(new_user.id),
                    "role": AuthService._get_role_name(new_user),
                    "email": new_user.email,
                }

                access_token = security_service.create_access_token(
                    token_data
                )
                refresh_token = security_service.create_refresh_token(
                    token_data
                )

                SessionService.create_session(
                    user_id=new_user.id,
                    access_token=access_token,
                    refresh_token=refresh_token,
                    ip_address=ip_address or "unknown",
                    user_agent="unknown",
                    db=db,
                    is_current=True,
                )

                AuthService._log_login_attempt(
                    new_user.email, True, ip_address, db=db
                )

                return access_token, refresh_token

        except (UserAlreadyExistsError, WeakPasswordError):
            raise
        except IntegrityError as exc:
            logger.error(
                "Error de integridad durante el registro: %s", exc
            )
            raise UserAlreadyExistsError(
                "Error al crear el usuario - correo ya registrado"
            )
        except SQLAlchemyError as exc:
            logger.error("Error de base de datos durante el registro: %s", exc)
            raise HTTPException(
                status_code=500,
                detail="Error interno del servidor durante el registro",
            )
        except Exception as exc:
            logger.exception(
                "Error inesperado durante el registro: %s", exc
            )
            raise HTTPException(
                status_code=500,
                detail="Error interno del servidor",
            )

    @staticmethod
    def refresh_tokens(refresh_token: str, db: Session) -> Tuple[str, str]:
        """
        Renueva los tokens de acceso y de refresco.

        El token de refresco utilizado se añade a la lista negra y la
        sesión activa se actualiza con los nuevos identificadores.

        Args:
            refresh_token: Token de refresco actual.
            db: Sesión de base de datos.

        Returns:
            Tupla `(nuevo_access_token, nuevo_refresh_token)`.

        Raises:
            TokenExpiredError: Si el token está expirado o es inválido.
            TokenBlacklistedError: Si el token fue revocado.
            UserNotFoundError: Si el usuario no existe o está desactivado.
        """
        try:
            try:
                payload = jwt.decode(
                    refresh_token,
                    security_service.SECRET_KEY,
                    algorithms=[security_service.ALGORITHM],
                )
            except JWTError as exc:
                logger.warning("Token de refresco inválido: %s", exc)
                raise TokenExpiredError(
                    "Refresh token inválido o expirado"
                )

            if AuthService.is_token_blacklisted(payload.get("jti"), db):
                raise TokenBlacklistedError(
                    "Refresh token ha sido revocado"
                )

            user_id = payload.get("sub")
            if not user_id:
                raise TokenExpiredError("Token inválido")

            user = db.query(User).filter(User.id == user_id).first()
            if not user or not user.is_active:
                raise UserNotFoundError(
                    "Usuario no encontrado o desactivado"
                )

            token_data = {
                "sub": str(user.id),
                "role": AuthService._get_role_name(user),
                "email": user.email,
            }

            new_access_token = security_service.create_access_token(
                token_data
            )
            new_refresh_token = security_service.create_refresh_token(
                token_data
            )

            with AuthService.db_transaction(db):
                db.add(
                    BlacklistedToken(
                        jti=payload.get("jti"),
                        expires_at=datetime.fromtimestamp(
                            payload.get("exp"), timezone.utc
                        ),
                        blacklisted_at=datetime.now(timezone.utc),
                    )
                )

                from app.models.auth_models import ActiveSession

                new_access_jti = SessionService.extract_jti_from_token(
                    new_access_token
                )
                new_refresh_jti = SessionService.extract_jti_from_token(
                    new_refresh_token
                )

                db.query(ActiveSession).filter(
                    ActiveSession.refresh_token_jti == payload.get("jti")
                ).update(
                    {
                        "access_token_jti": new_access_jti,
                        "refresh_token_jti": new_refresh_jti,
                        "last_active": datetime.now(timezone.utc),
                    }
                )

            return new_access_token, new_refresh_token

        except (TokenExpiredError, TokenBlacklistedError, UserNotFoundError):
            raise
        except SQLAlchemyError as exc:
            logger.error(
                "Error de base de datos durante la renovación de tokens: %s",
                exc,
            )
            raise HTTPException(
                status_code=500,
                detail=(
                    "Error interno del servidor durante la renovación "
                    "de tokens"
                ),
            )
        except Exception as exc:
            logger.exception(
                "Error inesperado durante la renovación de tokens: %s", exc
            )
            raise HTTPException(
                status_code=500,
                detail="Error interno del servidor",
            )

    # ========================================
    # GESTIÓN DE CONTRASEÑA
    # ========================================

    @staticmethod
    def change_password(
        user: User,
        old_password: str,
        new_password: str,
        db: Session,
    ) -> None:
        """
        Cambia la contraseña de un usuario autenticado.

        Args:
            user: Usuario cuya contraseña se va a cambiar.
            old_password: Contraseña actual en texto plano.
            new_password: Nueva contraseña en texto plano.
            db: Sesión de base de datos.

        Raises:
            InvalidCredentialsError: Si la contraseña actual es incorrecta.
            WeakPasswordError: Si la nueva contraseña no cumple los
                requisitos o coincide con la anterior.
        """
        try:
            if not security_service.verify_password(
                old_password, user.password_hash
            ):
                raise InvalidCredentialsError(
                    "Contraseña actual incorrecta"
                )

            AuthService._validate_password_strength(new_password)

            if security_service.verify_password(
                new_password, user.password_hash
            ):
                raise WeakPasswordError(
                    "La nueva contraseña debe ser distinta a la actual"
                )

            with AuthService.db_transaction(db):
                user.password_hash = security_service.hash_password(
                    new_password
                )
                user.password_changed_at = datetime.now(timezone.utc)

        except (InvalidCredentialsError, WeakPasswordError):
            raise
        except SQLAlchemyError as exc:
            logger.error(
                "Error de base de datos al cambiar contraseña: %s", exc
            )
            raise HTTPException(
                status_code=500,
                detail=(
                    "Error interno del servidor durante el cambio de "
                    "contraseña"
                ),
            )
        except Exception as exc:
            logger.exception(
                "Error inesperado al cambiar contraseña: %s", exc
            )
            raise HTTPException(
                status_code=500,
                detail="Error interno del servidor",
            )

    # ========================================
    # ADMINISTRACIÓN DE USUARIOS
    # ========================================

    @staticmethod
    def update_user_role(
        admin_user: User,
        target_user_id: int,
        new_role_name: str,
        db: Session,
    ) -> User:
        """
        Actualiza el rol de un usuario.

        Args:
            admin_user: Usuario que realiza la operación (debe ser admin).
            target_user_id: Identificador del usuario objetivo.
            new_role_name: Nombre del nuevo rol.
            db: Sesión de base de datos.

        Returns:
            Usuario actualizado.

        Raises:
            PermissionDeniedError: Si el solicitante no es administrador o
                intenta modificar su propio rol.
            UserNotFoundError: Si el usuario objetivo no existe.
        """
        try:
            if admin_user.role.name != "admin":
                raise PermissionDeniedError(
                    "Se requieren permisos de administrador"
                )

            target_user = (
                db.query(User).filter(User.id == target_user_id).first()
            )
            if not target_user:
                raise UserNotFoundError("Usuario objetivo no encontrado")

            if admin_user.id == target_user_id and new_role_name != "admin":
                raise PermissionDeniedError(
                    "No puede modificar su propio rol de administrador"
                )

            new_role = (
                db.query(Role).filter(Role.name == new_role_name).first()
            )
            if not new_role:
                raise HTTPException(status_code=400, detail="Rol inválido")

            with AuthService.db_transaction(db):
                target_user.role_id = new_role.id

            db.refresh(target_user)
            return target_user

        except (PermissionDeniedError, UserNotFoundError):
            raise
        except SQLAlchemyError as exc:
            logger.error(
                "Error de base de datos al actualizar rol: %s", exc
            )
            raise HTTPException(
                status_code=500,
                detail=(
                    "Error interno del servidor durante la actualización "
                    "de rol"
                ),
            )

    @staticmethod
    def deactivate_user(
        admin_user: User, target_user_id: int, db: Session
    ) -> User:
        """
        Desactiva la cuenta de un usuario.

        Args:
            admin_user: Usuario que realiza la operación (debe ser admin).
            target_user_id: Identificador del usuario objetivo.
            db: Sesión de base de datos.

        Returns:
            Usuario desactivado.

        Raises:
            PermissionDeniedError: Si el solicitante no es administrador o
                intenta desactivar su propia cuenta.
            UserNotFoundError: Si el usuario objetivo no existe.
        """
        try:
            if admin_user.role.name != "admin":
                raise PermissionDeniedError(
                    "Se requieren permisos de administrador"
                )

            target_user = (
                db.query(User).filter(User.id == target_user_id).first()
            )
            if not target_user:
                raise UserNotFoundError("Usuario no encontrado")

            if admin_user.id == target_user_id:
                raise PermissionDeniedError(
                    "No puede desactivar su propia cuenta"
                )

            with AuthService.db_transaction(db):
                target_user.is_active = False
                target_user.deactivated_at = datetime.now(timezone.utc)
                target_user.deactivated_by = admin_user.id

            return target_user

        except (PermissionDeniedError, UserNotFoundError):
            raise
        except Exception as exc:
            logger.exception("Error al desactivar usuario: %s", exc)
            raise HTTPException(
                status_code=500, detail="Error interno del servidor"
            )

    @staticmethod
    def activate_user(
        admin_user: User, target_user_id: int, db: Session
    ) -> User:
        """
        Reactiva una cuenta previamente desactivada.

        Args:
            admin_user: Usuario que realiza la operación (debe ser admin).
            target_user_id: Identificador del usuario objetivo.
            db: Sesión de base de datos.

        Returns:
            Usuario reactivado.

        Raises:
            PermissionDeniedError: Si el solicitante no es administrador.
            UserNotFoundError: Si el usuario objetivo no existe.
        """
        try:
            if admin_user.role.name != "admin":
                raise PermissionDeniedError(
                    "Se requieren permisos de administrador"
                )

            target_user = (
                db.query(User).filter(User.id == target_user_id).first()
            )
            if not target_user:
                raise UserNotFoundError("Usuario no encontrado")

            with AuthService.db_transaction(db):
                target_user.is_active = True
                target_user.activated_at = datetime.now(timezone.utc)
                target_user.activated_by = admin_user.id

            return target_user

        except (PermissionDeniedError, UserNotFoundError):
            raise
        except Exception as exc:
            logger.exception("Error al activar usuario: %s", exc)
            raise HTTPException(
                status_code=500, detail="Error interno del servidor"
            )

    @staticmethod
    def delete_user(
        admin_user: User, target_user_id: int, db: Session
    ) -> bool:
        """
        Elimina permanentemente una cuenta de usuario.

        Args:
            admin_user: Usuario que realiza la operación (debe ser admin).
            target_user_id: Identificador del usuario objetivo.
            db: Sesión de base de datos.

        Returns:
            `True` si la eliminación fue exitosa.

        Raises:
            PermissionDeniedError: Si el solicitante no es administrador o
                intenta eliminarse a sí mismo.
            UserNotFoundError: Si el usuario objetivo no existe.
        """
        try:
            if admin_user.role.name != "admin":
                raise PermissionDeniedError(
                    "Se requieren permisos de administrador"
                )

            target_user = (
                db.query(User).filter(User.id == target_user_id).first()
            )
            if not target_user:
                raise UserNotFoundError("Usuario no encontrado")

            if admin_user.id == target_user_id:
                raise PermissionDeniedError(
                    "No puede eliminarse a sí mismo"
                )

            with AuthService.db_transaction(db):
                db.delete(target_user)

            logger.info(
                "Usuario %s eliminado por el administrador %s",
                target_user.email,
                admin_user.email,
            )
            return True

        except (PermissionDeniedError, UserNotFoundError):
            raise
        except Exception as exc:
            logger.exception("Error al eliminar usuario: %s", exc)
            raise HTTPException(
                status_code=500, detail="Error interno del servidor"
            )

    # ========================================
    # MONITOREO Y AUDITORÍA
    # ========================================

    @staticmethod
    def get_login_attempts_stats(
        email: str, db: Session, hours: int = 24
    ) -> Dict[str, Any]:
        """
        Recupera estadísticas de intentos de acceso para un correo dado.

        Args:
            email: Correo del usuario.
            db: Sesión de base de datos.
            hours: Ventana temporal en horas a considerar.

        Returns:
            Diccionario con el total de intentos, exitosos, fallidos,
            tasa de éxito y fecha del último intento.
        """
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            attempts = (
                db.query(LoginAttempt)
                .filter(
                    LoginAttempt.email == email,
                    LoginAttempt.attempted_at > cutoff,
                )
                .all()
            )

            total = len(attempts)
            successful = len([a for a in attempts if a.success])
            failed = total - successful

            return {
                "email": email,
                "period_hours": hours,
                "total_attempts": total,
                "successful_attempts": successful,
                "failed_attempts": failed,
                "success_rate": (
                    (successful / total * 100) if total > 0 else 0
                ),
                "last_attempt": (
                    max(a.attempted_at for a in attempts)
                    if attempts
                    else None
                ),
            }

        except Exception as exc:
            logger.error(
                "Error al obtener estadísticas de acceso para %s: %s",
                email,
                exc,
            )
            return {"error": "No se pudieron recuperar las estadísticas"}


# ========================================
# DEPENDENCIAS DE SEGURIDAD
# ========================================

def get_current_user(
    request: Request, db: Session = Depends(get_db)
) -> User:
    """
    Dependencia que resuelve el usuario autenticado a partir de la
    solicitud entrante.

    Acepta el token en la cookie `access_token` o en la cabecera
    `Authorization: Bearer <token>`.

    Args:
        request: Solicitud HTTP entrante.
        db: Sesión de base de datos inyectada por FastAPI.

    Returns:
        Usuario autenticado.

    Raises:
        HTTPException 401: Si la autenticación falla.
    """
    try:
        token = request.cookies.get("access_token")
        if not token:
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.split(" ", 1)[1]

        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="No autenticado",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return AuthService.get_user_from_token(token, db)

    except TokenExpiredError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expirado o inválido",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except TokenBlacklistedError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token revocado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado o desactivado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "Error inesperado en get_current_user: %s", exc
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno del servidor",
        )


def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Dependencia que exige que el usuario autenticado tenga rol de
    administrador.

    Args:
        current_user: Usuario resuelto por `get_current_user`.

    Returns:
        El mismo usuario si tiene rol de administrador.

    Raises:
        HTTPException 403: Si el usuario no es administrador.
    """
    if current_user.role.name != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requieren permisos de administrador",
        )
    return current_user


def get_client_info(request: Request) -> Tuple[str, str]:
    """
    Extrae la dirección IP y el agente de usuario de la solicitud.

    Args:
        request: Solicitud HTTP entrante.

    Returns:
        Tupla `(ip_address, user_agent)`.
    """
    ip_address = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    return ip_address, user_agent


# ========================================
# SERVICIO DE AUTENTICACIÓN 2FA
# ========================================

class TwoFactorAuthService:
    """
    Servicio para la gestión de autenticación en dos pasos basada en
    TOTP (Time-based One-Time Password).
    """

    @staticmethod
    def generate_secret() -> str:
        """
        Genera un secreto aleatorio en formato Base32 apto para TOTP.

        Returns:
            Cadena Base32 con el secreto generado.
        """
        return pyotp.random_base32()

    @staticmethod
    def generate_qr_code(
        user_email: str,
        secret: str,
        issuer_name: str = "SecureDocApp",
    ) -> str:
        """
        Genera un código QR codificado en Base64 para configurar la
        aplicación autenticadora del usuario.

        Args:
            user_email: Correo del usuario.
            secret: Secreto TOTP asociado.
            issuer_name: Nombre del emisor mostrado en la aplicación.

        Returns:
            Cadena Base64 con la imagen PNG del código QR.
        """
        totp_uri = pyotp.totp.TOTP(secret).provisioning_uri(
            name=user_email, issuer_name=issuer_name
        )

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
            image_factory=PilImage,
        )
        qr.add_data(totp_uri)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")

        buffer = BytesIO()
        img.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode()

    @staticmethod
    def verify_totp_code(
        secret: str, code: str, window: int = 1
    ) -> bool:
        """
        Verifica un código TOTP contra el secreto proporcionado.

        Args:
            secret: Secreto TOTP del usuario.
            code: Código introducido por el usuario.
            window: Ventana de tiempo permitida, en número de periodos.

        Returns:
            `True` si el código es válido.
        """
        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=window)

    @staticmethod
    def enable_2fa_for_user(user: User, db: Session) -> Tuple[str, str]:
        """
        Inicia el proceso de habilitación de 2FA para un usuario.

        Genera un secreto temporal y devuelve el código QR para que el
        usuario lo escanee. La habilitación definitiva se confirma con
        `confirm_2fa_setup`.

        Args:
            user: Usuario al que se le habilita 2FA.
            db: Sesión de base de datos.

        Returns:
            Tupla `(secret, qr_code_base64)`.
        """
        secret = TwoFactorAuthService.generate_secret()
        user.two_factor_secret_temp = secret
        user.two_factor_enabled = False
        db.commit()

        qr_code = TwoFactorAuthService.generate_qr_code(
            user.email, secret
        )
        return secret, qr_code

    @staticmethod
    def confirm_2fa_setup(
        user: User, code: str, db: Session
    ) -> bool:
        """
        Confirma la habilitación de 2FA verificando el primer código.

        Args:
            user: Usuario que completa el flujo de configuración.
            code: Código TOTP generado por la aplicación autenticadora.
            db: Sesión de base de datos.

        Returns:
            `True` si la configuración quedó habilitada.

        Raises:
            ValueError: Si no existe una configuración pendiente.
        """
        if not user.two_factor_secret_temp:
            raise ValueError("No hay configuración de 2FA pendiente")

        if TwoFactorAuthService.verify_totp_code(
            user.two_factor_secret_temp, code
        ):
            user.two_factor_secret = user.two_factor_secret_temp
            user.two_factor_secret_temp = None
            user.two_factor_enabled = True
            user.two_factor_enabled_at = datetime.now(timezone.utc)

            db.add(
                Log(
                    user_id=user.id,
                    action=LogAction.ENABLE_2FA,
                    detail="Activación de autenticación en dos pasos",
                )
            )
            db.commit()
            return True

        return False

    @staticmethod
    def disable_2fa_for_user(
        user: User, code: str, db: Session
    ) -> bool:
        """
        Deshabilita 2FA previa verificación de un código válido.

        Args:
            user: Usuario que solicita la deshabilitación.
            code: Código TOTP válido.
            db: Sesión de base de datos.

        Returns:
            `True` si la deshabilitación fue exitosa.

        Raises:
            ValueError: Si 2FA no está habilitado para el usuario.
        """
        if not user.two_factor_enabled or not user.two_factor_secret:
            raise ValueError("2FA no está habilitado")

        if TwoFactorAuthService.verify_totp_code(
            user.two_factor_secret, code
        ):
            user.two_factor_enabled = False
            user.two_factor_secret = None
            user.two_factor_disabled_at = datetime.now(timezone.utc)
            db.commit()
            return True

        return False

    @staticmethod
    def generate_backup_codes(count: int = 8) -> List[str]:
        """
        Genera un conjunto de códigos de respaldo para 2FA.

        Args:
            count: Cantidad de códigos a generar.

        Returns:
            Lista de códigos en hexadecimal mayúscula.
        """
        return [secrets.token_hex(4).upper() for _ in range(count)]

    @staticmethod
    def save_backup_codes(
        user: User, codes: List[str], db: Session
    ) -> None:
        """
        Persiste los códigos de respaldo asociados al usuario.

        Los códigos se almacenan hasheados y separados por comas.

        Args:
            user: Usuario propietario de los códigos.
            codes: Lista de códigos en texto plano.
            db: Sesión de base de datos.
        """
        from app.services.security_service import hash_password

        hashed_codes = [hash_password(code) for code in codes]
        user.backup_codes = ",".join(hashed_codes)
        db.commit()

    @staticmethod
    def verify_backup_code(
        user: User, code: str, db: Session
    ) -> bool:
        """
        Verifica y consume un código de respaldo.

        Si el código es válido, se elimina de la lista para impedir su
        reutilización.

        Args:
            user: Usuario propietario de los códigos.
            code: Código de respaldo en texto plano.
            db: Sesión de base de datos.

        Returns:
            `True` si el código era válido.
        """
        from app.services.security_service import verify_password

        if not user.backup_codes:
            return False

        codes = user.backup_codes.split(",")
        for index, hashed_code in enumerate(codes):
            if verify_password(code, hashed_code):
                codes.pop(index)
                user.backup_codes = ",".join(codes) if codes else None
                db.commit()
                return True

        return False