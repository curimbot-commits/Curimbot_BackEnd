"""
Servicio OAuth para autenticación social con Google y GitHub.

Implementa el patrón Socialite de Laravel pero en FastAPI:
    - Google OAuth2 (OpenID Connect)
    - GitHub OAuth2

Flujo completo:
    1. Usuario hace clic en "Login con Google/GitHub"
    2. Backend redirige al provider
    3. Provider redirige a callback con ?code=
    4. Backend intercambia code por access_token
    5. Backend obtiene perfil del usuario
    6. Busca o crea usuario en MySQL
    7. Genera JWT y redirige a Angular con ?token=

Integración con arquitectura existente:
    - Usa el modelo User y Base de MySQL existentes
    - Usa security_service para generar JWT (mismos tokens que login normal)
    - Usa SessionLocal de database.py
    - Compatible con get_current_user() existente
"""

import logging
import httpx
from datetime import datetime, timezone
from typing import Optional, Tuple, cast, Any
from sqlalchemy.orm import Session

from app.models.models import User, Role
from app.services import security_service

logger = logging.getLogger(__name__)


# =========================================================
# CONFIGURACIÓN DE PROVIDERS
# =========================================================

# URLs de Google OAuth2
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"

# URLs de GitHub OAuth2
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_EMAIL_URL = "https://api.github.com/user/emails"
GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"


# =========================================================
# OAUTH SERVICE
# =========================================================

class OAuthService:
    """
    Servicio centralizado para OAuth con Google y GitHub.

    Equivalente a Laravel Socialite pero para FastAPI + MySQL.

    Métodos principales:
        - get_google_auth_url(): URL para redirigir al login de Google
        - get_github_auth_url(): URL para redirigir al login de GitHub
        - handle_google_callback(): Procesa callback de Google
        - handle_github_callback(): Procesa callback de GitHub

    Cada handle_*_callback() retorna un JWT listo para enviar a Angular.

    Uso en rutas:
        # Redirigir a Google
        url = OAuthService.get_google_auth_url(redirect_uri, state)
        return RedirectResponse(url)

        # Procesar callback
        token = await OAuthService.handle_google_callback(code, redirect_uri, db)
        return RedirectResponse(f"{FRONTEND_URL}/auth/callback?token={token}")
    """

    # -------------------------------------------------------
    # GOOGLE
    # -------------------------------------------------------

    @staticmethod
    def get_google_auth_url(redirect_uri: str, state: str) -> str:
        """
        Construye la URL de autorización de Google.

        Args:
            redirect_uri: URL de callback de tu backend
            state: Token aleatorio para prevenir CSRF

        Returns:
            str: URL completa para redirigir al usuario
        """
        import urllib.parse

        params = {
            "client_id": _get_env("GOOGLE_CLIENT_ID"),
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "offline",
            "prompt": "select_account",  # Fuerza selección de cuenta
        }

        return f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"

    @staticmethod
    async def handle_google_callback(
        code: str,
        redirect_uri: str,
        db: Session
    ) -> Tuple[str, str]:
        """
        Procesa el callback de Google y retorna un JWT.

        Pasos internos:
            1. Intercambia code por access_token con Google
            2. Obtiene perfil del usuario (email, name, picture, sub)
            3. Busca usuario en MySQL por provider_id
            4. Si no existe, lo crea automáticamente
            5. Genera JWT con security_service (mismo que login normal)

        Args:
            code: Código de autorización recibido de Google
            redirect_uri: Debe ser EXACTAMENTE igual al configurado en Google Console
            db: Sesión de MySQL

        Returns:
            str: access_token JWT

        Raises:
            OAuthError: Si falla el intercambio de tokens o la API de Google
        """
        # 1. Obtener access_token de Google
        token_data = await OAuthService._exchange_google_code(code, redirect_uri)
        access_token = token_data.get("access_token")

        if not access_token:
            raise OAuthError("No se pudo obtener access_token de Google")

        # 2. Obtener perfil del usuario
        profile = await OAuthService._get_google_profile(access_token)

        provider_id = profile.get("sub")
        email = profile.get("email")
        name = profile.get("name", email)
        avatar = profile.get("picture")

        if not provider_id or not email:
            raise OAuthError("Perfil de Google incompleto (falta sub o email)")

        # 3. Buscar o crear usuario en MySQL
        user = OAuthService._find_or_create_user(
            provider="google",
            provider_id=str(provider_id),
            email=str(email),
            name=str(name),
            avatar=avatar,
            db=db
        )

        # 4. Generar tokens (mismo formato que login normal)
        return OAuthService._generate_jwt(user)

    @staticmethod
    async def _exchange_google_code(code: str, redirect_uri: str) -> dict:
        """Intercambia authorization code por access_token con Google."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": _get_env("GOOGLE_CLIENT_ID"),
                    "client_secret": _get_env("GOOGLE_CLIENT_SECRET"),
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
                timeout=10.0
            )

            if response.status_code != 200:
                logger.error(f"Google token exchange failed: {response.text}")
                raise OAuthError("Error al intercambiar código de Google")

            return response.json()
        return {}

    @staticmethod
    async def _get_google_profile(access_token: str) -> dict:
        """Obtiene el perfil del usuario autenticado en Google."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10.0
            )

            if response.status_code != 200:
                logger.error(f"Google userinfo failed: {response.text}")
                raise OAuthError("Error al obtener perfil de Google")

            return response.json()
        return {}

    # -------------------------------------------------------
    # GITHUB
    # -------------------------------------------------------

    @staticmethod
    def get_github_auth_url(redirect_uri: str, state: str) -> str:
        """
        Construye la URL de autorización de GitHub.

        Args:
            redirect_uri: URL de callback de tu backend
            state: Token aleatorio para prevenir CSRF

        Returns:
            str: URL completa para redirigir al usuario
        """
        import urllib.parse

        params = {
            "client_id": _get_env("GITHUB_CLIENT_ID"),
            "redirect_uri": redirect_uri,
            "scope": "user:email read:user",
            "state": state,
        }

        return f"{GITHUB_AUTH_URL}?{urllib.parse.urlencode(params)}"

    @staticmethod
    async def handle_github_callback(
        code: str,
        redirect_uri: str,
        db: Session
    ) -> Tuple[str, str]:
        """
        Procesa el callback de GitHub y retorna un JWT.

        Nota importante sobre GitHub:
            GitHub puede no devolver el email si el usuario lo tiene privado.
            En ese caso se hace una segunda request a /user/emails para obtenerlo.

        Args:
            code: Código de autorización recibido de GitHub
            redirect_uri: URL de callback registrada en GitHub
            db: Sesión de MySQL

        Returns:
            str: access_token JWT

        Raises:
            OAuthError: Si falla el intercambio de tokens o la API de GitHub
        """
        # 1. Obtener access_token de GitHub
        access_token = await OAuthService._exchange_github_code(code, redirect_uri)

        if not access_token:
            raise OAuthError("No se pudo obtener access_token de GitHub")

        # 2. Obtener perfil del usuario
        profile = await OAuthService._get_github_profile(access_token)

        provider_id = profile.get("id")
        name = profile.get("name") or profile.get("login", "GitHub User")
        avatar = profile.get("avatar_url")

        # GitHub puede no devolver email si es privado
        email = profile.get("email")
        if not email:
            email = await OAuthService._get_github_primary_email(access_token)

        if not provider_id:
            raise OAuthError("Perfil de GitHub incompleto (falta id)")

        if not email:
            raise OAuthError(
                "No se pudo obtener el email de GitHub. "
                "Por favor configura un email público en tu cuenta de GitHub."
            )

        # 3. Buscar o crear usuario en MySQL
        user = OAuthService._find_or_create_user(
            provider="github",
            provider_id=str(provider_id),
            email=str(email),
            name=str(name),
            avatar=avatar,
            db=db
        )

        # 4. Generar tokens
        return OAuthService._generate_jwt(user)

    @staticmethod
    async def _exchange_github_code(code: str, redirect_uri: str) -> Optional[str]:
        """Intercambia authorization code por access_token con GitHub."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                GITHUB_TOKEN_URL,
                json={
                    "code": code,
                    "client_id": _get_env("GITHUB_CLIENT_ID"),
                    "client_secret": _get_env("GITHUB_CLIENT_SECRET"),
                    "redirect_uri": redirect_uri,
                },
                headers={"Accept": "application/json"},
                timeout=10.0
            )

            if response.status_code != 200:
                logger.error(f"GitHub token exchange failed: {response.text}")
                raise OAuthError("Error al intercambiar código de GitHub")

            data = response.json()
            return data.get("access_token")

    @staticmethod
    async def _get_github_profile(access_token: str) -> dict:
        """Obtiene el perfil del usuario autenticado en GitHub."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                GITHUB_USER_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                },
                timeout=10.0
            )

            if response.status_code != 200:
                logger.error(f"GitHub user failed: {response.text}")
                raise OAuthError("Error al obtener perfil de GitHub")

            return response.json()
        return {}

    @staticmethod
    async def _get_github_primary_email(access_token: str) -> Optional[str]:
        """
        Obtiene el email primario verificado de GitHub.

        Se usa cuando el email del perfil es privado/nulo.
        Busca el email marcado como primary=True y verified=True.
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                GITHUB_EMAIL_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                },
                timeout=10.0
            )

            if response.status_code != 200:
                logger.warning(f"GitHub emails endpoint failed: {response.text}")
                return None

            emails = response.json()

            # Buscar email primario verificado
            for email_obj in emails:
                if email_obj.get("primary") and email_obj.get("verified"):
                    return email_obj.get("email")

            # Si no hay primario verificado, tomar el primer verificado
            for email_obj in emails:
                if email_obj.get("verified"):
                    return email_obj.get("email")

            return None

    # -------------------------------------------------------
    # LÓGICA COMPARTIDA
    # -------------------------------------------------------

    @staticmethod
    def _find_or_create_user(
        provider: str,
        provider_id: str,
        email: str,
        name: str,
        avatar: Optional[str],
        db: Session
    ) -> User:
        """
        Busca usuario existente o lo crea automáticamente.

        Estrategia de búsqueda (en orden):
            1. Buscar por provider + provider_id (login OAuth previo)
            2. Buscar por email (usuario ya registrado con email/password)
               → En este caso vincular el proveedor OAuth a la cuenta existente
            3. Si no existe → crear usuario nuevo

        Esto previene duplicados cuando el mismo email se usa
        con distintos métodos de login.

        Args:
            provider: "google" o "github"
            provider_id: ID único del usuario en el provider
            email: Email del usuario
            name: Nombre completo
            avatar: URL de foto de perfil
            db: Sesión de MySQL

        Returns:
            User: Usuario encontrado o creado
        """
        # 1. Buscar por provider_id (ya hizo OAuth antes)
        user = db.query(User).filter(
            User.provider == provider,
            User.provider_id == provider_id
        ).first()

        if user:
            logger.info(f"OAuth login: usuario existente encontrado {user.email} via {provider}")
            user.last_login = datetime.now(timezone.utc)
            db.commit()
            return user

        # 2. Buscar por email (cuenta con password existente)
        user = db.query(User).filter(User.email == email.lower()).first()

        if user:
            # Vincular proveedor OAuth a cuenta existente
            logger.info(f"OAuth login: vinculando {provider} a cuenta existente {email}")
            user.provider = provider
            user.provider_id = provider_id
            if avatar and not user.avatar:
                user.avatar = avatar
            user.last_login = datetime.now(timezone.utc)
            db.commit()
            return user

        # 3. Crear usuario nuevo
        logger.info(f"OAuth login: creando nuevo usuario {email} via {provider}")
        return OAuthService._create_oauth_user(
            provider=provider,
            provider_id=provider_id,
            email=email,
            name=name,
            avatar=avatar,
            db=db
        )

    @staticmethod
    def _create_oauth_user(
        provider: str,
        provider_id: str,
        email: str,
        name: str,
        avatar: Optional[str],
        db: Session
    ) -> User:
        """
        Crea un nuevo usuario OAuth en MySQL.

        El usuario se crea sin password_hash (login solo via OAuth).
        Se asigna el rol 'user' automáticamente.
        El primer usuario registrado en el sistema sigue siendo admin.

        Args:
            provider: "google" o "github"
            provider_id: ID del usuario en el provider
            email: Email verificado
            name: Nombre completo
            avatar: URL de avatar
            db: Sesión de MySQL

        Returns:
            User: Usuario recién creado
        """
        try:
            # Obtener rol 'user' (crear si no existe)
            user_role = db.query(Role).filter(Role.name == "user").first()
            if not user_role:
                user_role = Role(name="user", description="Regular user role")
                db.add(user_role)
                db.flush()

            # Verificar si es el primer usuario del sistema → darle admin
            is_first_user = db.query(User).count() == 0
            if is_first_user:
                admin_role = db.query(Role).filter(Role.name == "admin").first()
                if not admin_role:
                    admin_role = Role(name="admin", description="Administrator role")
                    db.add(admin_role)
                    db.flush()
                assigned_role = admin_role
            else:
                assigned_role = user_role

            # Crear usuario OAuth
            # password_hash tiene un placeholder — no se puede usar para login con password
            new_user = User(
                name=name.strip(),
                email=email.lower().strip(),
                password_hash="OAUTH_NO_PASSWORD",  # Placeholder, no usable
                role_id=assigned_role.id,
                provider=provider,
                provider_id=provider_id,
                avatar=avatar,
                is_active=True,
                last_login=datetime.now(timezone.utc),
            )

            db.add(new_user)
            db.commit()
            db.refresh(new_user)

            logger.info(f"Usuario OAuth creado: {email} ({provider})")
            return new_user

        except Exception as e:
            db.rollback()
            logger.exception(f"Error creando usuario OAuth {email}: {e}")
            raise OAuthError(f"Error al crear usuario: {str(e)}")

    @staticmethod
    def _generate_jwt(user: User) -> Tuple[str, str]:
        """
        Genera JWT usando security_service (mismo que login normal).

        El token tiene el mismo formato que los generados por AuthService.login_user(),
        lo que significa que get_current_user() funciona sin cambios.

        Args:
            user: Usuario autenticado

        Returns:
            Tuple[str, str]: (access_token, refresh_token)
        """
        token_data = {
            "sub": str(user.id),
            "role": user.role.name if user.role else "user",
            "email": user.email,
        }

        access_token = security_service.create_access_token(token_data)
        refresh_token = security_service.create_refresh_token(token_data)

        logger.info(f"Tokens generados para usuario OAuth: {user.email}")
        return access_token, refresh_token


# =========================================================
# CSRF STATE MANAGER
# =========================================================

class OAuthStateManager:
    """
    Maneja el parámetro `state` para prevenir ataques CSRF en OAuth.

    El state es un token aleatorio que:
        1. Se genera antes de redirigir al provider
        2. Se guarda en la sesión del usuario (cookie firmada)
        3. Se verifica cuando el provider hace callback
    """

    @classmethod
    def generate(cls, request) -> str:
        """Genera y almacena un token state aleatorio en la sesión."""
        import secrets
        state = secrets.token_urlsafe(32)
        request.session["oauth_state"] = state
        return state

    @classmethod
    def verify(cls, request, state: str) -> bool:
        """
        Verifica y consume un state de la sesión.

        Returns:
            bool: True si el state coincide con el guardado
        """
        stored_state = request.session.get("oauth_state")
        if stored_state and stored_state == state:
            # Limpiar el estado después de verificarlo (uso único)
            del request.session["oauth_state"]
            return True
        
        # Mostrar el state completo para evitar errores de tipado con el linter en slicing
        rec_display = f"{state}"
        stored_display = f"{stored_state}" if stored_state else "None"
        
        logger.warning(
            f"Verificación de state fallida. "
            f"Recibido: {rec_display}, Almacenado: {stored_display}. "
            f"Cookies recibidas: {request.cookies}"
        )
        return False


# =========================================================
# EXCEPCIÓN PERSONALIZADA
# =========================================================

class OAuthError(Exception):
    """
    Excepción para errores en el flujo OAuth.

    Se lanza cuando:
        - Falla el intercambio de código por token
        - La API del provider devuelve error
        - El perfil del usuario está incompleto
        - No se puede obtener el email

    Se captura en las rutas y convierte a HTTPException 400.
    """
    pass


# =========================================================
# HELPER PRIVADO
# =========================================================

def _get_env(key: str) -> str:
    """Obtiene variable de entorno requerida. Lanza error si falta."""
    import os
    value = os.getenv(key)
    if not value:
        raise OAuthError(
            f"Variable de entorno {key} no configurada. "
            f"Agrégala en tu archivo .env"
        )
    return value