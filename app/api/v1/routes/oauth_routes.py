"""
Rutas OAuth para autenticación social con Google y GitHub.

Endpoints:
    GET /auth/google/login        → Redirige a Google
    GET /auth/google/callback     → Procesa respuesta de Google
    GET /auth/github/login        → Redirige a GitHub
    GET /auth/github/callback     → Procesa respuesta de GitHub

Flujo completo:
    Angular hace window.location.href = "/auth/google/login"
        ↓
    Backend redirige a Google
        ↓
    Usuario acepta en Google
        ↓
    Google redirige a /auth/google/callback?code=xxx&state=yyy
        ↓
    Backend procesa, genera JWT
        ↓
    Backend redirige a Angular: http://localhost:4200/auth/callback?token=JWT
        ↓
    Angular guarda el token y autentica al usuario

Registro en main.py:
    from app.routes.oauth_routes import router as oauth_router
    app.include_router(oauth_router)
"""

import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.oauth_service import OAuthError, OAuthService, OAuthStateManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["OAuth - Social Login"])

# URL base del frontend Angular (desde .env)
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:4200")

# URLs de callback que deben coincidir EXACTAMENTE con las configuradas
# en Google Cloud Console y GitHub OAuth App
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
GOOGLE_CALLBACK_URI = f"{BACKEND_URL}/auth/google/callback"
GITHUB_CALLBACK_URI = f"{BACKEND_URL}/auth/github/callback"


# =========================================================
# GOOGLE OAUTH
# =========================================================

@router.get(
    "/google/login",
    summary="Iniciar login con Google",
    description="Redirige al usuario a la pantalla de autorización de Google"
)
def google_login():
    """
    Inicia el flujo OAuth con Google.

    Genera un state aleatorio para prevenir CSRF y redirige al usuario
    a la pantalla de autorización de Google.

    Angular debe llamar:
        window.location.href = 'http://localhost:8000/auth/google/login'

    O usar un botón:
        <a href="http://localhost:8000/auth/google/login">Login con Google</a>

    Returns:
        RedirectResponse: Redirección a Google OAuth

    Raises:
        HTTPException 500: Si GOOGLE_CLIENT_ID no está configurado
    """
    try:
        # Generar state para prevenir CSRF
        state = OAuthStateManager.generate()

        # Construir URL de autorización de Google
        auth_url = OAuthService.get_google_auth_url(
            redirect_uri=GOOGLE_CALLBACK_URI,
            state=state
        )

        logger.info(f"Iniciando OAuth con Google, state={state[:8]}...")
        return RedirectResponse(url=auth_url)

    except OAuthError as e:
        logger.error(f"Error iniciando OAuth con Google: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    except Exception as e:
        logger.exception(f"Error inesperado en google_login: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno del servidor"
        )


from typing import Annotated, Optional, List

@router.get(
    "/google/callback",
    summary="Callback de Google OAuth",
    description="Google redirige aquí después de que el usuario autoriza"
)
async def google_callback(
    code: Annotated[str, Query(description="Código de autorización de Google")],
    state: Annotated[str, Query(description="State para verificación CSRF")],
    db: Session = Depends(get_db),
    error: Annotated[Optional[str], Query(description="Error si el usuario canceló")] = None
):
    """
    Procesa el callback de Google OAuth.

    Google redirige aquí con ?code=xxx&state=yyy después de que
    el usuario autoriza. Este endpoint:
        1. Verifica el state (anti-CSRF)
        2. Intercambia el code por un access_token con Google
        3. Obtiene el perfil del usuario
        4. Busca o crea el usuario en MySQL
        5. Genera JWT
        6. Redirige a Angular con el token

    Angular recibirá:
        http://localhost:4200/auth/callback?token=eyJhbGci...

    Args:
        code: Código de autorización temporal (expira en minutos)
        state: Token anti-CSRF generado en google_login
        error: Si el usuario canceló el login en Google
        db: Sesión de MySQL

    Returns:
        RedirectResponse: Redirige a Angular con ?token=JWT o ?error=mensaje
    """
    # Manejar cancelación del usuario en Google
    if error:
        logger.warning(f"Usuario canceló login en Google: {error}")
        return RedirectResponse(
            url=f"{FRONTEND_URL}/auth/callback?error=cancelled"
        )

    # Verificar state anti-CSRF
    if not OAuthStateManager.verify(state):
        logger.warning(f"State OAuth inválido o expirado: {state[:8]}...")
        return RedirectResponse(
            url=f"{FRONTEND_URL}/auth/callback?error=invalid_state"
        )

    try:
        # Procesar callback: intercambiar code → perfil → JWT
        jwt_token = await OAuthService.handle_google_callback(
            code=code,
            redirect_uri=GOOGLE_CALLBACK_URI,
            db=db
        )

        logger.info("Google OAuth completado, redirigiendo a Angular con JWT")

        # Redirigir a Angular con el token en la URL
        # Angular lo capturará con ActivatedRoute.queryParams
        return RedirectResponse(
            url=f"{FRONTEND_URL}/auth/callback?token={jwt_token}"
        )

    except OAuthError as e:
        logger.error(f"Error en callback de Google: {e}")
        return RedirectResponse(
            url=f"{FRONTEND_URL}/auth/callback?error={str(e)}"
        )
    except Exception as e:
        logger.exception(f"Error inesperado en google_callback: {e}")
        return RedirectResponse(
            url=f"{FRONTEND_URL}/auth/callback?error=server_error"
        )


# =========================================================
# GITHUB OAUTH
# =========================================================

@router.get(
    "/github/login",
    summary="Iniciar login con GitHub",
    description="Redirige al usuario a la pantalla de autorización de GitHub"
)
def github_login():
    """
    Inicia el flujo OAuth con GitHub.

    Angular debe llamar:
        window.location.href = 'http://localhost:8000/auth/github/login'

    Returns:
        RedirectResponse: Redirección a GitHub OAuth

    Raises:
        HTTPException 500: Si GITHUB_CLIENT_ID no está configurado
    """
    try:
        state = OAuthStateManager.generate()

        auth_url = OAuthService.get_github_auth_url(
            redirect_uri=GITHUB_CALLBACK_URI,
            state=state
        )

        logger.info(f"Iniciando OAuth con GitHub, state={state[:8]}...")
        return RedirectResponse(url=auth_url)

    except OAuthError as e:
        logger.error(f"Error iniciando OAuth con GitHub: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    except Exception as e:
        logger.exception(f"Error inesperado en github_login: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno del servidor"
        )


@router.get(
    "/github/callback",
    summary="Callback de GitHub OAuth",
    description="GitHub redirige aquí después de que el usuario autoriza"
)
async def github_callback(
    code: Annotated[str, Query(description="Código de autorización de GitHub")],
    state: Annotated[str, Query(description="State para verificación CSRF")],
    db: Session = Depends(get_db),
    error: Annotated[Optional[str], Query(description="Error si el usuario canceló")] = None
):
    """
    Procesa el callback de GitHub OAuth.

    Igual que google_callback pero con las particularidades de GitHub:
        - GitHub puede no devolver email si es privado
        - Se hace segunda request a /user/emails si es necesario

    Args:
        code: Código de autorización temporal
        state: Token anti-CSRF
        error: Si el usuario canceló
        db: Sesión de MySQL

    Returns:
        RedirectResponse: Redirige a Angular con ?token=JWT o ?error=mensaje
    """
    # Manejar cancelación
    if error:
        logger.warning(f"Usuario canceló login en GitHub: {error}")
        return RedirectResponse(
            url=f"{FRONTEND_URL}/auth/callback?error=cancelled"
        )

    # Verificar state anti-CSRF
    if not OAuthStateManager.verify(state):
        logger.warning(f"State OAuth inválido o expirado: {state[:8]}...")
        return RedirectResponse(
            url=f"{FRONTEND_URL}/auth/callback?error=invalid_state"
        )

    try:
        jwt_token = await OAuthService.handle_github_callback(
            code=code,
            redirect_uri=GITHUB_CALLBACK_URI,
            db=db
        )

        logger.info("GitHub OAuth completado, redirigiendo a Angular con JWT")

        return RedirectResponse(
            url=f"{FRONTEND_URL}/auth/callback?token={jwt_token}"
        )

    except OAuthError as e:
        logger.error(f"Error en callback de GitHub: {e}")
        return RedirectResponse(
            url=f"{FRONTEND_URL}/auth/callback?error={str(e)}"
        )
    except Exception as e:
        logger.exception(f"Error inesperado en github_callback: {e}")
        return RedirectResponse(
            url=f"{FRONTEND_URL}/auth/callback?error=server_error"
        )