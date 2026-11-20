"""
Rutas OAuth para autenticación social con Google.

Endpoints:
    GET /auth/google/login        → Redirige a Google
    GET /auth/google/callback     → Procesa respuesta de Google

Anti-CSRF (state):
    - Formato: {timestamp}.{token_hex}.{hmac_signature_hex}, firmado con SECRET_KEY
    - Se guarda también en la cookie HttpOnly `oauth_state` del navegador que
      inició el login; el callback exige que coincidan y que no haya caducado
      (10 min). Así un atacante no puede completar el flujo en el navegador
      de la víctima (login CSRF).
    - El redirect_uri es FIJO (sin query params) → compatible con Google Console

Resultado del callback (redirect a {FRONTEND_URL}/auth/callback):
    - ?status=success          → cookies de sesión HttpOnly ya establecidas
    - #requires_2fa=1&challenge=...&email=...  → el usuario tiene 2FA; el
      frontend completa con /auth/login-with-2fa. Va en el fragmento (#), que
      el navegador no envía a servidores, logs ni Referer.
    - ?error=<código>          → cancelled | invalid_state | email_not_verified
                                 | account_disabled | oauth_failed | server_error
    Los tokens de sesión nunca viajan en la URL.
"""

import hashlib
import hmac
import logging
import os
import secrets
import time
from typing import Annotated, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import rate_limit
from app.db.database import get_db
from app.models.models import User
from app.services import security_service
from app.services.oauth_service import (
    OAuthEmailNotVerifiedError,
    OAuthError,
    OAuthService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["OAuth - Social Login"])

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:4200")
BACKEND_URL  = os.getenv("BACKEND_URL",  "http://localhost:8000")

# URI FIJO — registrado exactamente así en Google Cloud Console
GOOGLE_CALLBACK_URI = f"{BACKEND_URL}/auth/google/callback"

STATE_COOKIE = "oauth_state"
STATE_MAX_AGE_SECONDS = 600


# =========================================================
# STATE HELPERS
# =========================================================

def _sign(value: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()


def _generate_state() -> str:
    """State firmado con HMAC-SHA256: {timestamp}.{token}.{firma}."""
    payload = f"{int(time.time())}.{secrets.token_hex(32)}"
    return f"{payload}.{_sign(payload)}"


def _verify_state(state: Optional[str], cookie_state: Optional[str]) -> bool:
    """
    True solo si el state:
      - coincide con la cookie del navegador que inició el login,
      - tiene firma HMAC válida,
      - no ha caducado.
    """
    if not state or not cookie_state:
        return False
    if not hmac.compare_digest(state, cookie_state):
        return False
    try:
        timestamp, token, sig = state.split(".")
        if not hmac.compare_digest(sig, _sign(f"{timestamp}.{token}")):
            return False
        return 0 <= time.time() - int(timestamp) <= STATE_MAX_AGE_SECONDS
    except (ValueError, TypeError):
        return False


def _redirect_with_state(auth_url: str, state: str) -> RedirectResponse:
    response = RedirectResponse(url=auth_url)
    response.set_cookie(
        key=STATE_COOKIE,
        value=state,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",          # se envía en el redirect top-level del proveedor
        max_age=STATE_MAX_AGE_SECONDS,
        path="/auth",
    )
    return response


def _frontend_redirect(query: str = "", fragment: str = "") -> RedirectResponse:
    url = f"{FRONTEND_URL}/auth/callback"
    if query:
        url += f"?{query}"
    if fragment:
        url += f"#{fragment}"
    response = RedirectResponse(url=url)
    response.delete_cookie(STATE_COOKIE, path="/auth")
    return response


def _error_redirect(code: str) -> RedirectResponse:
    return _frontend_redirect(query=urlencode({"error": code}))


# =========================================================
# FINALIZACIÓN COMÚN DEL LOGIN
# =========================================================

def _complete_login(request: Request, user: User, db: Session) -> RedirectResponse:
    """Aplica las mismas reglas que el login con contraseña."""
    if not user.is_active:
        return _error_redirect("account_disabled")

    if user.two_factor_enabled:
        challenge = security_service.create_2fa_challenge_token(user.id)
        fragment = urlencode({"requires_2fa": "1", "challenge": challenge, "email": user.email})
        return _frontend_redirect(fragment=fragment)

    from app.api.v1.routes.auth_endpoints.autentication import _set_auth_cookies
    from app.services.auth_service import get_client_info
    from app.services.session_service import SessionService

    access_token, refresh_token = OAuthService._generate_jwt(user)
    ip_address, user_agent = get_client_info(request)
    SessionService.create_session(
        user_id=user.id,
        access_token=access_token,
        refresh_token=refresh_token,
        ip_address=ip_address,
        user_agent=user_agent,
        db=db,
        is_current=True,
    )

    response = _frontend_redirect(query="status=success")
    _set_auth_cookies(response, access_token, refresh_token)
    return response


async def _handle_callback(provider: str, handler, callback_uri: str,
                           request: Request, code: Optional[str], state: Optional[str],
                           error: Optional[str], db: Session) -> RedirectResponse:
    if error:
        logger.warning(f"Usuario canceló login en {provider}: {error}")
        return _error_redirect("cancelled")

    if not _verify_state(state, request.cookies.get(STATE_COOKIE)):
        logger.warning(f"State OAuth de {provider} inválido, caducado o sin cookie")
        return _error_redirect("invalid_state")

    if not code:
        return _error_redirect("oauth_failed")

    try:
        user = await handler(code=code, redirect_uri=callback_uri, db=db)
        logger.info(f"{provider} OAuth completado para usuario {user.id}")
        return _complete_login(request, user, db)
    except OAuthEmailNotVerifiedError as e:
        logger.warning(f"Login {provider} rechazado: {e}")
        return _error_redirect("email_not_verified")
    except OAuthError as e:
        logger.error(f"Error en callback de {provider}: {e}")
        return _error_redirect("oauth_failed")
    except Exception as e:
        logger.exception(f"Error inesperado en callback de {provider}: {e}")
        return _error_redirect("server_error")


# =========================================================
# GOOGLE OAUTH
# =========================================================

@router.get(
    "/google/login",
    summary="Iniciar login con Google",
    description="Redirige al usuario a la pantalla de autorización de Google",
    dependencies=[Depends(rate_limit(20, 60))],
)
def google_login():
    """
    Inicia el flujo OAuth con Google.
    Angular debe navegar a: {apiUrl}/auth/google/login
    """
    try:
        state = _generate_state()
        auth_url = OAuthService.get_google_auth_url(redirect_uri=GOOGLE_CALLBACK_URI, state=state)
        return _redirect_with_state(auth_url, state)
    except OAuthError as e:
        logger.error(f"Error iniciando OAuth con Google: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Login con Google no disponible")


@router.get(
    "/google/callback",
    summary="Callback de Google OAuth",
    description="Google redirige aquí después de que el usuario autoriza",
)
async def google_callback(
    request: Request,
    db: Session = Depends(get_db),
    code:  Annotated[Optional[str], Query(description="Código de autorización de Google")] = None,
    state: Annotated[Optional[str], Query(description="State devuelto por Google")] = None,
    error: Annotated[Optional[str], Query(description="Error si el usuario canceló")] = None,
):
    return await _handle_callback("Google", OAuthService.handle_google_callback,
                                  GOOGLE_CALLBACK_URI, request, code, state, error, db)
