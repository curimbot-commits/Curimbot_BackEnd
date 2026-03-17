"""
Servicio de Recuperación de Contraseña
app/services/password_reset_service.py
"""
import secrets
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.models import User, PasswordResetToken
from app.schemas.auth_schemas import get_password_hash
from app.services.notification_service import NotificationService
from app.enums.enums import NotificationType

logger = logging.getLogger(__name__)


class PasswordResetService:
    """Servicio para gestionar recuperación de contraseñas"""
    
    def __init__(self, notification_service: NotificationService, frontend_url: str):
        """
        Inicializa el servicio
        
        Args:
            notification_service: Instancia del servicio de notificaciones
            frontend_url: URL base del frontend
        """
        self.notification_service = notification_service
        self.frontend_url = frontend_url
        self.token_expiry_hours = 1
    
    def generate_reset_token(self) -> str:
        """
        Genera un token seguro para recuperación de contraseña
        
        Returns:
            Token aleatorio de 32 bytes en formato hexadecimal
        """
        return secrets.token_urlsafe(32)
    
    def request_password_reset(
        self,
        email: str,
        db: Session
    ) -> dict:
        """
        Solicita recuperación de contraseña
        
        Args:
            email: Email del usuario
            db: Sesión de base de datos
            
        Returns:
            Diccionario con mensaje de confirmación
        """
        try:
            # Buscar usuario por email
            user = db.query(User).filter(User.email == email).first()
            
            # Por seguridad, siempre retornar el mismo mensaje
            # No revelar si el email existe o no
            standard_response = {
                "message": "Si el correo existe, recibirás instrucciones para recuperar tu contraseña"
            }
            
            if not user:
                return standard_response
            
            if not user.is_active:
                logger.warning(f"Password reset requested for inactive user: {email}")
                return standard_response
            
            # Invalidar tokens anteriores del usuario
            db.query(PasswordResetToken).filter(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.is_used == False
            ).update({"is_used": True})
            
            # Generar nuevo token
            reset_token = self.generate_reset_token()
            expiry_time = datetime.now(timezone.utc) + timedelta(hours=self.token_expiry_hours)
            
            # Guardar token en BD
            token_record = PasswordResetToken(
                user_id=user.id,
                token=reset_token,
                expires_at=expiry_time,
                is_used=False
            )
            db.add(token_record)
            db.commit()
            
            # Enviar notificación via central
            self.notification_service.send_notification(
                db=db,
                user_id=user.id,
                event_type=NotificationType.PASSWORD_RESET,
                data={
                    "token": reset_token,
                    "frontend_url": self.frontend_url
                }
            )
            
            return standard_response
            
        except Exception as e:
            logger.exception(f"Error requesting password reset for {email}: {e}")
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error al procesar la solicitud"
            )
    
    def verify_reset_token(
        self,
        token: str,
        db: Session
    ) -> Optional[PasswordResetToken]:
        """
        Verifica si un token de recuperación es válido
        
        Args:
            token: Token a verificar
            db: Sesión de base de datos
            
        Returns:
            Token record si es válido, None si no lo es
        """
        try:
            token_record = db.query(PasswordResetToken).filter(
                PasswordResetToken.token == token,
                PasswordResetToken.is_used == False
            ).first()
            
            if not token_record:
                logger.warning(f"Invalid or already used reset token")
                return None
            
            if token_record.expires_at < datetime.now(timezone.utc):
                logger.warning(f"Expired reset token for user {token_record.user_id}")
                return None
            
            return token_record
            
        except Exception as e:
            logger.exception(f"Error verifying reset token: {e}")
            return None
    
    def reset_password(
        self,
        token: str,
        new_password: str,
        db: Session
    ) -> dict:
        """
        Restablece la contraseña del usuario.

        - Verifica el token
        - Actualiza la contraseña en el campo que usa login (password_hash)
        - Marca token como usado
        - Envía email de confirmación
        """
        try:
            # 1. Verificar token
            token_record = self.verify_reset_token(token, db)
            if not token_record:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Token inválido o expirado"
                )

            # 2. Obtener usuario
            user = db.query(User).filter(User.id == token_record.user_id).first()
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Usuario no encontrado"
                )

            # 3. Actualizar contraseña en el campo correcto para login
            # Asegurándonos de usar el mismo campo que verifica verify_password
            user.password_hash = get_password_hash(new_password)

            # 4. Marcar token como usado
            token_record.is_used = True
            token_record.used_at = datetime.now(timezone.utc)

            # 5. Guardar cambios en la DB
            db.commit()

            # 6. Enviar notificación de confirmación
            self.notification_service.send_notification(
                db=db,
                user_id=user.id,
                event_type=NotificationType.PASSWORD_CHANGED,
                data={}
            )


            return {
                "message": "Contraseña actualizada exitosamente"
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"Error resetting password: {e}")
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error al restablecer la contraseña"
            )

    
    def cleanup_expired_tokens(self, db: Session) -> int:
        """
        Limpia tokens expirados de la base de datos
        
        Args:
            db: Sesión de base de datos
            
        Returns:
            Número de tokens eliminados
        """
        try:
            deleted_count = db.query(PasswordResetToken).filter(
                PasswordResetToken.expires_at < datetime.now(timezone.utc)
            ).delete()
            
            db.commit()
            return deleted_count
            
        except Exception as e:
            logger.exception(f"Error cleaning up expired tokens: {e}")
            db.rollback()
            return 0