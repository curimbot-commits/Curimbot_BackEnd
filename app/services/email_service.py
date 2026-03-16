"""
Servicio de Email con Resend
app/services/email_service.py
"""
import resend
import logging
from typing import Optional, List
from datetime import datetime, timezone

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
    
    def send_email(
        self, 
        to_email: str, 
        subject: str, 
        html_content: str,
        from_email: Optional[str] = None
    ) -> Optional[dict]:
        """
        Envía un email usando Resend
        
        Args:
            to_email: Email del destinatario
            subject: Asunto del email
            html_content: Contenido HTML del email
            from_email: Email del remitente (opcional)
            
        Returns:
            Respuesta de Resend o None si falla
        """
        try:
            response = resend.Emails.send({
                "from": from_email or self.from_email,
                "to": [to_email],
                "subject": subject,
                "html": html_content,
            })
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
        reset_link = f"{frontend_url}/resetpassword?token={reset_token}"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #02ab74 0%, #7209b7 100%); 
                          color: white; padding: 30px; border-radius: 8px 8px 0 0; text-align: center; }}
                .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 8px 8px; }}
                .button {{ display: inline-block; background: #02ab74; color: white; 
                          padding: 14px 28px; text-decoration: none; border-radius: 8px; 
                          font-weight: bold; margin: 20px 0; }}
                .button:hover {{ background: #028a5f; }}
                .warning {{ background: #fff3cd; border-left: 4px solid #ffc107; 
                           padding: 12px; margin: 20px 0; border-radius: 4px; }}
                .footer {{ text-align: center; margin-top: 20px; color: #666; font-size: 12px; }}
                .icon {{ font-size: 48px; margin-bottom: 10px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="icon">🔒</div>
                    <h2>Recuperación de Contraseña</h2>
                </div>
                <div class="content">
                    <p>Hola {user_name},</p>
                    <p>Hemos recibido una solicitud para restablecer la contraseña de tu cuenta.</p>
                    <p>Haz clic en el botón de abajo para crear una nueva contraseña:</p>
                    
                    <div style="text-align: center;">
                        <a href="{reset_link}" class="button">Restablecer Contraseña</a>
                    </div>
                    
                    <div class="warning">
                        <strong>⚠️ Importante:</strong>
                        <ul style="margin: 10px 0;">
                            <li>Este enlace expirará en <strong>1 hora</strong></li>
                            <li>Si no solicitaste este cambio, ignora este correo</li>
                            <li>Nunca compartas este enlace con nadie</li>
                        </ul>
                    </div>
                    
                    <p style="margin-top: 20px; font-size: 14px; color: #666;">
                        Si el botón no funciona, copia y pega este enlace en tu navegador:
                    </p>
                    <p style="word-break: break-all; font-size: 12px; color: #666;">
                        {reset_link}
                    </p>
                    
                    <p style="margin-top: 20px;">
                        <strong>Fecha de solicitud:</strong> {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')}
                    </p>
                </div>
                <div class="footer">
                    <p>© 2025 SecureDoc App. Todos los derechos reservados.</p>
                    <p>Si no solicitaste este cambio, tu cuenta sigue siendo segura.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
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
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #02ab74 0%, #7209b7 100%); 
                          color: white; padding: 30px; border-radius: 8px 8px 0 0; text-align: center; }}
                .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 8px 8px; }}
                .success {{ background: #d4edda; border-left: 4px solid #28a745; 
                           padding: 12px; margin: 20px 0; border-radius: 4px; color: #155724; }}
                .footer {{ text-align: center; margin-top: 20px; color: #666; font-size: 12px; }}
                .icon {{ font-size: 48px; margin-bottom: 10px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="icon">✅</div>
                    <h2>Contraseña Actualizada</h2>
                </div>
                <div class="content">
                    <p>Hola {user_name},</p>
                    
                    <div class="success">
                        <strong>✅ Tu contraseña ha sido cambiada exitosamente</strong>
                    </div>
                    
                    <p>Tu contraseña se ha actualizado correctamente.</p>
                    <p><strong>Fecha del cambio:</strong> {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')}</p>
                    
                    <div style="background: #fff3cd; border-left: 4px solid #ffc107; padding: 12px; margin: 20px 0; border-radius: 4px;">
                        <strong>⚠️ ¿No fuiste tú?</strong>
                        <p style="margin: 10px 0 0 0;">
                            Si no realizaste este cambio, contacta con soporte inmediatamente.
                        </p>
                    </div>
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
        summary_data: dict
    ) -> Optional[dict]:
        """
        Envía resumen semanal de actividad
        
        Args:
            to_email: Email del usuario
            user_name: Nombre del usuario
            summary_data: Datos del resumen (documentos, actividad, etc.)
        """
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #028a5e 0%, #5a058f 100%); 
                          color: white; padding: 20px; border-radius: 8px 8px 0 0; }}
                .content {{ background: #f9f9f9; padding: 20px; }}
                .stat-box {{ background: white; padding: 15px; margin: 10px 0; 
                            border-radius: 8px; border-left: 4px solid #02ab74; }}
                .stat-number {{ font-size: 24px; font-weight: bold; color: #02ab74; }}
                .footer {{ text-align: center; margin-top: 20px; color: #666; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>📊 Tu Resumen Semanal</h2>
                </div>
                <div class="content">
                    <p>Hola {user_name},</p>
                    <p>Aquí está tu resumen de actividad de esta semana:</p>
                    
                    <div class="stat-box">
                        <div class="stat-number">{summary_data.get('documents_uploaded', 0)}</div>
                        <div>Documentos subidos</div>
                    </div>
                    
                    <div class="stat-box">
                        <div class="stat-number">{summary_data.get('documents_viewed', 0)}</div>
                        <div>Documentos visualizados</div>
                    </div>
                    
                    <div class="stat-box">
                        <div class="stat-number">{summary_data.get('documents_downloaded', 0)}</div>
                        <div>Documentos descargados</div>
                    </div>
                    
                    <p style="margin-top: 20px;">
                        <a href="https://tuapp.com/dashboard" 
                           style="background: #02ab74; color: white; padding: 10px 20px; 
                                  text-decoration: none; border-radius: 5px; display: inline-block;">
                            Ver Dashboard
                        </a>
                    </p>
                </div>
                <div class="footer">
                    <p>© 2025 SecureDoc App. Todos los derechos reservados.</p>
                    <p><a href="https://tuapp.com/settings">Gestionar preferencias de notificaciones</a></p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return self.send_email(
            to_email=to_email,
            subject=f"📊 Tu resumen semanal - {datetime.now(timezone.utc).strftime('%d/%m/%Y')}",
            html_content=html_content
        )
    
    def send_preference_change_notification(
        self,
        to_email: str,
        user_name: str,
        preference_type: str
    ) -> Optional[dict]:
        """
        Envía notificación de cambio en preferencias
        
        Args:
            to_email: Email del usuario
            user_name: Nombre del usuario
            preference_type: Tipo de preferencia modificada
        """
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #028a5e 0%, #5a058f 100%); 
                          color: white; padding: 20px; border-radius: 8px; }}
                .content {{ padding: 20px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>⚙️ Preferencias Actualizadas</h2>
                </div>
                <div class="content">
                    <p>Hola {user_name},</p>
                    <p>Tus preferencias de <strong>{preference_type}</strong> han sido actualizadas exitosamente.</p>
                    <p><strong>Fecha:</strong> {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')}</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return self.send_email(
            to_email=to_email,
            subject="Tus preferencias han sido actualizadas",
            html_content=html_content
        )