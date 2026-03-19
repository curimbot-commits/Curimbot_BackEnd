"""
Módulo de administración de usuarios.

Endpoints para gestión de usuarios (listar, cambiar rol, activar/desactivar)
y estadísticas de inicio de sesión. Todos requieren privilegios de administrador.
"""

import logging
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status, Body
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.models import User, ActiveSession
from app.enums.enums import UserRole
from app.services.session_service import SessionService

from app.schemas.common_schemas import LoginStatsResponse
from app.schemas.user_schemas import UserCreate, UserInfoResponse, UserManagementResponse
from app.services.auth_service import (
    AccountLockedError,
    AuthService,
    InvalidCredentialsError,
    PermissionDeniedError,
    TokenBlacklistedError,
    TokenExpiredError,
    TwoFactorAuthService,
    UserAlreadyExistsError,
    UserNotFoundError,
    WeakPasswordError,
    get_client_info,
    get_current_user,
    require_admin
)


# ========================================
# CONFIGURACIÓN
# ========================================

router = APIRouter(prefix="/auth", tags=["authentication"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
logger = logging.getLogger(__name__)


# ========================================
# ENDPOINTS DE ADMINISTRACIÓN
# ========================================

@router.get("/users", response_model=List[UserInfoResponse])
def get_all_users(
    skip: int = 0,
    limit: int = 100,
    active_only: bool = True,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Obtener lista de usuarios del sistema con paginación.
    Solo disponible para administradores.

    Args:
        skip: Usuarios a omitir (>= 0).
        limit: Máximo de resultados (1–100).
        active_only: Si True, retorna solo usuarios activos.

    Raises:
        HTTPException 400: Parámetros de paginación inválidos.
        HTTPException 403: Sin privilegios de administrador.
    """
    try:
        if skip < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Skip no puede ser negativo"
            )
        if limit <= 0 or limit > 100:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Limit debe estar entre 1 y 100"
            )

        query = db.query(User)
        if active_only:
            query = query.filter(User.is_active == True)

        users = query.offset(skip).limit(limit).all()

        return [
            UserInfoResponse(
                id=user.id,
                email=user.email,
                name=user.name,
                role=user.role.name,
                created_at=user.created_at,
                last_login=user.last_login,
                is_active=user.is_active,
                two_factor_enabled=user.two_factor_enabled
            )
            for user in users
        ]

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting all users: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno del servidor"
        )


@router.patch("/users/{user_id}/role", response_model=UserManagementResponse)
def update_user_role(
    user_id: int,
    new_role: str = Body(..., embed=True, description="New role for the user (admin or user)"),
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Actualiza el rol de un usuario. Roles válidos: 'admin' o 'user'.

    Raises:
        HTTPException 400: user_id inválido o rol no permitido.
        HTTPException 403: Sin permisos o intento de modificar rol propio.
        HTTPException 404: Usuario no encontrado.
    """
    try:
        if user_id <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ID de usuario inválido"
            )
        if new_role not in ["admin", "user"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Rol inválido. Debe ser 'admin' o 'user'"
            )

        updated_user = AuthService.update_user_role(admin_user, user_id, new_role, db)

        return UserManagementResponse(
            message=f"Rol del usuario {updated_user.email} actualizado exitosamente a {new_role}",
            user_id=updated_user.id,
            user_email=updated_user.email,
            new_role=new_role,
            updated_by=admin_user.email,
            updated_at=datetime.now(timezone.utc)
        )

    except PermissionDeniedError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.patch("/users/{user_id}/deactivate", response_model=UserManagementResponse)
def deactivate_user(
    user_id: int,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Desactiva la cuenta de un usuario. Los usuarios desactivados no pueden iniciar sesión.
    Un administrador no puede desactivarse a sí mismo.

    Raises:
        HTTPException 400: user_id inválido.
        HTTPException 403: Sin permisos o intento de auto-desactivación.
        HTTPException 404: Usuario no encontrado.
    """
    try:
        if user_id <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ID de usuario inválido"
            )

        deactivated_user = AuthService.deactivate_user(admin_user, user_id, db)

        return UserManagementResponse(
            message=f"Usuario {deactivated_user.email} desactivado exitosamente",
            user_id=deactivated_user.id,
            user_email=deactivated_user.email,
            new_role=deactivated_user.role.name,
            updated_by=admin_user.email,
            updated_at=datetime.now(timezone.utc)
        )

    except PermissionDeniedError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except UserNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Unexpected error deactivating user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno del servidor"
        )


@router.patch("/users/{user_id}/activate", response_model=UserManagementResponse)
def activate_user(
    user_id: int,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Reactiva la cuenta de un usuario previamente desactivado.

    Raises:
        HTTPException 400: user_id inválido.
        HTTPException 403: Sin privilegios de administrador.
        HTTPException 404: Usuario no encontrado.
    """
    try:
        if user_id <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ID de usuario inválido"
            )

        activated_user = AuthService.activate_user(admin_user, user_id, db)
        logger.info(f"User activated: {activated_user.email} by {admin_user.email}")

        return UserManagementResponse(
            message=f"Usuario {activated_user.email} activado exitosamente",
            user_id=activated_user.id,
            user_email=activated_user.email,
            new_role=activated_user.role.name,
            updated_by=admin_user.email,
            updated_at=datetime.now(timezone.utc)
        )

    except PermissionDeniedError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except UserNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Unexpected error activating user: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno del servidor"
        )


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Elimina permanentemente un usuario.
    Solo disponible para administradores.
    Punto de refinamiento 9.
    """
    try:
        if user_id <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ID de usuario inválido"
            )

        AuthService.delete_user(admin_user, user_id, db)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    except PermissionDeniedError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except UserNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.exception(f"Error deleting user {user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno del servidor"
        )

@router.delete("/{session_id}", tags=["sessions"], summary="Revocar sesión (Legacy/Compatibilidad)")
def revoke_session_legacy(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Punto de refinamiento Phase 2.
    Resuelve el error 404 cuando el frontend llama a DELETE /auth/{id}.
    Redirige la lógica al servicio de sesiones.
    """
    try:
        return SessionService.revoke_session(
            session_id=session_id,
            user_id=current_user.id,
            db=db,
            requester_user_id=current_user.id
        )
    except Exception as e:
        logger.exception(f"Error en revocación legacy para sesión {session_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al revocar sesión"
        )


@router.get("/users/{user_id}/login-stats", response_model=LoginStatsResponse)
def get_user_login_stats(
    user_id: int,
    hours: int = 24,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Estadísticas de intentos de inicio de sesión de un usuario en un período dado.
    Útil para análisis de seguridad y auditoría.

    Args:
        hours: Número de horas hacia atrás a consultar (default 24).

    Raises:
        HTTPException 400: user_id inválido.
        HTTPException 403: Sin privilegios de administrador.
        HTTPException 404: Usuario no encontrado.
    """
    try:
        if user_id <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ID de usuario inválido"
            )

        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Usuario no encontrado"
            )

        stats = AuthService.get_login_attempts_stats(user.email, db, hours)

        return LoginStatsResponse(
            email=stats["email"],
            period_hours=stats["period_hours"],
            total_attempts=stats["total_attempts"],
            successful_attempts=stats["successful_attempts"],
            failed_attempts=stats["failed_attempts"],
            success_rate=stats["success_rate"],
            last_attempt=stats["last_attempt"]
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting login stats for user {user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno del servidor"
        )
