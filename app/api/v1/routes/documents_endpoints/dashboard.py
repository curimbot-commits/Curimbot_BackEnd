"""
Router para estadísticas, dashboards y monitoreo de documentos.

Este módulo proporciona endpoints para visualizar estadísticas de documentos,
actividad del usuario, almacenamiento y convocatorias. Incluye dashboards
completos, gráficos de actividad y métricas de uso.

Funcionalidades:
    - Estadísticas generales del dashboard
    - Datos para gráficos de actividad (semanal, mensual, anual)
    - Historial de interacciones recientes con la IA
    - Estadísticas de almacenamiento por usuario
    - Health checks para monitoreo
    - Resumen completo de métricas
    - Estadísticas de convocatorias

Acceso:
    - Usuarios ven solo sus propias estadísticas
    - Administradores pueden ver estadísticas globales u de otros usuarios
"""

import datetime
import logging
from typing import List, Optional, Annotated
from fastapi import APIRouter, Depends, HTTPException
from fastapi.params import Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.schemas.dashboard_schemas import ChartDataPoint, DashboardStats
from app.schemas.log_schemas import AIInteractionLogOut
from app.services.auth_service import get_current_user
from app.db.database import get_db
from app.enums.enums import FileType
from app.models import models
from app.services.document_service import DocumentService

router = APIRouter(prefix="/documents", tags=["documents"])


# =========================================================
# 📊 Dashboard - Estadísticas generales
# =========================================================

@router.get("/stats/dashboard", response_model=DashboardStats)
def get_dashboard_stats(
    include_all_users: Annotated[bool, Query(description="Incluir stats de todos los usuarios (solo admin)")] = False,
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    """
    Obtener estadísticas generales para el dashboard.
    """
    try:
        user_id = None if (include_all_users and user.is_admin) else user.id
        stats = DocumentService.get_dashboard_stats(db, user_id)
        return stats

    except HTTPException:
        raise
    except Exception as e:
        logging.exception(f"Error obteniendo estadísticas del dashboard: {e}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")


# =========================================================
# 📈 Datos para gráficos
# =========================================================

@router.get("/stats/charts", response_model=List[ChartDataPoint])
def get_chart_data(
    period: Annotated[str, Query(regex="^(week|month|year)$", description="Período para el gráfico")] = "month",
    include_all_users: Annotated[bool, Query(description="Incluir datos de todos los usuarios (solo admin)")] = False,
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    """
    Obtener datos de actividad para gráficos de tendencias.
    """
    try:
        user_id = None if (include_all_users and user.is_admin) else user.id
        chart_data = DocumentService.get_chart_data(period, db, user_id)
        return chart_data

    except HTTPException:
        raise
    except Exception as e:
        logging.exception(f"Error obteniendo datos del gráfico: {e}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")


# =========================================================
# 📋 Interacciones recientes con la IA
# =========================================================

@router.get("/ai-interactions/recent", response_model=List[AIInteractionLogOut])
def get_recent_ai_interactions(
    limit: Annotated[int, Query(ge=1, le=100, description="Número máximo de interacciones")] = 20,
    channel: Annotated[Optional[str], Query(description="Filtrar por canal: text | voice")] = None,
    status: Annotated[Optional[str], Query(description="Filtrar por estado: success | error | no_context")] = None,
    include_all_users: Annotated[bool, Query(description="Incluir interacciones de todos los usuarios (solo admin)")] = False,
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    """
    Obtener historial de interacciones recientes con la IA.

    Retorna las últimas preguntas/respuestas del usuario con la IA Curim,
    incluyendo canal (texto/voz), confianza, fuentes usadas y estado.

    Control de acceso:
        - Usuarios regulares: solo sus propias interacciones
        - Administradores: pueden ver todas con include_all_users=true

    Args:
        limit: Número máximo de registros (1-100). Default: 20
        channel: Filtrar por canal ('text' | 'voice'). Opcional.
        status: Filtrar por estado ('success' | 'error' | 'no_context'). Opcional.
        include_all_users: Si True y es admin, incluye interacciones globales.
        db: Sesión de base de datos (inyectada automáticamente).
        user: Usuario autenticado actual (inyectado automáticamente).

    Returns:
        List[AIInteractionLogOut]: Lista de interacciones recientes ordenadas
        por fecha (más reciente primero).

    Example:
        GET /documents/ai-interactions/recent?limit=10&channel=text
    """
    try:
        user_id = None if (include_all_users and user.is_admin) else user.id

        interactions = DocumentService.get_recent_ai_interactions(
            limit=limit,
            db=db,
            user_id=user_id,
            channel=channel,
            status=status,
        )
        return interactions

    except HTTPException:
        raise
    except Exception as e:
        logging.exception(f"Error obteniendo interacciones IA recientes: {e}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")


# =========================================================
# 💾 Estadísticas de almacenamiento por usuario
# =========================================================

@router.get("/stats/storage", response_model=dict)
def get_user_storage_stats(
    target_user_id: Annotated[Optional[int], Query(description="ID del usuario objetivo (solo admin)")] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    """
    Obtener estadísticas detalladas de almacenamiento del usuario.
    """
    try:
        if target_user_id and target_user_id != user.id:
            if not user.is_admin:
                raise HTTPException(
                    status_code=403,
                    detail="No autorizado para ver estadísticas de otros usuarios"
                )
            user_id = target_user_id
        else:
            user_id = user.id

        stats = DocumentService.get_user_storage_stats(db, user_id)
        return stats

    except HTTPException:
        raise
    except Exception as e:
        logging.exception(f"Error obteniendo estadísticas de almacenamiento: {e}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")


# =========================================================
# 🏥 Health check para monitoreo
# =========================================================

@router.get("/health", response_model=dict)
def health_check(db: Session = Depends(get_db)):
    """
    Verificar estado de salud del servicio de documentos.
    """
    try:
        db.execute("SELECT 1")

        return {
            "status": "healthy",
            "service": "document-service",
            "timestamp": datetime.datetime.now().isoformat(),
            "database": "connected"
        }

    except Exception as e:
        logging.error(f"Health check failed: {e}")
        raise HTTPException(
            status_code=503,
            detail="Service unhealthy - database connection failed"
        )


# =========================================================
# 📊 Resumen de métricas del usuario
# =========================================================

@router.get("/stats/summary", response_model=dict)
def get_user_summary(
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    """
    Obtener resumen completo y consolidado de todas las métricas del usuario.

    Este endpoint combina múltiples tipos de estadísticas en una sola respuesta
    para dashboards completos. Incluye almacenamiento, actividad general y
    documentos, proporcionando una vista integral de la cuenta del usuario.
    """
    try:
        storage_stats = DocumentService.get_user_storage_stats(db, user.id)
        recent_interactions = DocumentService.get_recent_ai_interactions(10, db, user.id)
        dashboard_stats = DocumentService.get_dashboard_stats(db, user.id)

        return {
            "user_id": user.id,
            "user_name": user.name,
            "user_email": user.email,
            "storage": storage_stats,
            "dashboard": dashboard_stats,
            "recent_interactions_count": len(recent_interactions),
            "last_interaction": (
                recent_interactions[0].timestamp.isoformat()
                if recent_interactions and recent_interactions[0].timestamp
                else None
            ),
            "generated_at": datetime.datetime.now().isoformat()
        }

    except Exception as e:
        logging.exception(f"Error obteniendo resumen de usuario {user.id}: {e}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")


@router.get("/stats/convocatorias")
def get_convocatoria_stats(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Obtener estadísticas específicas del módulo de convocatorias.
    """
    try:
        query = db.query(models.Convocatoria)

        if not current_user.is_admin:
            query = query.filter(models.Convocatoria.created_by == current_user.id)

        total_convocatorias = query.count()

        completed = db.query(models.Convocatoria).join(
            models.ConvocatoriaDocument
        ).filter(
            models.ConvocatoriaDocument.status == "completed"
        ).distinct().count()

        pending_query = db.query(models.ConvocatoriaDocument).filter(
            models.ConvocatoriaDocument.status == "pending"
        )

        if not current_user.is_admin:
            pending_query = pending_query.join(
                models.Convocatoria
            ).filter(
                models.Convocatoria.created_by == current_user.id
            )

        pending_docs = pending_query.count()

        completion_rate = (
            (completed / total_convocatorias * 100)
            if total_convocatorias > 0
            else 0
        )

        return {
            "total_convocatorias": total_convocatorias,
            "completed_convocatorias": completed,
            "pending_documents": pending_docs,
            "completion_rate": completion_rate
        }

    except Exception as e:
        logging.exception(f"Error obteniendo estadísticas de convocatorias: {e}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")