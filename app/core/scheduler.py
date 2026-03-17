"""
Programador de tareas en segundo plano.
app/core/scheduler.py
"""

import asyncio
import logging
from datetime import datetime, time, timedelta
import os

from app.db.database import SessionLocal
from app.services.email_service import EmailService
from app.services.notification_service import NotificationService
from app.services.weekly_summary_service import WeeklySummaryService
from app.core.config import settings

logger = logging.getLogger(__name__)

# Configuración del envío: Lunes a las 08:00 AM
SCHEDULED_DAY = 0 # 0 = Lunes
SCHEDULED_TIME = time(8, 0) # 08:00 AM

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
                
                # Usar una nueva sesión de base de datos
                db = SessionLocal()
                try:
                    weekly_service.process_all_summaries(db)
                finally:
                    db.close()
                
                # Si fue forzado, desactivar para evitar bucle
                if force_send:
                    os.environ["FORCE_WEEKLY_SUMMARY"] = "false"
                
                # Esperar una hora para no enviar múltiples veces en la misma ventana
                await asyncio.sleep(3600)
            else:
                # Esperar 15 minutos antes de la siguiente verificación
                await asyncio.sleep(900)
                
        except Exception as e:
            logger.error(f"Error en el ciclo del scheduler: {e}")
            await asyncio.sleep(60) # Esperar un minuto antes de reintentar tras error
