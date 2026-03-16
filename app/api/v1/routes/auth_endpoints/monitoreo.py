"""
Módulo de monitoreo y estadísticas del servicio de autenticación.

Este módulo proporciona endpoints para verificar el estado de salud del servicio
de autenticación y obtener estadísticas agregadas sobre usuarios y actividad.
Los endpoints de estadísticas requieren privilegios de administrador.
"""

from app.services.auth_service import AuthService, require_admin
from app.services.security_service import verify_password
import logging
from datetime import datetime, timezone
from typing import List, Optional
from .....schemas.auth_schemas import (
    ActiveSessionsResponse, BackupCodesResponse, RefreshTokenRequest, 
    ResetPasswordRequest, Token, TwoFactorConfirmRequest, TwoFactorDisableRequest, 
    TwoFactorSetupResponse, TwoFactorVerifyRequest
)

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status, Body
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.models import Role, User
from app.enums.enums import UserRole

from app.schemas.common_schemas import LoginStatsResponse
from app.schemas.user_schemas import UserCreate, UserInfoResponse, UserManagementResponse


# ========================================
# 🔧 CONFIGURACIÓN
# ========================================

router = APIRouter(prefix="/auth", tags=["authentication"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
logger = logging.getLogger(__name__)


# ========================================
# 🏥 ENDPOINTS DE MONITOREO
# ========================================

@router.get("/health", status_code=status.HTTP_200_OK)
def health_check(db: Session = Depends(get_db)):
    """
    Verificar el estado de salud del servicio de autenticación.
    
    Este endpoint es utilizado por sistemas de monitoreo, load balancers y
    orquestadores de contenedores (como Kubernetes) para determinar si el
    servicio está operativo y puede recibir tráfico.
    
    Verificaciones realizadas:
        - Conectividad con la base de datos
        - Capacidad de ejecutar consultas SQL
        - Estado general del servicio
    
    Casos de uso:
        - Health checks de Kubernetes/Docker
        - Monitoreo de disponibilidad con Prometheus/Grafana
        - Verificación de conectividad en pipelines CI/CD
        - Balanceo de carga basado en salud del servicio
    
    Args:
        db (Session): Sesión de base de datos (inyectada automáticamente)
    
    Returns:
        dict: Estado del servicio incluyendo:
            - status: "healthy" si todo funciona correctamente
            - service: Nombre del servicio ("auth-service")
            - timestamp: Fecha y hora de la verificación en formato ISO 8601
            - database: Estado de conexión a BD ("connected" o error)
    
    Raises:
        HTTPException 503: Servicio no disponible, fallo en conexión a base de datos
    
    Example:
        GET /auth/health
        
        Response (200 OK):
        {
            "status": "healthy",
            "service": "auth-service",
            "timestamp": "2025-11-02T20:24:00.000Z",
            "database": "connected"
        }
        
        Response (503 Service Unavailable):
        {
            "detail": "Service unhealthy - database connection failed"
        }
    
    Notes:
        - Este endpoint NO requiere autenticación para facilitar monitoreo externo
        - Se ejecuta una consulta simple (SELECT 1) para verificar conectividad
        - Errores se registran en logs pero no exponen detalles internos
        - Responde rápidamente para evitar timeouts en health checks
        - Código 503 indica que el servicio no puede recibir tráfico
    """
    try:
        # Probar conectividad con base de datos ejecutando consulta simple
        db.execute("SELECT 1")
        
        return {
            "status": "healthy",
            "service": "auth-service",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "database": "connected"
        }
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service unhealthy - database connection failed"
        )


@router.get("/stats/summary", response_model=dict)
def get_auth_stats_summary(
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Obtener resumen de estadísticas del servicio de autenticación.
    
    Este endpoint proporciona un dashboard completo de métricas del servicio de
    autenticación, incluyendo estadísticas de usuarios, actividad reciente y
    configuración de seguridad. Solo accesible para administradores.
    
    Métricas incluidas:
        - **Estadísticas de usuarios**: Total, activos, inactivos, admins
        - **Actividad reciente**: Registros y logins en últimas 24 horas
        - **Configuración de seguridad**: Requisitos de contraseña y políticas de bloqueo
    
    Casos de uso:
        - Dashboards administrativos
        - Reportes de auditoría
        - Monitoreo de actividad del sistema
        - Análisis de crecimiento de usuarios
        - Verificación de configuración de seguridad
    
    Args:
        admin_user (User): Usuario administrador autenticado (inyectado automáticamente)
        db (Session): Sesión de base de datos (inyectada automáticamente)
    
    Returns:
        dict: Resumen completo de estadísticas incluyendo:
            - service: Nombre del servicio
            - generated_at: Timestamp de generación del reporte
            - user_stats: Estadísticas de usuarios
                - total_users: Total de usuarios registrados
                - active_users: Usuarios con cuenta activa
                - inactive_users: Usuarios desactivados
                - admin_users: Cantidad de administradores
                - regular_users: Cantidad de usuarios regulares
            - activity_stats: Actividad reciente (últimas 24 horas)
                - recent_signups_24h: Nuevos registros
                - recent_logins_24h: Inicios de sesión
            - security_info: Configuración de seguridad
                - password_requirements: Requisitos de contraseña
                - lockout_policy: Política de bloqueo de cuenta
    
    Raises:
        HTTPException 403: Usuario no es administrador
        HTTPException 500: Error al generar estadísticas
    
    Example:
        GET /auth/stats/summary
        Headers: Authorization: Bearer <admin_access_token>
        
        Response:
        {
            "service": "auth-service",
            "generated_at": "2025-11-02T20:24:00.000Z",
            "user_stats": {
                "total_users": 150,
                "active_users": 145,
                "inactive_users": 5,
                "admin_users": 3,
                "regular_users": 147
            },
            "activity_stats": {
                "recent_signups_24h": 8,
                "recent_logins_24h": 67
            },
            "security_info": {
                "password_requirements": {
                    "min_length": 8,
                    "requires_uppercase": true,
                    "requires_lowercase": true,
                    "requires_digit": true,
                    "requires_special_char": true
                },
                "lockout_policy": {
                    "max_attempts": 5,
                    "lockout_duration_minutes": 15
                }
            }
        }
    
    Notes:
        - Los cálculos se realizan en tiempo real desde la base de datos
        - Las estadísticas de actividad cubren las últimas 24 horas
        - Los requisitos de seguridad provienen de la configuración de AuthService
        - Útil para monitoreo continuo y reportes periódicos
        - No incluye información sensible de usuarios individuales
    """
    try:
        from sqlalchemy import func
        from datetime import timedelta
        
        # Estadísticas de usuarios
        total_users = db.query(User).count()
        active_users = db.query(User).filter(User.is_active == True).count()
        
        # Contar administradores por nombre de rol
        admin_role = db.query(Role).filter(Role.name == "admin").first()
        admin_users = 0
        if admin_role:
            admin_users = db.query(User).filter(User.role_id == admin_role.id).count()
        
        # Actividad reciente (últimas 24 horas)
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)
        recent_signups = db.query(User).filter(User.created_at > cutoff_time).count()
        recent_logins = db.query(User).filter(User.last_login > cutoff_time).count()
        
        return {
            "service": "auth-service",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "user_stats": {
                "total_users": total_users,
                "active_users": active_users,
                "inactive_users": total_users - active_users,
                "admin_users": admin_users,
                "regular_users": total_users - admin_users
            },
            "activity_stats": {
                "recent_signups_24h": recent_signups,
                "recent_logins_24h": recent_logins
            },
            "security_info": {
                "password_requirements": {
                    "min_length": AuthService.PASSWORD_MIN_LENGTH,
                    "requires_uppercase": True,
                    "requires_lowercase": True,
                    "requires_digit": True,
                    "requires_special_char": True
                },
                "lockout_policy": {
                    "max_attempts": AuthService.MAX_LOGIN_ATTEMPTS,
                    "lockout_duration_minutes": AuthService.LOCKOUT_DURATION.seconds // 60
                }
            }
        }
    except Exception as e:
        logger.exception(f"Error getting auth stats summary: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno del servidor"
        )