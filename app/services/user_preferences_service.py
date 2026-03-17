import os
import logging
from typing import Optional, List
import uuid
from sqlalchemy.orm import Session
from fastapi import UploadFile, HTTPException, status

from app.models.models import User, UserPreferences
from app.schemas.user_preferences_schemas import (
    NotificationPreferencesUpdate,
    InterfacePreferencesUpdate,
    UserProfileUpdate,
    UserPreferencesResponse
)
from app.services.email_service import EmailService

logger = logging.getLogger(__name__)

def remove_file(self, file_path: str):
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
            else:
                logger.warning(f"File not found: {file_path}")
        except Exception as e:
            logger.warning(f"Failed to delete file {file_path}: {e}")

class UserPreferencesService:
    UPLOAD_DIR = "uploads/profile_photos"
    ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
    
    def __init__(self, email_service: EmailService):
        self.email_service = email_service
        os.makedirs(self.UPLOAD_DIR, exist_ok=True)
    
    def upload_profile_photo(self, user: User, file: UploadFile, db: Session) -> str:
        file_ext = os.path.splitext(file.filename)[1].lower()
        if file_ext not in self.ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Formato de archivo no permitido. Use: {', '.join(self.ALLOWED_EXTENSIONS)}"
            )

        # Validar tamaño del archivo
        file_size = len(file.file.read())  # Get size without moving file pointer
        if file_size > self.MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"El archivo es demasiado grande. Máximo: {self.MAX_FILE_SIZE / 1024 / 1024}MB"
            )

        # Generar nombre único
        filename = f"user_{user.id}_{uuid.uuid4().hex}{file_ext}"
        file_path = os.path.join(self.UPLOAD_DIR, filename)

        try:
            # Guardar archivo
            with open(file_path, "wb") as buffer:
                buffer.write(file.file.read())
            
            # Eliminar foto anterior si existe
            prefs = self.get_or_create_preferences(user, db)
            if prefs.profile_photo_url:
                old_file_path = prefs.profile_photo_url.replace("/uploads/", "uploads/")
                remove_file(old_file_path)

            # Actualizar URL en base de datos
            photo_url = f"/uploads/profile_photos/{filename}"
            prefs.profile_photo_url = photo_url
            db.commit()

            return photo_url

        except Exception as e:
            logger.error(f"Error uploading profile photo for user {user.id}: {e}")
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except:
                    pass
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error al subir la foto de perfil"
            )
    
    

    @staticmethod
    def get_or_create_preferences(user: User, db: Session) -> UserPreferences:
        """
        Obtiene o crea las preferencias del usuario
        
        Args:
            user: Usuario actual
            db: Sesión de base de datos
            
        Returns:
            Preferencias del usuario
        """
        prefs = db.query(UserPreferences).filter(
            UserPreferences.user_id == user.id
        ).first()
        
        if not prefs:
            prefs = UserPreferences(user_id=user.id)
            db.add(prefs)
            db.commit()
            db.refresh(prefs)
        
        return prefs
    
    def get_preferences(self, user: User, db: Session) -> UserPreferencesResponse:
        """
        Obtiene las preferencias del usuario
        
        Args:
            user: Usuario actual
            db: Sesión de base de datos
            
        Returns:
            Preferencias del usuario
        """
        prefs = self.get_or_create_preferences(user, db)
        
        return UserPreferencesResponse(
            user_id=prefs.user_id,
            email_notifications=prefs.email_notifications,
            push_notifications=prefs.push_notifications,
            weekly_summary=prefs.weekly_summary,
            weekly_summary_format=prefs.weekly_summary_format,
            login_alerts=prefs.login_alerts,
            security_alerts=prefs.security_alerts,
            language=prefs.language,
            theme=prefs.theme,
            profile_photo_url=prefs.profile_photo_url,
            updated_at=prefs.updated_at
        )

    
    def update_notification_preferences(
        self,
        user: User,
        preferences: NotificationPreferencesUpdate,
        db: Session
    ) -> UserPreferencesResponse:
        """
        Actualiza preferencias de notificaciones
        
        Args:
            user: Usuario actual
            preferences: Nuevas preferencias
            db: Sesión de base de datos
            
        Returns:
            Preferencias actualizadas
        """
        prefs = self.get_or_create_preferences(user, db)
        
        updated_fields = []
        
        if preferences.email_notifications is not None:
            prefs.email_notifications = preferences.email_notifications
            updated_fields.append("Notificaciones por email")
        
        if preferences.push_notifications is not None:
            prefs.push_notifications = preferences.push_notifications
            updated_fields.append("Notificaciones push")
        
        if preferences.weekly_summary is not None:
            prefs.weekly_summary = preferences.weekly_summary
            updated_fields.append("Resumen semanal")

        if preferences.weekly_summary_format is not None:
            prefs.weekly_summary_format = preferences.weekly_summary_format.value
            updated_fields.append("Formato de resumen semanal")

        if preferences.login_alerts is not None:
            prefs.login_alerts = preferences.login_alerts
            updated_fields.append("Alertas de login")

        if preferences.security_alerts is not None:
            prefs.security_alerts = preferences.security_alerts
            updated_fields.append("Alertas de seguridad")

        
        db.commit()
        db.refresh(prefs)
                
        # Enviar notificación si está habilitada
        if prefs.email_notifications and updated_fields:
            try:
                self.email_service.send_preference_change_notification(
                    to_email=user.email,
                    user_name=user.name,
                    preference_type="notificaciones"
                )
            except Exception as e:
                logger.warning(f"Failed to send preference change notification: {e}")
        
        return self.get_preferences(user, db)
    
    def update_interface_preferences(
        self,
        user: User,
        preferences: InterfacePreferencesUpdate,
        db: Session
    ) -> UserPreferencesResponse:
        """
        Actualiza preferencias de interfaz
        
        Args:
            user: Usuario actual
            preferences: Nuevas preferencias
            db: Sesión de base de datos
            
        Returns:
            Preferencias actualizadas
        """
        prefs = self.get_or_create_preferences(user, db)
        
        updated_fields = []
        
        if preferences.language is not None:
            prefs.language = preferences.language.value
            updated_fields.append("Idioma")
        
        if preferences.theme is not None:
            prefs.theme = preferences.theme.value
            updated_fields.append("Tema")
        
        db.commit()
        db.refresh(prefs)
                
        return self.get_preferences(user, db)
    
    def update_profile(
        self,
        user: User,
        profile_data: UserProfileUpdate,
        db: Session
    ) -> User:
        """
        Actualiza el perfil del usuario
        
        Args:
            user: Usuario actual
            profile_data: Datos a actualizar
            db: Sesión de base de datos
            
        Returns:
            Usuario actualizado
        """
        updated_fields = []
        
        if profile_data.name is not None:
            user.name = profile_data.name
            updated_fields.append("Nombre")
        
        if profile_data.email is not None:
            # Verificar que el email no esté en uso
            existing_user = db.query(User).filter(
                User.email == profile_data.email,
                User.id != user.id
            ).first()
            
            if existing_user:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="El email ya está en uso por otro usuario"
                )
            
            user.email = profile_data.email
            updated_fields.append("Email")
        
        db.commit()
        db.refresh(user)
                
        # Enviar notificación
        prefs = self.get_or_create_preferences(user, db)
        if prefs.email_notifications and updated_fields:
            try:
                self.email_service.send_profile_update_notification(
                    to_email=user.email,
                    user_name=user.name,
                    changed_fields=updated_fields
                )
            except Exception as e:
                logger.warning(f"Failed to send profile update notification: {e}")
        
        return user
    
    def upload_profile_photo(
        self,
        user: User,
        file: UploadFile,
        db: Session
    ) -> str:
        """
        Sube la foto de perfil del usuario
        
        Args:
            user: Usuario actual
            file: Archivo de imagen
            db: Sesión de base de datos
            
        Returns:
            URL de la foto subida
            
        Raises:
            HTTPException: Si el archivo no es válido
        """
        # Validar extensión
        file_ext = os.path.splitext(file.filename)[1].lower()
        if file_ext not in self.ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Formato de archivo no permitido. Use: {', '.join(self.ALLOWED_EXTENSIONS)}"
            )
        
        # Validar tamaño
        file.file.seek(0, 2)  # Ir al final del archivo
        file_size = file.file.tell()
        file.file.seek(0)  # Volver al inicio
        
        if file_size > self.MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"El archivo es demasiado grande. Máximo: {self.MAX_FILE_SIZE / 1024 / 1024}MB"
            )
        
        # Generar nombre único
        filename = f"user_{user.id}_{uuid.uuid4().hex}{file_ext}"
        file_path = os.path.join(self.UPLOAD_DIR, filename)
        
        try:
            # Guardar archivo
            with open(file_path, "wb") as buffer:
                buffer.write(file.file.read())
            
            # Eliminar foto anterior si existe
            prefs = self.get_or_create_preferences(user, db)
            if prefs.profile_photo_url:
                old_file_path = prefs.profile_photo_url.replace("/uploads/", "uploads/")
                if os.path.exists(old_file_path):
                    try:
                        os.remove(old_file_path)
                    except Exception as e:
                        logger.warning(f"Failed to delete old profile photo: {e}")
            
            # Actualizar URL en base de datos
            photo_url = f"/uploads/profile_photos/{filename}"
            prefs.profile_photo_url = photo_url
            db.commit()
                        
            return photo_url
            
        except Exception as e:
            logger.error(f"Error uploading profile photo for user {user.id}: {e} - Filename: {file.filename}")
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except:
                    pass
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error al subir la foto de perfil"
            )

    
    
    def delete_profile_photo(self, user: User, db: Session) -> bool:
        """
        Elimina la foto de perfil del usuario
        
        Args:
            user: Usuario actual
            db: Sesión de base de datos
            
        Returns:
            True si se eliminó exitosamente
        """
        prefs = self.get_or_create_preferences(user, db)
        
        if not prefs.profile_photo_url:
            return False
        
        # Eliminar archivo físico
        file_path = prefs.profile_photo_url.replace("/uploads/", "uploads/")
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                logger.warning(f"Failed to delete profile photo file: {e}")
        
        # Limpiar URL en base de datos
        prefs.profile_photo_url = None
        db.commit()
        
        return True
    
    def update_convocatoria_preference(
    self,
    user: User,
    enabled: bool,
    db: Session
) -> UserPreferencesResponse:
        """
        Actualiza la preferencia de convocatorias.
        Solo usuarios admins pueden modificar esta preferencia.
        """
        if not getattr(user, "is_admin", False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para modificar esta preferencia"
            )

        prefs = self.get_or_create_preferences(user, db)
        prefs.convocatoria_enabled = enabled
        db.commit()
        db.refresh(prefs)


        # Notificación opcional por email
        if prefs.email_notifications:
            try:
                self.email_service.send_preference_change_notification(
                    to_email=user.email,
                    user_name=user.name,
                    preference_type="convocatorias"
                )
            except Exception as e:
                logger.warning(f"Failed to send convocatoria preference notification: {e}")

        return self.get_preferences(user, db)
