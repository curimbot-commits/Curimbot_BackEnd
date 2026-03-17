
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from app.models.models import User, UserPreferences, NotificationHistory
from app.enums.enums import NotificationType, NotificationChannel, NotificationStatus
from app.services.email_service import EmailService

logger = logging.getLogger(__name__)

class NotificationService:
    """
    Servicio centralizado para la gestión de notificaciones.
    Se encarga de verificar preferencias y despachar a los canales correspondientes.
    """

    def __init__(self, email_service: EmailService):
        self.email_service = email_service
        # En el futuro se pueden inyectar push_service, in_app_service, etc.

    def send_notification(
        self,
        db: Session,
        user_id: int,
        event_type: NotificationType,
        data: Dict[str, Any]
    ) -> List[NotificationHistory]:
        """
        Envía una notificación al usuario basándose en sus preferencias.

        Args:
            db: Sesión de base de datos
            user_id: ID del usuario destinatario
            event_type: Tipo de evento (LOGIN_ALERT, etc.)
            data: Diccionario con los datos para la plantilla (user_name, etc.)

        Returns:
            Lista de registros de historial creados
        """
        results = []
        
        # 1. Obtener usuario y sus preferencias
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error(f"User {user_id} not found for notification {event_type}")
            return results

        prefs = user.preferences
        if not prefs:
            logger.warning(f"User {user_id} has no preferences. Skipping notification.")
            return results

        # 2. Determinar si el evento debe ser notificado según preferencias
        if not self._should_notify_event(prefs, event_type):
            self._log_history(db, user_id, event_type, NotificationChannel.EMAIL, NotificationStatus.SKIPPED, "Filtered by user preferences")
            return results

        # 3. Determinar canales activos
        channels = self._get_active_channels(prefs)

        # 4. Despachar a cada canal
        for channel in channels:
            status = NotificationStatus.SENT
            error_detail = None

            try:
                if channel == NotificationChannel.EMAIL:
                    if not self._dispatch_email(user, event_type, data):
                        status = NotificationStatus.FAILED
                        error_detail = "Email transport failed"
                
                elif channel == NotificationChannel.PUSH:
                    # TODO: Implementar PushService
                    status = NotificationStatus.SKIPPED
                    error_detail = "PushChannel not implemented yet"
                
                elif channel == NotificationChannel.IN_APP:
                    # TODO: Implementar InAppService
                    status = NotificationStatus.SKIPPED
                    error_detail = "InAppChannel not implemented yet"

            except Exception as e:
                logger.exception(f"Error dispatching notification {event_type} via {channel}: {e}")
                status = NotificationStatus.FAILED
                error_detail = str(e)

            # 5. Registrar en el historial
            history = self._log_history(db, user_id, event_type, channel, status, error_detail)
            results.append(history)

        return results

    def _should_notify_event(self, prefs: UserPreferences, event_type: NotificationType) -> bool:
        """Verifica si el tipo de evento está habilitado en las preferencias generales."""
        mapping = {
            NotificationType.LOGIN_ALERT: prefs.login_alerts,
            NotificationType.SECURITY_ALERT: prefs.security_alerts,
            NotificationType.PASSWORD_CHANGED: prefs.security_alerts,
            NotificationType.PASSWORD_RESET: True, # Siempre permitir reseteo de password
            NotificationType.WEEKLY_SUMMARY: prefs.weekly_summary,
            NotificationType.PROFILE_UPDATED: True # Opcional: añadir preferencia para esto
        }
        return mapping.get(event_type, True)

    def _get_active_channels(self, prefs: UserPreferences) -> List[NotificationChannel]:
        """Obtiene la lista de canales habilitados por el usuario."""
        active = []
        if prefs.email_notifications:
            active.append(NotificationChannel.EMAIL)
        if prefs.push_notifications:
            active.append(NotificationChannel.PUSH)
        # In-app podría estar habilitado por defecto si no hay switch
        active.append(NotificationChannel.IN_APP)
        return active

    def _dispatch_email(self, user: User, event_type: NotificationType, data: Dict[str, Any]) -> bool:
        """Lógica interna para mapear evento -> método del EmailService."""
        data['user_name'] = user.name # Asegurar que el nombre esté disponible
        
        try:
            attachment = data.get('attachment') # Opcional: dict {"filename": str, "content": bytes}

            if event_type == NotificationType.LOGIN_ALERT:
                # El data debe contener login_alert (objeto LoginAlert)
                return self.email_service.send_login_alert_email(user, data['login_alert'])
            
            elif event_type == NotificationType.PASSWORD_RESET:
                return self.email_service.send_password_reset_email(
                    user.email, user.name, data['token'], data['frontend_url']
                )
            
            elif event_type == NotificationType.PASSWORD_CHANGED:
                return self.email_service.send_password_changed_confirmation(user.email, user.name)
            
            elif event_type == NotificationType.WEEKLY_SUMMARY:
                return self.email_service.send_weekly_summary(
                    user.email, user.name, data['summary_data'], attachment=attachment
                )
            
            elif event_type == NotificationType.PROFILE_UPDATED:
                return self.email_service.send_profile_update_notification(user.email, user.name, data['fields'])
            
            return False
        except Exception as e:
            logger.error(f"Failed to dispatch email for {event_type}: {e}")
            return False

    def _log_history(
        self, 
        db: Session, 
        user_id: int, 
        event_type: NotificationType, 
        channel: NotificationChannel, 
        status: NotificationStatus,
        error_detail: Optional[str] = None
    ) -> NotificationHistory:
        """Registra el evento en la tabla de historial."""
        history = NotificationHistory(
            user_id=user_id,
            type=event_type,
            channel=channel,
            status=status,
            error_detail=error_detail
        )
        db.add(history)
        db.commit()
        db.refresh(history)
        return history
