from datetime import datetime, timezone
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.models import ActiveSession, User
from app.schemas.session_schemas import (
    ActiveSessionOut,
    RevokeSessionRequest,
    RevokeAllSessionsRequest,
    SessionStatsResponse
)
from app.services.session_service import SessionService
from app.services.auth_service import get_current_user

router = APIRouter(prefix="/sessions", tags=["sessions"])
logger = logging.getLogger(__name__)


@router.get(
    "/active",
    response_model=List[ActiveSessionOut],
    summary="Obtener sesiones activas",
    description="Retorna todas las sesiones activas del usuario actual"
)
def get_active_sessions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtiene todas las sesiones activas del usuario actual
    
    Returns:
        Lista de sesiones activas con información de dispositivo, ubicación y última actividad
    """
    try:
        sessions = SessionService.get_user_sessions(
            user_id=current_user.id,
            db=db,
            active_only=True
        )
        
        return sessions
        
    except Exception as e:
        logger.exception(f"Error obteniendo sesiones activas: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener sesiones activas"
        )


@router.delete(
    "/{session_id}",
    summary="Revocar sesión específica",
    description="Revoca una sesión específica del usuario actual"
)
def revoke_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Revoca una sesión específica
    
    Args:
        session_id: ID de la sesión a revocar
        
    Returns:
        Mensaje de confirmación
        
    Raises:
        404: Si la sesión no existe
        403: Si no tienes permisos para revocar esta sesión
    """
    try:
        result = SessionService.revoke_session(
            session_id=session_id,
            user_id=current_user.id,
            db=db,
            requester_user_id=current_user.id
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error revocando sesión {session_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al revocar sesión"
        )


@router.post(
    "/revoke-all",
    summary="Revocar todas las sesiones",
    description="Revoca todas las sesiones del usuario excepto la actual (opcional)"
)
def revoke_all_sessions(
    request_data: RevokeAllSessionsRequest = RevokeAllSessionsRequest(except_current=True),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Revoca todas las sesiones del usuario
    
    Args:
        except_current: Si mantener la sesión actual activa (default: True)
        
    Returns:
        Mensaje con número de sesiones revocadas
    """
    try:
        # Obtener ID de sesión actual
        current_session_id = None
        if request_data.except_current:
            current_session = db.query(ActiveSession).filter(
                ActiveSession.user_id == current_user.id,
                ActiveSession.is_current == True
            ).first()
            
            if current_session:
                current_session_id = current_session.id
        
        result = SessionService.revoke_all_sessions(
            user_id=current_user.id,
            db=db,
            except_current=request_data.except_current,
            current_session_id=current_session_id
        )
        
        return result
        
    except Exception as e:
        logger.exception(f"Error revocando todas las sesiones: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al revocar sesiones"
        )


@router.get(
    "/stats",
    response_model=SessionStatsResponse,
    summary="Estadísticas de sesiones",
    description="Obtiene estadísticas de sesiones del usuario actual"
)
def get_session_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtiene estadísticas de sesiones del usuario actual
    
    Returns:
        Estadísticas con total de sesiones, activas, inactivas, etc.
    """
    try:
        all_sessions = SessionService.get_user_sessions(
            user_id=current_user.id,
            db=db,
            active_only=False
        )
        
        active_sessions = [s for s in all_sessions if s.is_active and s.expires_at > datetime.now(timezone.utc)]
        current_session = next((s for s in active_sessions if s.is_current), None)
        
        return SessionStatsResponse(
            total_sessions=len(all_sessions),
            active_sessions=len(active_sessions),
            inactive_sessions=len(all_sessions) - len(active_sessions),
            current_device=current_session.device if current_session else None,
            last_login=current_user.last_login
        )
        
    except Exception as e:
        logger.exception(f"Error obteniendo estadísticas de sesiones: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener estadísticas"
        )