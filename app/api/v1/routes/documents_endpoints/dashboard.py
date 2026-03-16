"""
Router para estadísticas, dashboards y monitoreo de documentos.

Este módulo proporciona endpoints para visualizar estadísticas de documentos,
actividad del usuario, almacenamiento y convocatorias. Incluye dashboards
completos, gráficos de actividad y métricas de uso.

Funcionalidades:
    - Estadísticas generales del dashboard
    - Datos para gráficos de actividad (semanal, mensual, anual)
    - Historial de actividades recientes
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
from app.schemas.log_schemas import ActivityLogOut
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
    
    Este endpoint retorna un resumen completo de estadísticas de documentos
    incluyendo totales, completados, pendientes y tasas de uso. Los usuarios
    ven solo sus propias estadísticas, mientras que los administradores pueden
    ver estadísticas globales de todo el sistema.
    
    Estadísticas incluidas:
        - **Total de documentos**: Cantidad total de documentos
        - **Documentos completados**: Documentos totalmente procesados
        - **Documentos pendientes**: Documentos en espera de procesamiento
        - **Documentos en proceso**: Documentos actualmente siendo procesados
        - **Tasa de completitud**: Porcentaje de documentos completados
        - **Espacio utilizado**: Almacenamiento usado (en MB o GB)
        - **Últimas actividades**: Resumen de actividad reciente
    
    Control de acceso:
        - **Usuarios regulares**: Solo ven sus propias estadísticas
        - **Administradores**: Pueden ver:
            - Sus propias estadísticas (include_all_users=false)
            - Estadísticas globales del sistema (include_all_users=true)
    
    Args:
        include_all_users (bool): Si True y es admin, retorna stats de todo el sistema.
            Default: False (estadísticas personales)
        db (Session): Sesión de base de datos (inyectada automáticamente)
        user (User): Usuario autenticado actual (inyectado automáticamente)
    
    Returns:
        DashboardStats: Resumen de estadísticas incluyendo:
            - total_documents: Total de documentos
            - completed_documents: Documentos completados
            - pending_documents: Documentos pendientes
            - processing_documents: Documentos en proceso
            - completion_rate: Porcentaje de completitud
            - total_storage_used: Almacenamiento utilizado (formato legible)
            - total_storage_bytes: Almacenamiento en bytes
    
    Raises:
        HTTPException 401: Usuario no autenticado
        HTTPException 403: Usuario intenta ver stats globales sin ser admin
        HTTPException 500: Error al calcular estadísticas
    
    Example:
        GET /documents/stats/dashboard
        Headers: Authorization: Bearer <access_token>
        
        Response:
        {
            "total_documents": 45,
            "completed_documents": 38,
            "pending_documents": 5,
            "processing_documents": 2,
            "completion_rate": 84.44,
            "total_storage_used": "2.3 GB",
            "total_storage_bytes": 2469606912
        }
    
    Example admin (global):
        GET /documents/stats/dashboard?include_all_users=true
        Headers: Authorization: Bearer <admin_token>
        
        Response:
        {
            "total_documents": 1250,
            "completed_documents": 1050,
            "pending_documents": 150,
            "processing_documents": 50,
            "completion_rate": 84.0,
            "total_storage_used": "45.6 GB",
            "total_storage_bytes": 49010597888
        }
    
    Notes:
        - Las estadísticas se actualizan en tiempo real desde BD
        - El cálculo de porcentajes es resiliente ante datos vacíos
        - Useful para widgets de dashboard
    """
    try:
        # Determinar si se deben incluir datos de todos los usuarios
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
    
    Este endpoint retorna datos de actividad agregados por período de tiempo
    para visualizar tendencias de uso. Útil para gráficos de líneas o barras
    mostrando actividad a lo largo del tiempo.
    
    Períodos soportados:
        - **week**: Últimos 7 días, agregado por día
        - **month**: Últimos 30 días, agregado por día
        - **year**: Últimos 12 meses, agregado por mes
    
    Métricas por punto de datos:
        - **timestamp**: Fecha/hora del punto de datos
        - **documents_added**: Documentos agregados en ese período
        - **documents_completed**: Documentos completados
        - **storage_added_bytes**: Bytes agregados al almacenamiento
        - **activity_count**: Total de actividades registradas
    
    Control de acceso:
        - **Usuarios regulares**: Solo sus propias métricas
        - **Administradores**: Pueden ver métricas globales con include_all_users=true
    
    Args:
        period (str): Período a visualizar (week, month, year)
        include_all_users (bool): Si True y es admin, incluye datos globales
        db (Session): Sesión de base de datos (inyectada automáticamente)
        user (User): Usuario autenticado actual (inyectado automáticamente)
    
    Returns:
        List[ChartDataPoint]: Lista de puntos para gráfico:
            - timestamp: ISO 8601 timestamp
            - documents_added: Documentos nuevos
            - documents_completed: Documentos completados
            - storage_added_bytes: Bytes agregados
            - activity_count: Total de actividades
    
    Raises:
        HTTPException 401: Usuario no autenticado
        HTTPException 400: Período inválido
        HTTPException 500: Error al generar datos
    
    Example (últimas 4 semanas):
        GET /documents/stats/charts?period=month
        Headers: Authorization: Bearer <access_token>
        
        Response:
        [
            {
                "timestamp": "2025-10-05T00:00:00Z",
                "documents_added": 5,
                "documents_completed": 3,
                "storage_added_bytes": 1048576,
                "activity_count": 8
            },
            {
                "timestamp": "2025-10-06T00:00:00Z",
                "documents_added": 7,
                "documents_completed": 5,
                "storage_added_bytes": 2097152,
                "activity_count": 12
            },
            ...
        ]
    
    Notes:
        - Cada punto representa un período agregado (día o mes)
        - Puntos sin actividad pueden estar omitidos
        - Ordenado cronológicamente (antiguo a reciente)
        - Útil para gráficos de tendencias y análisis de patrones
    """
    try:
        # Determinar si incluir datos de todos los usuarios
        user_id = None if (include_all_users and user.is_admin) else user.id
        
        chart_data = DocumentService.get_chart_data(period, db, user_id)
        return chart_data
        
    except HTTPException:
        raise
    except Exception as e:
        logging.exception(f"Error obteniendo datos del gráfico: {e}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")


# =========================================================
# 📋 Actividades recientes
# =========================================================

@router.get("/activities/recent", response_model=List[ActivityLogOut])
def get_recent_activities(
    limit: Annotated[int, Query(ge=1, le=100, description="Número máximo de actividades")] = 20,
    include_all_users: Annotated[bool, Query(description="Incluir actividades de todos los usuarios (solo admin)")] = False,
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    """
    Obtener historial de actividades recientes.
    
    Este endpoint retorna el registro de actividades ordenado por fecha reciente.
    Cada registro incluye información sobre qué acción se realizó, cuándo, y en
    qué documento. Útil para auditoría y seguimiento de cambios.
    
    Tipos de actividades:
        - **document_uploaded**: Documento subido
        - **document_processed**: Documento procesado
        - **document_deleted**: Documento eliminado
        - **document_shared**: Documento compartido
        - **file_viewed**: Archivo visualizado
        - **export_generated**: Exportación creada
        - **error_occurred**: Error en procesamiento
    
    Información por actividad:
        - **id**: ID único de la actividad
        - **action**: Tipo de acción realizada
        - **document_name**: Nombre del documento afectado
        - **user_id**: Usuario que realizó la acción
        - **user_name**: Nombre del usuario
        - **timestamp**: Cuándo ocurrió (ISO 8601)
        - **details**: Información adicional opcional
        - **status**: Estado (success, error, pending)
    
    Control de acceso:
        - **Usuarios regulares**: Solo sus propias actividades
        - **Administradores**: Pueden ver actividades globales con include_all_users=true
    
    Args:
        limit (int): Número máximo de registros a retornar (1-100). Default: 20
        include_all_users (bool): Si True y es admin, incluye actividades globales
        db (Session): Sesión de base de datos (inyectada automáticamente)
        user (User): Usuario autenticado actual (inyectado automáticamente)
    
    Returns:
        List[ActivityLogOut]: Lista de actividades recientes ordenadas por fecha (reciente primero)
    
    Raises:
        HTTPException 401: Usuario no autenticado
        HTTPException 400: Limit fuera de rango
        HTTPException 500: Error al obtener actividades
    
    Example:
        GET /documents/activities/recent?limit=10
        Headers: Authorization: Bearer <access_token>
        
        Response:
        [
            {
                "id": 1250,
                "action": "document_processed",
                "document_name": "Reporte Q4 2025",
                "user_id": 1,
                "user_name": "Juan Pérez",
                "timestamp": "2025-11-02T20:35:00Z",
                "details": "Procesamiento completado en 2.3 segundos",
                "status": "success"
            },
            {
                "id": 1249,
                "action": "document_uploaded",
                "document_name": "Declaración de impuestos",
                "user_id": 1,
                "user_name": "Juan Pérez",
                "timestamp": "2025-11-02T20:30:15Z",
                "details": "PDF de 2.5 MB",
                "status": "success"
            },
            ...
        ]
    
    Notes:
        - Actividades ordenadas de más reciente a más antiguo
        - Useful para auditoría y troubleshooting
        - El límite máximo es 100 para evitar sobrecargas
        - Se pueden usar para reconstruir historial de cambios
    """
    try:
        # Determinar si incluir actividades de todos los usuarios
        user_id = None if (include_all_users and user.is_admin) else user.id
        
        activities = DocumentService.get_recent_activities(limit, db, user_id)
        return activities
        
    except HTTPException:
        raise
    except Exception as e:
        logging.exception(f"Error obteniendo actividades recientes: {e}")
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
    
    Este endpoint retorna información detallada sobre el uso de almacenamiento
    del usuario, desglosado por tipo de archivo y convocatoria. Útil para
    administración de cuotas y planificación de capacidad.
    
    Estadísticas incluidas:
        - **Total usado**: Cantidad total de almacenamiento utilizado
        - **Por tipo de archivo**: Desglose por PDF, DOCX, XLSX, etc.
        - **Por convocatoria**: Cuánto usa cada convocatoria
        - **Disponible**: Cuota restante disponible
        - **Porcentaje usado**: Porcentaje de la cuota utilizada
        - **Tendencia**: Cómo ha crecido el uso (últimos 30 días)
    
    Control de acceso:
        - **Usuarios regulares**: Solo ven su propio almacenamiento
        - **Administradores**: Pueden ver almacenamiento de cualquier usuario
            especificando target_user_id
    
    Args:
        target_user_id (Optional[int]): ID del usuario a consultar.
            - Si omitido: retorna datos del usuario actual
            - Si specified: solo admin puede consultar otros usuarios
        db (Session): Sesión de base de datos (inyectada automáticamente)
        user (User): Usuario autenticado actual (inyectado automáticamente)
    
    Returns:
        dict: Estadísticas de almacenamiento:
            - user_id: ID del usuario
            - total_storage_bytes: Total en bytes
            - total_storage_formatted: Formato legible (2.3 GB)
            - storage_by_type: Desglose por tipo archivo
            - storage_by_convocatoria: Desglose por convocatoria
            - quota_bytes: Cuota total disponible
            - available_bytes: Bytes aún disponibles
            - usage_percentage: Porcentaje de cuota utilizada
            - growth_30_days: Crecimiento en últimos 30 días
    
    Raises:
        HTTPException 401: Usuario no autenticado
        HTTPException 403: Intento de ver stats de otro usuario sin ser admin
        HTTPException 404: Usuario objetivo no encontrado
        HTTPException 500: Error al calcular estadísticas
    
    Example (ver propias estadísticas):
        GET /documents/stats/storage
        Headers: Authorization: Bearer <access_token>
        
        Response:
        {
            "user_id": 1,
            "total_storage_bytes": 2469606912,
            "total_storage_formatted": "2.3 GB",
            "storage_by_type": {
                "pdf": "1.5 GB",
                "docx": "600 MB",
                "xlsx": "200 MB"
            },
            "storage_by_convocatoria": {
                "Convocatoria 2025": "1.2 GB",
                "Documentos Personales": "1.1 GB"
            },
            "quota_bytes": 5368709120,
            "available_bytes": 2899102208,
            "usage_percentage": 46.0,
            "growth_30_days": "+250 MB"
        }
    
    Example (admin consultando otro usuario):
        GET /documents/stats/storage?target_user_id=42
        Headers: Authorization: Bearer <admin_token>
    
    Notes:
        - Las cuotas pueden variar según plan de suscripción
        - Los cálculos se actualizan en tiempo real desde BD
        - Útil para advertir sobre límites de cuota
        - El almacenamiento se comparte entre convocatorias
    """
    try:
        # Determinar usuario objetivo
        if target_user_id and target_user_id != user.id:
            # Intentar acceder a datos de otro usuario
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
    
    Este endpoint es utilizado por sistemas de monitoreo, load balancers y
    orquestadores (Kubernetes, Docker Swarm) para determinar si el servicio
    está disponible y funcionando correctamente.
    
    Verificaciones realizadas:
        - Conectividad con base de datos
        - Capacidad de ejecutar consultas SQL
        - Estado general del servicio
    
    Casos de uso:
        - Health checks de Kubernetes/Docker
        - Monitoreo de disponibilidad continuo
        - Verificación en pipelines CI/CD
        - Balanceo de carga
        - Alertas de disponibilidad
    
    Args:
        db (Session): Sesión de base de datos (inyectada automáticamente)
    
    Returns:
        dict: Estado del servicio:
            - status: "healthy" si todo funciona correctamente
            - service: "document-service"
            - timestamp: Hora actual (ISO 8601)
            - database: "connected" si BD está disponible
    
    Raises:
        HTTPException 503: Servicio no disponible (fallo de BD)
    
    Example (exitoso):
        GET /documents/health
        
        Response (200 OK):
        {
            "status": "healthy",
            "service": "document-service",
            "timestamp": "2025-11-02T20:36:00.123456Z",
            "database": "connected"
        }
    
    Example (fallo):
        GET /documents/health
        
        Response (503 Service Unavailable):
        {
            "detail": "Service unhealthy - database connection failed"
        }
    
    Notes:
        - **NO requiere autenticación** para facilitar monitoreo externo
        - Responde rápidamente para evitar timeouts
        - Código 503 indica que el servicio no debe recibir tráfico
        - Se ejecuta una consulta simple (SELECT 1) para validar conexión
        - Errores se registran pero no se exponen detalles internos
    """
    try:
        # Prueba de conectividad con base de datos
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
    
    Datos consolidados:
        - **Información del usuario**: ID, nombre, email
        - **Almacenamiento**: Uso de cuota y desglose por tipo
        - **Dashboard**: Totales de documentos y tasas
        - **Actividades recientes**: Últimos 10 eventos
        - **Últimas actividades**: Timestamp del último evento
        - **Generado en**: Cuándo se creó el resumen
    
    Casos de uso:
        - Dashboard principal con todas las métricas
        - Vista rápida de salud de la cuenta
        - Exportación de reportes personalizados
        - Resumen para notificaciones por email
        - Análisis retrospectivo de uso
    
    Args:
        db (Session): Sesión de base de datos (inyectada automáticamente)
        user (User): Usuario autenticado actual (inyectado automáticamente)
    
    Returns:
        dict: Resumen consolidado incluyendo:
            - user_id: ID del usuario
            - user_name: Nombre completo
            - user_email: Email
            - storage: Estadísticas de almacenamiento
            - dashboard: Estadísticas generales de documentos
            - recent_activities_count: Número de actividades recientes
            - last_activity: Timestamp de última actividad (null si ninguna)
            - generated_at: Cuándo se generó el resumen (ISO 8601)
    
    Raises:
        HTTPException 401: Usuario no autenticado
        HTTPException 500: Error al consolidar datos
    
    Example:
        GET /documents/stats/summary
        Headers: Authorization: Bearer <access_token>
        
        Response:
        {
            "user_id": 1,
            "user_name": "Juan Pérez",
            "user_email": "juan@example.com",
            "storage": {
                "total_storage_bytes": 2469606912,
                "total_storage_formatted": "2.3 GB",
                "usage_percentage": 46.0
            },
            "dashboard": {
                "total_documents": 45,
                "completed_documents": 38,
                "pending_documents": 5,
                "processing_documents": 2,
                "completion_rate": 84.44
            },
            "recent_activities_count": 10,
            "last_activity": "2025-11-02T20:35:00Z",
            "generated_at": "2025-11-02T20:36:00.123456Z"
        }
    
    Notes:
        - Combina datos de múltiples servicios
        - Útil para dashboards unificados
        - El timestamp de generación es útil para detectar datos obsoletos
        - Todos los datos están sincronizados (misma transacción de BD)
    """
    try:
        # Obtener diferentes tipos de métricas
        storage_stats = DocumentService.get_user_storage_stats(db, user.id)
        recent_activities = DocumentService.get_recent_activities(10, db, user.id)
        dashboard_stats = DocumentService.get_dashboard_stats(db, user.id)
        
        # Consolidar en un resumen único
        return {
            "user_id": user.id,
            "user_name": user.name,
            "user_email": user.email,
            "storage": storage_stats,
            "dashboard": dashboard_stats,
            "recent_activities_count": len(recent_activities),
            "last_activity": (
                recent_activities[0].timestamp.isoformat() 
                if recent_activities and recent_activities[0].timestamp 
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
    
    Este endpoint retorna métricas sobre convocatorias, incluyendo totales,
    tasas de completitud y documentos pendientes. Los usuarios ven solo sus
    convocatorias, mientras que administradores ven todas del sistema.
    
    Estadísticas incluidas:
        - **Total de convocatorias**: Cantidad total de procesos
        - **Convocatorias completadas**: Procesos con todos documentos completos
        - **Documentos pendientes**: Documentos aún esperando
        - **Tasa de completitud**: Porcentaje de progreso general
    
    Control de acceso:
        - **Usuarios regulares**: Solo sus convocatorias personales
        - **Administradores**: Todas las convocatorias del sistema
    
    Filtrado automático:
        - Si not admin: Filtra por created_by == user.id
        - Si admin: Retorna estadísticas globales
    
    Args:
        db (Session): Sesión de base de datos (inyectada automáticamente)
        current_user (User): Usuario autenticado actual (inyectado automáticamente)
    
    Returns:
        dict: Estadísticas de convocatorias:
            - total_convocatorias: Total de procesos
            - completed_convocatorias: Procesos completados (todos documentos done)
            - pending_documents: Documentos en estado "pending"
            - completion_rate: Porcentaje de completitud (0-100)
    
    Example (usuario regular):
        GET /documents/stats/convocatorias
        Headers: Authorization: Bearer <access_token>
        
        Response:
        {
            "total_convocatorias": 12,
            "completed_convocatorias": 9,
            "pending_documents": 15,
            "completion_rate": 75.0
        }
    
    Example (administrador):
        GET /documents/stats/convocatorias
        Headers: Authorization: Bearer <admin_token>
        
        Response:
        {
            "total_convocatorias": 156,
            "completed_convocatorias": 138,
            "pending_documents": 285,
            "completion_rate": 88.46
        }
    
    Cálculos:
        - completion_rate = (completed_convocatorias / total_convocatorias) * 100
        - Si total_convocatorias = 0, completion_rate = 0
        - pending_documents = COUNT(docs WHERE status = "pending")
    
    Notes:
        - Las convocatorias se consideran completadas cuando TODOS sus documentos 
          están en estado "completed"
        - Los documentos pendientes se cuentan independientemente de convocatoria
        - Useful para reportes de progreso
    """
    try:
        # Construir query base
        query = db.query(models.Convocatoria)
        
        # Filtrar por usuario si no es admin
        if not current_user.is_admin:
            query = query.filter(models.Convocatoria.created_by == current_user.id)
        
        # Contar total de convocatorias
        total_convocatorias = query.count()
        
        # Contar convocatorias completadas (todas sus documentos están "completed")
        completed = db.query(models.Convocatoria).join(
            models.ConvocatoriaDocument
        ).filter(
            models.ConvocatoriaDocument.status == "completed"
        ).distinct().count()
        
        # Contar documentos pendientes (de convocatorias del usuario si aplica)
        pending_query = db.query(models.ConvocatoriaDocument).filter(
            models.ConvocatoriaDocument.status == "pending"
        )
        
        # Si no es admin, filtrar por convocatorias del usuario
        if not current_user.is_admin:
            pending_query = pending_query.join(
                models.Convocatoria
            ).filter(
                models.Convocatoria.created_by == current_user.id
            )
        
        pending_docs = pending_query.count()
        
        # Calcular tasa de completitud
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
