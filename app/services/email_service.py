"""
Servicio de Email con Resend
app/services/email_service.py
"""
import resend
import logging
from typing import Optional, List, Any
from datetime import datetime, timezone

from app.services.email_templates import EmailTemplates

logger = logging.getLogger(__name__)


class EmailService:
    """Servicio para envío de emails con Resend"""
    
    def __init__(self, api_key: str, from_email: str):
        """
        Inicializa el servicio de email
        
        Args:
            api_key: API key de Resend
            from_email: Email verificado desde el cual enviar
        """
        resend.api_key = api_key
        self.from_email = from_email
        self.templates = EmailTemplates()
    
    def send_email(
        self, 
        to_email: str, 
        subject: str, 
        html_content: str,
        from_email: Optional[str] = None,
        attachments: Optional[List[dict]] = None
    ) -> Optional[dict]:
        """
        Envía un email usando Resend con soporte para adjuntos
        
        Args:
            to_email: Email del destinatario
            subject: Asunto del email
            html_content: Contenido HTML del email
            from_email: Email del remitente (opcional)
            attachments: Lista de dicts con {"filename": str, "content": bytes}
            
        Returns:
            Respuesta de Resend o None si falla
        """
        try:
            params = {
                "from": from_email or self.from_email,
                "to": [to_email],
                "subject": subject,
                "html": html_content,
            }
            
            if attachments:
                # Resend espera contenido en base64 o bytes si la librería lo maneja
                # Para la librería de Python, se pasan los bytes directamente o una lista
                # Convertimos bytes a lista si es necesario, o simplemente pasamos el dict
                # Según docs: [{"filename": "invoice.pdf", "content": list(content_bytes)}] 
                # o simplemente los bytes si la versión es reciente.
                resend_attachments = []
                for att in attachments:
                    resend_attachments.append({
                        "filename": att["filename"],
                        "content": list(att["content"]) if isinstance(att["content"], bytes) else att["content"]
                    })
                params["attachments"] = resend_attachments

            response = resend.Emails.send(params)
            return response
        except Exception as e:
            logger.error(f"Error sending email to {to_email}: {e}")
            return None
    
    def send_password_reset_email(
        self,
        to_email: str,
        user_name: str,
        reset_token: str,
        frontend_url: str
    ) -> Optional[dict]:
        """
        Envía email de recuperación de contraseña
        
        Args:
            to_email: Email del usuario
            user_name: Nombre del usuario
            reset_token: Token de recuperación
            frontend_url: URL base del frontend
        """
        html_content = self.templates.password_reset(
            user_name=user_name,
            reset_link=f"{frontend_url}/resetpassword?token={reset_token}"
        )
        
        return self.send_email(
            to_email=to_email,
            subject="🔒 Recuperación de Contraseña - SecureDoc",
            html_content=html_content
        )
    
    def send_password_changed_confirmation(
        self,
        to_email: str,
        user_name: str
    ) -> Optional[dict]:
        """
        Envía confirmación de cambio de contraseña exitoso
        
        Args:
            to_email: Email del usuario
            user_name: Nombre del usuario
        """
        html_content = self.templates.password_changed(user_name=user_name)
        
        return self.send_email(
            to_email=to_email,
            subject="✅ Contraseña Actualizada - SecureDoc",
            html_content=html_content
        )
    
    def send_profile_update_notification(
        self,
        to_email: str,
        user_name: str,
        changed_fields: List[str]
    ) -> Optional[dict]:
        """
        Envía notificación de actualización de perfil
        
        Args:
            to_email: Email del usuario
            user_name: Nombre del usuario
            changed_fields: Lista de campos modificados
        """
        fields_text = ", ".join(changed_fields)
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #028a5e 0%, #5a058f 100%); 
                          color: white; padding: 20px; border-radius: 8px 8px 0 0; }}
                .content {{ background: #f9f9f9; padding: 20px; border-radius: 0 0 8px 8px; }}
                .footer {{ text-align: center; margin-top: 20px; color: #666; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>Perfil Actualizado</h2>
                </div>
                <div class="content">
                    <p>Hola {user_name},</p>
                    <p>Tu perfil ha sido actualizado exitosamente.</p>
                    <p><strong>Campos modificados:</strong> {fields_text}</p>
                    <p><strong>Fecha:</strong> {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')}</p>
                    <p>Si no realizaste este cambio, por favor contacta con soporte inmediatamente.</p>
                </div>
                <div class="footer">
                    <p>© 2025 SecureDoc App. Todos los derechos reservados.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return self.send_email(
            to_email=to_email,
            subject="Tu perfil ha sido actualizado",
            html_content=html_content
        )

    def send_weekly_summary(
        self,
        to_email: str,
        user_name: str,
        summary_data: dict,
        attachment: Optional[dict] = None
    ) -> Optional[dict]:
        """
        Envía resumen semanal con adjunto opcional
        
        Args:
            to_email: Email del usuario
            user_name: Nombre del usuario
            summary_data: Datos para el HTML del correo
            attachment: Dict con {"filename": str, "content": bytes}
        """
        html_content = self.templates.weekly_summary(user_name, summary_data)
        attachments = [attachment] if attachment else None
        
        return self.send_email(
            to_email=to_email,
            subject="📊 Tu resumen semanal - SecureDoc",
            html_content=html_content,
            attachments=attachments
        )

    def send_login_alert_email(self, user: Any, login_alert: Any) -> bool:
        """Alerta de inicio de sesión"""
        html_content = self.templates.login_alert(user.name, login_alert)
        success = self.send_email(
            to_email=user.email,
            subject="⚠️ Alerta de Seguridad - SecureDoc",
            html_content=html_content
        )
        return success is not None

    def send_preference_change_notification(
        self,
        to_email: str,
        user_name: str,
        preference_type: str
    ) -> Optional[dict]:
        """Envía notificación de cambio en preferencias"""
        # Aquí también podríamos usar una plantilla si quisiéramos uniformidad
        html_content = f"""
            <p>Hola <strong>{user_name}</strong>,</p>
            <p>Tus preferencias de <strong>{preference_type}</strong> han sido actualizadas exitosamente.</p>
        """
        # Usamos el wrap genérico si existe o uno simple
        return self.send_email(
            to_email=to_email,
            subject="Tus preferencias han sido actualizadas",
            html_content=html_content
        )