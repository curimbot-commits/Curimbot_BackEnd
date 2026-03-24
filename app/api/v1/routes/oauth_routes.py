"""
Rutas OAuth para autenticación social con Google y GitHub.

Endpoints:
    GET /auth/google/login        → Redirige a Google
    GET /auth/google/callback     → Procesa respuesta de Google
    GET /auth/github/login        → Redirige a GitHub
    GET /auth/github/callback     → Procesa respuesta de GitHub

Flujo anti-CSRF sin cookies:
    - El state es self-contained y firmado con HMAC-SHA256 usando SECRET_KEY
    - Formato: {token_hex}.{hmac_signature_hex}
    - No requiere sesión, cookies ni almacenamiento en servidor
    - El redirect_uri es FIJO (sin query params) → compatible con Google Console

Registro en main.py:
    from app.routes.oauth_routes import router as oauth_router
    app.include_router(oauth_router)
"""

import hashlib
import hmac
import logging
import os
import secrets
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.services.oauth_service import OAuthError, OAuthService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["OAuth - Social Login"])

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:4200")
BACKEND_URL  = os.getenv("BACKEND_URL",  "http://localhost:8000")

# URIs FIJOS — registrados exactamente así en Google Cloud Console y GitHub OAuth App
GOOGLE_CALLBACK_URI = f"{BACKEND_URL}/auth/google/callback"
GITHUB_CALLBACK_URI = f"{BACKEND_URL}/auth/github/callback"


# =========================================================
# STATE HELPERS — self-contained, sin cookies ni sesión
# =========================================================

def _generate_state() -> str:
    """
    Genera un state OAuth self-contained firmado con HMAC-SHA256.

    Formato: {token}.{hmac_signature}
        - token:     32 bytes aleatorios en hex (64 chars)
        - signature: HMAC-SHA256(token, SECRET_KEY) en hex

    El state es verificable sin almacenamiento porque la firma
    solo puede generarla el servidor que conoce el SECRET_KEY.
    Resiste ataques CSRF — un atacante no puede forjar la firma.
    """
    token = secrets.token_hex(32)
    sig = hmac.new(
        settings.SECRET_KEY.encode(),
        token.encode(),
        hashlib.sha256
    ).hexdigest()
    return f"{token}.{sig}"


def _verify_state(state: str) -> bool:
    """
    Verifica que el state fue generado por este servidor (firma HMAC válida).

    Returns False si el state fue manipulado, está malformado,
    o fue generado con un SECRET_KEY diferente.
    """
    try:
        token, sig = state.rsplit(".", 1)
        expected_sig = hmac.new(
            settings.SECRET_KEY.encode(),
            token.encode(),
            hashlib.sha256
        ).hexdigest()
        # compare_digest previene timing attacks
        return hmac.compare_digest(sig, expected_sig)
    except Exception:
        return False


# =========================================================
# GOOGLE OAUTH
# =========================================================

@router.get(
    "/google/login",
    summary="Iniciar login con Google",
    description="Redirige al usuario a la pantalla de autorización de Google"
)
def google_login(request: Request):
    """
    Inicia el flujo OAuth con Google.

    Genera un state firmado con HMAC (self-contained, sin cookies).
    El redirect_uri es fijo para cumplir con la validación de Google.

    Angular debe llamar:
        window.location.href = 'http://localhost:8000/auth/google/login'
    """
    try:
        state = _generate_state()

        auth_url = OAuthService.get_google_auth_url(
            redirect_uri=GOOGLE_CALLBACK_URI,
            state=state
        )

        logger.info(f"Iniciando OAuth con Google, state={state[:8]}...")
        return RedirectResponse(url=auth_url)

    except OAuthError as e:
        logger.error(f"Error iniciando OAuth con Google: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    except Exception as e:
        logger.exception(f"Error inesperado en google_login: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error interno del servidor")


@router.get(
    "/google/callback",
    summary="Callback de Google OAuth",
    description="Google redirige aquí después de que el usuario autoriza"
)
async def google_callback(
    request: Request,
    code:  Annotated[str, Query(description="Código de autorización de Google")],
    state: Annotated[str, Query(description="State devuelto por Google")],
    db:    Session = Depends(get_db),
    error: Annotated[Optional[str], Query(description="Error si el usuario canceló")] = None,
):
    """
    Procesa el callback de Google OAuth.

    Verifica la firma HMAC del state — sin cookies, sin sesión.
    Si la firma es válida, el state fue generado por este servidor
    y el flujo es legítimo.
    """
    if error:
        logger.warning(f"Usuario canceló login en Google: {error}")
        return RedirectResponse(url=f"{FRONTEND_URL}/auth/callback?error=cancelled")

    if not _verify_state(state):
        logger.warning(f"State OAuth inválido o manipulado: {state[:8]}...")
        return RedirectResponse(url=f"{FRONTEND_URL}/auth/callback?error=invalid_state")

    try:
        jwt_token, refresh_token = await OAuthService.handle_google_callback(
            code=code,
            redirect_uri=GOOGLE_CALLBACK_URI,
            db=db
        )

        from app.services.session_service import SessionService
        from app.services.auth_service import get_client_info
        ip_address, user_agent = get_client_info(request)

        SessionService.create_session(
            user_id=None,
            access_token=jwt_token,
            refresh_token=refresh_token,
            ip_address=ip_address,
            user_agent=user_agent,
            db=db,
            is_current=True
        )

        logger.info("Google OAuth completado, redirigiendo a Angular")

        response = RedirectResponse(url=f"{FRONTEND_URL}/auth/callback?token={jwt_token}&refresh={refresh_token}")
        return response

    except OAuthError as e:
        logger.error(f"Error en callback de Google: {e}")
        return RedirectResponse(url=f"{FRONTEND_URL}/auth/callback?error={str(e)}")
    except Exception as e:
        logger.exception(f"Error inesperado en google_callback: {e}")
        return RedirectResponse(url=f"{FRONTEND_URL}/auth/callback?error=server_error")


class OAuthTokens(BaseModel):
    token: str
    refresh: str

@router.post("/oauth/set-cookies")
async def set_oauth_cookies(
    tokens: OAuthTokens,
    db: Session = Depends(get_db)
):
    """
    Recibe los tokens OAuth y los setea como cookies HttpOnly
    en el contexto del frontend (mismo origen via proxy).
    """
    try:
        # Validar que el token sea legítimo antes de setearlo
        from app.services.auth_service import AuthService
        user = AuthService.get_user_from_token(tokens.token, db)
        
        is_secure = not settings.DEBUG
        # En producción (HTTPS) usamos SameSite=none para permitir cookies
        # en peticiones XHR cross-origin (curimbot.com → api.curimbot.com).
        # En local (HTTP) usamos SameSite=lax porque todo corre en localhost.
        samesite = "none" if is_secure else "lax"
        response = JSONResponse(content={
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role.name,
            "is_active": user.is_active,
            "two_factor_enabled": user.two_factor_enabled,
            "last_login": str(user.last_login),
            "created_at": str(user.created_at),
        })
        response.set_cookie(
            key="access_token",
            value=tokens.token,
            httponly=True,
            secure=is_secure,
            samesite=samesite,
            max_age=3600 * 24
        )
        response.set_cookie(
            key="refresh_token",
            value=tokens.refresh,
            httponly=True,
            secure=is_secure,
            samesite=samesite,
            path="/auth/refresh",
            max_age=3600 * 24 * 7
        )
        return response
        
    except Exception as e:
        logger.exception(f"Error setting oauth cookies: {e}")
        raise HTTPException(status_code=401, detail="Token OAuth inválido")


# =========================================================
# GITHUB OAUTH
# =========================================================

@router.get(
    "/github/login",
    summary="Iniciar login con GitHub",
    description="Redirige al usuario a la pantalla de autorización de GitHub"
)
def github_login(request: Request):
    """
    Inicia el flujo OAuth con GitHub.

    Angular debe llamar:
        window.location.href = 'http://localhost:8000/auth/github/login'
    """
    try:
        state = _generate_state()

        auth_url = OAuthService.get_github_auth_url(
            redirect_uri=GITHUB_CALLBACK_URI,
            state=state
        )

        logger.info(f"Iniciando OAuth con GitHub, state={state[:8]}...")
        return RedirectResponse(url=auth_url)

    except OAuthError as e:
        logger.error(f"Error iniciando OAuth con GitHub: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    except Exception as e:
        logger.exception(f"Error inesperado en github_login: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error interno del servidor")


@router.get(
    "/github/callback",
    summary="Callback de GitHub OAuth",
    description="GitHub redirige aquí después de que el usuario autoriza"
)
async def github_callback(
    request: Request,
    code:  Annotated[str, Query(description="Código de autorización de GitHub")],
    state: Annotated[str, Query(description="State devuelto por GitHub")],
    db:    Session = Depends(get_db),
    error: Annotated[Optional[str], Query(description="Error si el usuario canceló")] = None,
):
    """
    Procesa el callback de GitHub OAuth.

    Igual que google_callback. GitHub puede no devolver email si es
    privado — el servicio hace una segunda request a /user/emails.
    """
    if error:
        logger.warning(f"Usuario canceló login en GitHub: {error}")
        return RedirectResponse(url=f"{FRONTEND_URL}/auth/callback?error=cancelled")

    if not _verify_state(state):
        logger.warning(f"State OAuth inválido o manipulado: {state[:8]}...")
        return RedirectResponse(url=f"{FRONTEND_URL}/auth/callback?error=invalid_state")

    try:
        jwt_token, refresh_token = await OAuthService.handle_github_callback(
            code=code,
            redirect_uri=GITHUB_CALLBACK_URI,
            db=db
        )

        from app.services.session_service import SessionService
        from app.services.auth_service import get_client_info
        ip_address, user_agent = get_client_info(request)

        SessionService.create_session(
            user_id=None,
            access_token=jwt_token,
            refresh_token=refresh_token,
            ip_address=ip_address,
            user_agent=user_agent,
            db=db,
            is_current=True
        )

        logger.info("GitHub OAuth completado, redirigiendo a Angular")

        response = RedirectResponse(url=f"{FRONTEND_URL}/auth/callback?token={jwt_token}&refresh={refresh_token}")
        return response

    except OAuthError as e:
        logger.error(f"Error en callback de GitHub: {e}")
        return RedirectResponse(url=f"{FRONTEND_URL}/auth/callback?error={str(e)}")
    except Exception as e:
        logger.exception(f"Error inesperado en github_callback: {e}")
        return RedirectResponse(url=f"{FRONTEND_URL}/auth/callback?error=server_error")