
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from fastapi import Request

from app.models.models import User, LoginAlert, UserPreferences
from app.services.email_service import EmailService

logger = logging.getLogger(__name__)


class LoginAlertService:
    """
    Servicio para gestionar alertas de inicio de sesión
    
    Detecta y notifica sobre:
    - Nuevos dispositivos
    - Nuevas ubicaciones
    - Actividad sospechosa
    """
    
    def __init__(self, email_service: EmailService):
        self.email_service = email_service

    @staticmethod
    def parse_user_agent(user_agent: str) -> str:
        """
        Extrae información del dispositivo desde el User-Agent
        
        Args:
            user_agent: String del User-Agent
            
        Returns:
            String descriptivo del dispositivo (ej: "Chrome en Windows")
        """
        if not user_agent:
            return "Dispositivo desconocido"
        
        # Detectar navegador
        browser = "Navegador desconocido"
        if "Chrome" in user_agent and "Edg" not in user_agent:
            browser = "Chrome"
        elif "Firefox" in user_agent:
            browser = "Firefox"
        elif "Safari" in user_agent and "Chrome" not in user_agent:
            browser = "Safari"
        elif "Edg" in user_agent:
            browser = "Edge"
        elif "OPR" in user_agent or "Opera" in user_agent:
            browser = "Opera"
        
        # Detectar sistema operativo
        os_name = "Sistema desconocido"
        if "Windows" in user_agent:
            os_name = "Windows"
        elif "Macintosh" in user_agent or "Mac OS" in user_agent:
            os_name = "MacOS"
        elif "Linux" in user_agent and "Android" not in user_agent:
            os_name = "Linux"
        elif "Android" in user_agent:
            os_name = "Android"
        elif "iPhone" in user_agent or "iPad" in user_agent:
            os_name = "iOS"
        
        return f"{browser} en {os_name}"

    @staticmethod
    def get_location_from_ip(ip_address: str) -> Optional[str]:
        """
        Obtiene la ubicación aproximada desde una IP
        
        En producción, usar un servicio como:
        - ipapi.co
        - ip-api.com
        - MaxMind GeoIP
        
        Args:
            ip_address: Dirección IP
            
        Returns:
            String de ubicación (ej: "Madrid, España") o None
        """
        # Implementación básica - En producción usar un servicio real
        if ip_address.startswith("127.") or ip_address == "localhost":
            return "Local"
        
        # Aquí iría la llamada a un servicio de geolocalización
        # Por ahora retornamos una ubicación genérica
        return "Ubicación no disponible"

    def check_for_suspicious_activity(
        self, 
        user: User, 
        ip_address: str, 
        device: str,
        db: Session
    ) -> Tuple[bool, bool, bool]:
        """
        Verifica si el inicio de sesión es sospechoso
        
        Args:
            user: Usuario que inicia sesión
            ip_address: IP del login
            device: Dispositivo utilizado
            db: Sesión de base de datos
            
        Returns:
            Tupla (es_sospechoso, es_nuevo_dispositivo, es_nueva_ubicacion)
        """
        # Obtener los últimos logins del usuario (últimos 30 días)
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
        
        recent_logins = db.query(LoginAlert).filter(
            LoginAlert.user_id == user.id,
            LoginAlert.created_at >= thirty_days_ago
        ).all()
        
        # Si no hay logins previos, marcar como nuevo pero no sospechoso
        if not recent_logins:
            return False, True, True
        
        # Verificar si es un dispositivo conocido
        known_devices = {login.device for login in recent_logins}
        is_new_device = device not in known_devices
        
        # Verificar si es una IP conocida
        known_ips = {login.ip_address for login in recent_logins}
        is_new_ip = ip_address not in known_ips
        
        # Criterios de sospecha:
        # 1. Dispositivo Y ubicación nuevos al mismo tiempo
        # 2. Múltiples logins desde IPs diferentes en poco tiempo
        is_suspicious = False
        
        if is_new_device and is_new_ip:
            # Verificar si hubo un login reciente desde otra IP
            recent_login = db.query(LoginAlert).filter(
                LoginAlert.user_id == user.id,
                LoginAlert.created_at >= datetime.now(timezone.utc) - timedelta(hours=1)
            ).order_by(LoginAlert.created_at.desc()).first()
            
            if recent_login and recent_login.ip_address != ip_address:
                is_suspicious = True
        
        return is_suspicious, is_new_device, is_new_ip

    def record_login_and_check(
        self,
        user: User,
        request: Request,
        db: Session
    ) -> Optional[LoginAlert]:
        """
        Registra un inicio de sesión y verifica si debe enviarse alerta
        
        Args:
            user: Usuario que inicia sesión
            request: Request de FastAPI para obtener IP y User-Agent
            db: Sesión de base de datos
            
        Returns:
            LoginAlert creado o None si no se debe alertar
        """
        try:
            # Obtener preferencias del usuario
            preferences = db.query(UserPreferences).filter(
                UserPreferences.user_id == user.id
            ).first()
            
            # Si no tiene alertas activadas, no hacer nada
            if not preferences or not preferences.login_alerts:
                return None
            
            # Extraer información del request
            ip_address = request.client.host if request.client else "unknown"
            user_agent = request.headers.get("user-agent", "")
            device = self.parse_user_agent(user_agent)
            location = self.get_location_from_ip(ip_address)
            
            # Verificar si es sospechoso
            is_suspicious, is_new_device, is_new_location = self.check_for_suspicious_activity(
                user, ip_address, device, db
            )
            
            # Crear registro de login
            login_alert = LoginAlert(
                user_id=user.id,
                device=device,
                location=location,
                ip_address=ip_address,
                user_agent=user_agent,
                is_suspicious=is_suspicious,
                is_new_device=is_new_device,
                is_new_location=is_new_location,
                notification_sent=False
            )
            
            db.add(login_alert)
            db.commit()
            db.refresh(login_alert)
            
            # Enviar notificación si es necesario
            should_notify = (
                preferences.email_notifications and
                (is_suspicious or is_new_device or is_new_location)
            )
            
            if should_notify:
                self.send_login_alert_email(user, login_alert, db)
            
            return login_alert
            
        except Exception as e:
            logger.exception(f"Error recording login alert for user {user.id}: {e}")
            db.rollback()
            return None

    def send_login_alert_email(
        self,
        user: User,
        login_alert: LoginAlert,
        db: Session
    ) -> bool:
        """
        Envía email de alerta de inicio de sesión
        
        Args:
            user: Usuario
            login_alert: Información del login
            db: Sesión de base de datos
            
        Returns:
            True si se envió correctamente
        """
        try:
            # Determinar el tipo de alerta
            alert_type = "sospechoso" if login_alert.is_suspicious else "nuevo"
            
            # Construir el asunto
            subject = f"⚠️ Inicio de sesión {alert_type} detectado"
            
            # Construir el contenido HTML
            html_content = f"""
                <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                    <h2 style="color: {'#dc2626' if login_alert.is_suspicious else '#02ab74'};">
                        {'🚨 Actividad sospechosa detectada' if login_alert.is_suspicious else '🔔 Nuevo inicio de sesión'}
                    </h2>
                    
                    <p>Hola {user.name},</p>
                    
                    <p>
                        {'Se ha detectado un inicio de sesión sospechoso en tu cuenta.' if login_alert.is_suspicious 
                         else 'Se ha detectado un nuevo inicio de sesión en tu cuenta.'}
                    </p>
                    
                    <div style="background-color: #f3f4f6; padding: 20px; border-radius: 8px; margin: 20px 0;">
                        <h3 style="margin-top: 0;">Detalles del inicio de sesión:</h3>
                        <ul style="list-style: none; padding: 0;">
                            <li><strong>📱 Dispositivo:</strong> {login_alert.device}</li>
                            <li><strong>📍 Ubicación:</strong> {login_alert.location or 'No disponible'}</li>
                            <li><strong>🌐 IP:</strong> {login_alert.ip_address}</li>
                            <li><strong>🕐 Fecha y hora:</strong> {login_alert.created_at.strftime('%d/%m/%Y %H:%M:%S')}</li>
                        </ul>
                        
                        {f'<p style="color: #dc2626; font-weight: bold;">⚠️ Este inicio de sesión es nuevo desde un dispositivo y ubicación desconocidos.</p>' 
                         if login_alert.is_suspicious else ''}
                    </div>
                    
                    <div style="background-color: {'#fef2f2' if login_alert.is_suspicious else '#f0fdf4'}; 
                                border-left: 4px solid {'#dc2626' if login_alert.is_suspicious else '#02ab74'}; 
                                padding: 15px; margin: 20px 0;">
                        <p style="margin: 0;">
                            <strong>{'¿No fuiste tú?' if login_alert.is_suspicious else '¿Fuiste tú?'}</strong><br>
                            {f'Si no reconoces este inicio de sesión, <strong>cambia tu contraseña inmediatamente</strong> y activa la autenticación de dos factores.'
                             if login_alert.is_suspicious 
                             else 'Si fuiste tú, puedes ignorar este mensaje. Es solo una notificación de seguridad.'}
                        </p>
                    </div>
                    
                    <p style="color: #6b7280; font-size: 12px; margin-top: 30px;">
                        Este es un mensaje automático de seguridad. Si deseas desactivar estas alertas, 
                        puedes hacerlo en la configuración de tu cuenta.
                    </p>
                </div>
            """
            
            # Enviar email
            success = self.email_service.send_email(
                to_email=user.email,
                subject=subject,
                html_content=html_content
            )
            
            if success:
                # Marcar como enviado
                login_alert.notification_sent = True
                login_alert.notification_sent_at = datetime.now(timezone.utc)
                db.commit()
                
            
            return success
            
        except Exception as e:
            logger.exception(f"Error sending login alert email to user {user.id}: {e}")
            return False

    @staticmethod
    def get_recent_login_alerts(
        user: User,
        days: int = 30,
        db: Session = None
    ) -> list[LoginAlert]:
        """
        Obtiene las alertas de login recientes de un usuario
        
        Args:
            user: Usuario
            days: Número de días hacia atrás
            db: Sesión de base de datos
            
        Returns:
            Lista de LoginAlert
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        return db.query(LoginAlert).filter(
            LoginAlert.user_id == user.id,
            LoginAlert.created_at >= cutoff_date
        ).order_by(LoginAlert.created_at.desc()).all()