"""
Programador de tareas en segundo plano.
app/core/scheduler.py

- Resumen semanal: lunes a las 08:00 (hora del servidor), ventana de 1 hora.
- Mantenimiento: limpieza de sesiones expiradas cada 15 minutos.

El trabajo (BD, generación de reportes, envío de emails) es síncrono, así
que se ejecuta con asyncio.to_thread para no bloquear el event loop.

Varios procesos (más de un worker, o dos contenedores durante un redeploy)
pueden ejecutar este scheduler a la vez. El resumen semanal se protege con
un lock con nombre de MySQL (GET_LOCK): solo el proceso que lo obtiene envía.
"""

import asyncio
import logging
import os
from datetime import datetime, time

from sqlalchemy import text

from app.db.database import SessionLocal, engine
from app.services.email_service import EmailService
from app.services.notification_service import NotificationService
from app.services.weekly_summary_service import WeeklySummaryService
from app.core.config import settings

logger = logging.getLogger(__name__)

# Configuración del envío: Lunes a las 08:00 AM
SCHEDULED_DAY = 0 # 0 = Lunes
SCHEDULED_TIME = time(8, 0) # 08:00 AM

WEEKLY_SUMMARY_LOCK = "curim_weekly_summary"


def run_with_lock(lock_name: str, job) -> bool:
    """
    Ejecuta job() solo si este proceso obtiene el lock con nombre de MySQL.

    GET_LOCK es por conexión: se mantiene la conexión abierta mientras dura
    el trabajo. Timeout 0 → si otro proceso lo tiene, no espera y devuelve
    False. MySQL lo libera solo si la conexión se cae.
    """
    with engine.connect() as conn:
        acquired = conn.execute(text("SELECT GET_LOCK(:name, 0)"), {"name": lock_name}).scalar()
        if acquired != 1:
            logger.info(f"Lock '{lock_name}' en uso por otro proceso; se omite la ejecución.")
            return False
        try:
            job()
            return True
        finally:
            conn.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name})


def _weekly_job(weekly_service: WeeklySummaryService) -> None:
    from app.services.session_service import SessionService
    from app.services.auth_service import AuthService

    db = SessionLocal()
    try:
        weekly_service.process_all_summaries(db)

        # Limpieza de sesiones y tokens (Aprovechamos el trigger semanal o forzado)
        session_count = SessionService.cleanup_expired_sessions(db)
        AuthService._cleanup_expired_tokens(db)
        logger.info(f"Limpieza completada: {session_count} sesiones eliminadas.")
    finally:
        db.close()


def _maintenance_job() -> None:
    from app.services.session_service import SessionService

    db = SessionLocal()
    try:
        SessionService.cleanup_expired_sessions(db)
    finally:
        db.close()


async def start_weekly_summary_scheduler():
    """
    Tarea en segundo plano que verifica periódicamente si es momento de enviar los resúmenes.
    """
    logger.info("Scheduler de Resumen Semanal iniciado.")

    # Inicializar servicios
    email_service = EmailService(
        api_key=settings.RESEND_API_KEY,
        from_email=settings.FROM_EMAIL
    )
    notification_service = NotificationService(email_service)
    weekly_service = WeeklySummaryService(notification_service)

    while True:
        try:
            now = datetime.now()

            # Verificar si debemos forzar el envío por variable de entorno (para pruebas)
            force_send = os.getenv("FORCE_WEEKLY_SUMMARY", "false").lower() == "true"

            # Lógica semanal: Es Lunes y estamos en la hora programada (ventana de 1 hora)
            is_scheduled_time = (
                now.weekday() == SCHEDULED_DAY and
                now.time().hour == SCHEDULED_TIME.hour
            )

            if is_scheduled_time or force_send:
                logger.info("Trigger de resumen semanal activado.")

                await asyncio.to_thread(
                    run_with_lock, WEEKLY_SUMMARY_LOCK, lambda: _weekly_job(weekly_service)
                )

                # Si fue forzado, desactivar para evitar bucle
                if force_send:
                    os.environ["FORCE_WEEKLY_SUMMARY"] = "false"

                # Esperar una hora para no enviar múltiples veces en la misma ventana
                await asyncio.sleep(3600)
            else:
                # Tarea de mantenimiento rápida cada vez que despertamos (15 min)
                await asyncio.to_thread(_maintenance_job)

                # Esperar 15 minutos antes de la siguiente verificación
                await asyncio.sleep(900)

        except Exception as e:
            logger.error(f"Error en el ciclo del scheduler: {e}")
            await asyncio.sleep(60) # Esperar un minuto antes de reintentar tras error
