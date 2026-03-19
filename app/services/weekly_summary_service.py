"""
Servicio para coordinar el proceso de resumen semanal.
app/services/weekly_summary_service.py
"""

import logging
from typing import List
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from app.models.models import User, UserPreferences
from app.services.document_service import DocumentService
from app.services.report_service import ReportService
from app.services.notification_service import NotificationService
from app.enums.enums import NotificationType

logger = logging.getLogger(__name__)

class WeeklySummaryService:
    def __init__(self, notification_service: NotificationService):
        self.notification_service = notification_service

    def process_all_summaries(self, db: Session):
        """
        Procesa el resumen semanal para todos los usuarios que lo tengan habilitado.
        """
        logger.info("Iniciando proceso de resumen semanal...")
        
        # 1. Obtener usuarios con resumen semanal habilitado
        users_with_summary = (
            db.query(User)
            .join(UserPreferences)
            .filter(UserPreferences.weekly_summary == True)
            .all()
        )
        
        logger.info(f"Se encontraron {len(users_with_summary)} usuarios para procesar.")
        
        for user in users_with_summary:
            try:
                self.process_user_summary(db, user)
            except Exception as e:
                logger.error(f"Error procesando resumen para usuario {user.id} ({user.email}): {e}")

    def process_user_summary(self, db: Session, user: User):
        """
        Genera y envía el resumen para un usuario específico.
        """
        # 2. Obtener estadísticas del dashboard para el usuario
        stats = DocumentService.get_dashboard_stats(db, user_id=user.id)
        
        # 3. Determinar formato preferido (PDF por defecto)
        prefs = user.preferences
        format_choice = getattr(prefs, 'weekly_summary_format', 'pdf').lower()
        
        # 4. Generar el archivo según preferencia
        attachment = None
        if format_choice == 'excel':
            content = ReportService.generate_excel_report(user.name, stats.dict())
            attachment = {
                "filename": f"Resumen_Semanal_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                "content": content
            }
        else:
            content = ReportService.generate_pdf_report(user.name, stats.dict())
            attachment = {
                "filename": f"Resumen_Semanal_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                "content": content
            }
            
        # 5. Enviar la notificación
        data = {
            "summary_data": {
                "documents_uploaded": stats.documentsThisWeek,
                "ai_interactions": 0, # TODO: Implementar conteo de interacciones si existe en BD
            },
            "attachment": attachment
        }
        
        self.notification_service.send_notification(
            db, 
            user.id, 
            NotificationType.WEEKLY_SUMMARY, 
            data
        )
        
        logger.info(f"Resumen semanal enviado exitosamente a {user.email} en formato {format_choice}.")
