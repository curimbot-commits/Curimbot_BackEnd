
from datetime import datetime, timezone
from typing import List, Dict, Any

class EmailTemplates:
    """Centralización de plantillas HTML para emails."""

    BASE_STYLE = """
    body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 0; }
    .container { max-width: 600px; margin: 20px auto; border: 1px solid #e5e7eb; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); }
    .header { background: linear-gradient(135deg, #02ab74 0%, #7209b7 100%); color: white; padding: 30px; text-align: center; }
    .content { padding: 30px; background: #ffffff; }
    .footer { background: #f9fafb; padding: 20px; text-align: center; color: #6b7280; font-size: 12px; border-top: 1px solid #e5e7eb; }
    .button { display: inline-block; background-color: #02ab74; color: #ffffff !important; padding: 12px 24px; text-decoration: none; border-radius: 8px; font-weight: 600; margin: 20px 0; }
    .stat-box { background: #f0fdf4; padding: 15px; margin: 10px 0; border-radius: 8px; border-left: 4px solid #02ab74; }
    .warning-box { background: #fffbeb; padding: 15px; margin: 10px 0; border-radius: 8px; border-left: 4px solid #f59e0b; }
    """

    @staticmethod
    def _wrap(content: str, title: str) -> str:
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>{EmailTemplates.BASE_STYLE}</style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>{title}</h1>
                </div>
                <div class="content">
                    {content}
                </div>
                <div class="footer">
                    <p>© {datetime.now().year} Curim AI Assistant. Todos los derechos reservados.</p>
                    <p>Enviado de forma segura por SecureDoc Infrastructure.</p>
                </div>
            </div>
        </body>
        </html>
        """

    @staticmethod
    def password_reset(user_name: str, reset_link: str) -> str:
        content = f"""
            <p>Hola <strong>{user_name}</strong>,</p>
            <p>Hemos recibido una solicitud para restablecer la contraseña de tu cuenta.</p>
            <div style="text-align: center;">
                <a href="{reset_link}" class="button">Restablecer Contraseña</a>
            </div>
            <div class="warning-box">
                <strong>⚠️ Seguridad:</strong> Este enlace expirará en 1 hora. Si no solicitaste este cambio, puedes ignorar este correo de forma segura.
            </div>
        """
        return EmailTemplates._wrap(content, "Recuperación de Contraseña")

    @staticmethod
    def password_changed(user_name: str) -> str:
        content = f"""
            <p>Hola <strong>{user_name}</strong>,</p>
            <div class="stat-box">
                <strong>✅ Éxito:</strong> Tu contraseña ha sido actualizada correctamente.
            </div>
            <p>Si no realizaste este cambio, por favor contacta con soporte inmediatamente para proteger tu cuenta.</p>
        """
        return EmailTemplates._wrap(content, "Seguridad de la Cuenta")

    @staticmethod
    def login_alert(user_name: str, alert_data: Any) -> str:
        # alert_data puede ser el objeto LoginAlert
        is_suspicious = getattr(alert_data, 'is_suspicious', False)
        status_color = "#dc2626" if is_suspicious else "#02ab74"
        
        content = f"""
            <p>Hola <strong>{user_name}</strong>,</p>
            <p>Se ha detectado un {'inicio de sesión sospechoso' if is_suspicious else 'nuevo inicio de sesión'} en tu cuenta.</p>
            
            <div class="stat-box" style="border-left-color: {status_color};">
                <ul style="list-style: none; padding: 0;">
                    <li><strong>📱 Dispositivo:</strong> {getattr(alert_data, 'device', 'Desconocido')}</li>
                    <li><strong>📍 Ubicación:</strong> {getattr(alert_data, 'location', 'No disponible')}</li>
                    <li><strong>🌐 IP:</strong> {getattr(alert_data, 'ip_address', 'Desconocida')}</li>
                    <li><strong>🕐 Fecha:</strong> {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M:%S')} UTC</li>
                </ul>
            </div>
            
            <div class="warning-box">
                <strong>¿No fuiste tú?</strong> Si no reconoces esta actividad, cambia tu contraseña y revisa tus sesiones activas desde el panel de seguridad.
            </div>
        """
        return EmailTemplates._wrap(content, "Alerta de Seguridad")

    @staticmethod
    def weekly_summary(user_name: str, summary_data: Dict[str, Any]) -> str:
        content = f"""
            <p>Hola <strong>{user_name}</strong>,</p>
            <p>Aquí tienes tu actividad resumida de la última semana:</p>
            
            <div class="stat-box">
                <strong>Documentos subidos:</strong> {summary_data.get('documents_uploaded', 0)}
            </div>
            <div class="stat-box">
                <strong>Interacciones con IA:</strong> {summary_data.get('ai_interactions', 0)}
            </div>
            
            <p>Sigue aprovechando al máximo tu asistente Curim.</p>
            <div style="text-align: center;">
                <a href="https://curim.ai/dashboard" class="button">Ver Dashboard Completo</a>
            </div>
        """
        return EmailTemplates._wrap(content, "Resumen Semanal")
