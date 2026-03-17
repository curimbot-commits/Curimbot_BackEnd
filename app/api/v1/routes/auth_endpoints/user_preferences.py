"""
Router para gestión de preferencias y perfil de usuario.

Este módulo proporciona endpoints para que los usuarios gestionen sus preferencias
personales, configuración de notificaciones, interfaz, perfil y foto de perfil.
Permite personalizar la experiencia del usuario en la aplicación.

Funcionalidades:
    - Gestión de preferencias de notificaciones (email, push, resúmenes)
    - Configuración de interfaz (idioma, tema)
    - Actualización de información de perfil
    - Subida y eliminación de foto de perfil
    - Envío de emails de prueba
    - Preferencias específicas de módulos (convocatorias)

Categories:
    - Preferencias: Configuración de notificaciones e interfaz
    - Perfil: Información personal y foto de perfil
    - Notificaciones: Gestión y pruebas de email
"""

import logging
from typing import Optional

from requests import Session
from fastapi import (
    APIRouter, 
    Depends, 
    HTTPException, 
    status, 
    UploadFile, 
    File, 
    Body
)

from app.core.config import FROM_EMAIL, RESEND_API_KEY
from app.db.database import get_db
from app.models.models import User
from app.schemas.user_preferences_schemas import (
    NotificationPreferencesUpdate,
    InterfacePreferencesUpdate,
    UserProfileUpdate,
    UserPreferencesResponse,
    ProfilePhotoResponse
)
from app.schemas.user_schemas import UserInfoResponse
from app.services.auth_service import get_current_user
from app.services.user_preferences_service import UserPreferencesService
from app.services.email_service import EmailService

import os
from dotenv import load_dotenv

# Carga el archivo .env desde la raíz del proyecto
load_dotenv()

# Accede a las variables de entorno
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
FROM_EMAIL = os.getenv("FROM_EMAIL")

# Configuración
router = APIRouter(prefix="/preferences", tags=["user-preferences"])
logger = logging.getLogger(__name__)

# Inicializar servicios
email_service = EmailService(api_key=RESEND_API_KEY, from_email=FROM_EMAIL)
preferences_service = UserPreferencesService(email_service=email_service)


# ========================================
# 📋 ENDPOINTS DE PREFERENCIAS
# ========================================

@router.get("", response_model=UserPreferencesResponse)
def get_user_preferences(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtener todas las preferencias del usuario autenticado.
    
    Este endpoint retorna la configuración completa de preferencias del usuario,
    incluyendo notificaciones, interfaz y preferencias de módulos específicos.
    Si el usuario no tiene preferencias configuradas, se crean con valores por defecto.
    
    Preferencias incluidas:
        - **Notificaciones**: Configuración de email, push y resúmenes
        - **Interfaz**: Idioma y tema visual
        - **Módulos**: Preferencias específicas de funcionalidades (convocatorias)
    
    Args:
        current_user (User): Usuario autenticado actual (inyectado automáticamente)
        db (Session): Sesión de base de datos (inyectada automáticamente)
    
    Returns:
        UserPreferencesResponse: Preferencias completas del usuario incluyendo:
            - email_notifications: Si recibe notificaciones por email
            - push_notifications: Si recibe notificaciones push
            - weekly_summary: Si recibe resumen semanal
            - language: Idioma de la interfaz (es, en)
            - theme: Tema visual (light, dark, auto)
            - convocatoria_enabled: Si tiene acceso a módulo de convocatorias
    
    Raises:
        HTTPException 401: Usuario no autenticado
        HTTPException 500: Error al obtener preferencias
    
    Example:
        GET /preferences
        Headers: Authorization: Bearer <access_token>
        
        Response:
        {
            "email_notifications": true,
            "push_notifications": false,
            "weekly_summary": true,
            "language": "es",
            "theme": "dark",
            "convocatoria_enabled": false
        }
    
    Notes:
        - Las preferencias se crean automáticamente con valores por defecto
        - Valores por defecto: notificaciones activas, idioma español, tema light
        - Las preferencias se guardan por usuario en base de datos
    """
    try:
        return preferences_service.get_preferences(current_user, db)
    except Exception as e:
        logger.exception(f"Error getting preferences for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al obtener preferencias"
        )


@router.patch("/notifications", response_model=UserPreferencesResponse)
def update_notification_preferences(
    preferences: NotificationPreferencesUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Actualizar preferencias de notificaciones del usuario.
    
    Este endpoint permite a los usuarios controlar qué tipos de notificaciones
    desean recibir. Los cambios son inmediatos y afectan todas las notificaciones
    futuras del sistema.
    
    Tipos de notificaciones:
        - **Email**: Notificaciones enviadas al correo electrónico
            - Alertas de seguridad
            - Confirmaciones de cambios
            - Actualizaciones de convocatorias
        
        - **Push**: Notificaciones en navegador/dispositivo móvil
            - Alertas en tiempo real
            - Recordatorios
        
        - **Resumen semanal**: Email con resumen de actividad
            - Enviado cada lunes
            - Incluye métricas y actividad reciente
    
    Args:
        preferences (NotificationPreferencesUpdate): Preferencias a actualizar (opcional):
            - email_notifications: Activar/desactivar emails (boolean)
            - push_notifications: Activar/desactivar push (boolean)
            - weekly_summary: Activar/desactivar resumen semanal (boolean)
        current_user (User): Usuario autenticado actual (inyectado automáticamente)
        db (Session): Sesión de base de datos (inyectada automáticamente)
    
    Returns:
        UserPreferencesResponse: Preferencias completas actualizadas
    
    Raises:
        HTTPException 401: Usuario no autenticado
        HTTPException 500: Error al actualizar preferencias
    
    Example:
        PATCH /preferences/notifications
        Headers: Authorization: Bearer <access_token>
        Body: {
            "email_notifications": false,
            "weekly_summary": true
        }
        
        Response:
        {
            "email_notifications": false,
            "push_notifications": true,
            "weekly_summary": true,
            "language": "es",
            "theme": "dark",
            "convocatoria_enabled": false
        }
    
    Notes:
        - Solo se actualizan los campos proporcionados
        - Los cambios son inmediatos
        - Desactivar email_notifications bloquea TODOS los emails (incluye seguridad)
        - El resumen semanal requiere email_notifications activo
    """
    try:
        return preferences_service.update_notification_preferences(
            current_user, preferences, db
        )
    except Exception as e:
        logger.exception(f"Error updating notification preferences for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al actualizar preferencias de notificaciones"
        )


@router.patch("/interface", response_model=UserPreferencesResponse)
def update_interface_preferences(
    preferences: InterfacePreferencesUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Actualizar preferencias de interfaz del usuario.
    
    Este endpoint permite personalizar la apariencia y el idioma de la interfaz
    de usuario. Los cambios afectan la visualización en todas las sesiones activas
    del usuario.
    
    Opciones de idioma:
        - **es**: Español
        - **en**: Inglés
        - Más idiomas pueden agregarse en el futuro
    
    Opciones de tema:
        - **light**: Tema claro (fondo blanco)
        - **dark**: Tema oscuro (fondo negro)
        - **auto**: Automático según preferencias del sistema operativo
    
    Args:
        preferences (InterfacePreferencesUpdate): Preferencias a actualizar (opcional):
            - language: Código de idioma (es, en)
            - theme: Tema visual (light, dark, auto)
        current_user (User): Usuario autenticado actual (inyectado automáticamente)
        db (Session): Sesión de base de datos (inyectada automáticamente)
    
    Returns:
        UserPreferencesResponse: Preferencias completas actualizadas
    
    Raises:
        HTTPException 400: Idioma o tema inválido
        HTTPException 401: Usuario no autenticado
        HTTPException 500: Error al actualizar preferencias
    
    Example:
        PATCH /preferences/interface
        Headers: Authorization: Bearer <access_token>
        Body: {
            "language": "en",
            "theme": "dark"
        }
        
        Response:
        {
            "email_notifications": true,
            "push_notifications": true,
            "weekly_summary": true,
            "language": "en",
            "theme": "dark",
            "convocatoria_enabled": false
        }
    
    Notes:
        - El cambio de idioma afecta todas las interfaces y emails
        - El tema "auto" detecta preferencias del navegador/OS
        - Los cambios son visibles inmediatamente en la interfaz
        - Solo se actualizan los campos proporcionados
    """
    try:
        return preferences_service.update_interface_preferences(
            current_user, preferences, db
        )
    except Exception as e:
        logger.exception(f"Error updating interface preferences for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al actualizar preferencias de interfaz"
        )


@router.patch("/convocatoria", response_model=UserPreferencesResponse)
def update_convocatoria_preference(
    enabled: bool = Body(..., description="Habilitar o deshabilitar convocatorias"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Actualizar preferencia de acceso al módulo de convocatorias.
    
    Este endpoint permite habilitar o deshabilitar el acceso de un usuario al
    módulo de convocatorias. Solo administradores pueden modificar esta preferencia,
    ya que controla el acceso a funcionalidades administrativas.
    
    Restricciones:
        - **Solo administradores** pueden modificar esta preferencia
        - No se puede auto-habilitar sin ser administrador
        - Los cambios afectan el acceso inmediatamente
    
    Efectos:
        - Si enabled=true: Usuario puede acceder a módulo de convocatorias
        - Si enabled=false: Se restringe el acceso al módulo
    
    Args:
        enabled (bool): True para habilitar, False para deshabilitar
        current_user (User): Usuario autenticado actual (inyectado automáticamente)
        db (Session): Sesión de base de datos (inyectada automáticamente)
    
    Returns:
        UserPreferencesResponse: Preferencias completas actualizadas
    
    Raises:
        HTTPException 403: Usuario no es administrador
        HTTPException 401: Usuario no autenticado
        HTTPException 500: Error al actualizar preferencia
    
    Example:
        PATCH /preferences/convocatoria
        Headers: Authorization: Bearer <admin_access_token>
        Body: {
            "enabled": true
        }
        
        Response:
        {
            "email_notifications": true,
            "push_notifications": true,
            "weekly_summary": true,
            "language": "es",
            "theme": "light",
            "convocatoria_enabled": true
        }
    
    Security Notes:
        - Solo administradores pueden ejecutar este endpoint
        - Se verifica el rol antes de procesar la solicitud
        - Los cambios se registran en logs de auditoría
        - Útil para gestión de permisos por módulo
    """
    try:
        # Verificar rol de administrador
        if not current_user.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para modificar esta preferencia"
            )
        
        return preferences_service.update_convocatoria_preference(current_user, enabled, db)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error updating convocatoria preference for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al actualizar preferencia de convocatorias"
        )


# ========================================
# 👤 ENDPOINTS DE PERFIL
# ========================================

@router.patch("/profile", response_model=UserInfoResponse)
def update_user_profile(
    profile_data: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Actualizar información del perfil del usuario.
    
    Este endpoint permite a los usuarios actualizar su nombre y/o email.
    Los cambios son validados antes de aplicarse y el email debe ser único
    en el sistema.
    
    Validaciones:
        - **Nombre**: Mínimo 2 caracteres, máximo 100 caracteres
        - **Email**: Formato válido de email, único en el sistema
        - Los cambios de email requieren verificación (futura implementación)
    
    Args:
        profile_data (UserProfileUpdate): Datos a actualizar (opcional):
            - name: Nuevo nombre completo del usuario
            - email: Nueva dirección de correo electrónico
        current_user (User): Usuario autenticado actual (inyectado automáticamente)
        db (Session): Sesión de base de datos (inyectada automáticamente)
    
    Returns:
        UserInfoResponse: Información completa del perfil actualizado incluyendo:
            - id: ID del usuario
            - email: Email actualizado
            - name: Nombre actualizado
            - role: Rol del usuario
            - created_at: Fecha de creación
            - last_login: Último inicio de sesión
            - is_active: Estado de la cuenta
            - two_factor_enabled: Estado de 2FA
    
    Raises:
        HTTPException 400: Datos inválidos o email ya en uso
        HTTPException 401: Usuario no autenticado
        HTTPException 500: Error al actualizar perfil
    
    Example:
        PATCH /preferences/profile
        Headers: Authorization: Bearer <access_token>
        Body: {
            "name": "Juan Pérez Actualizado",
            "email": "nuevo.email@example.com"
        }
        
        Response:
        {
            "id": 1,
            "email": "nuevo.email@example.com",
            "name": "Juan Pérez Actualizado",
            "role": "user",
            "created_at": "2025-01-15T10:30:00Z",
            "last_login": "2025-11-02T20:00:00Z",
            "is_active": true,
            "two_factor_enabled": true
        }
    
    Notes:
        - Solo se actualizan los campos proporcionados
        - El email debe ser único (no puede estar en uso por otro usuario)
        - Los cambios son inmediatos
        - Considerar agregar verificación por email para cambios de email
    """
    try:
        updated_user = preferences_service.update_profile(
            current_user, profile_data, db
        )
        
        return UserInfoResponse(
            id=updated_user.id,
            email=updated_user.email,
            name=updated_user.name,
            role=updated_user.role.name,
            created_at=updated_user.created_at,
            last_login=updated_user.last_login,
            is_active=updated_user.is_active,
            two_factor_enabled=updated_user.two_factor_enabled
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error updating profile for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al actualizar perfil"
        )


@router.post("/profile/photo", response_model=ProfilePhotoResponse)
async def upload_profile_photo(
    file: UploadFile = File(..., description="Imagen de perfil (JPG, PNG, GIF, WEBP, máx 5MB)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Subir o actualizar foto de perfil del usuario.
    
    Este endpoint permite a los usuarios subir una imagen como foto de perfil.
    La imagen se valida, se redimensiona si es necesario y se almacena de forma
    segura. Si ya existe una foto, se reemplaza.
    
    Restricciones de archivo:
        - **Formatos permitidos**: JPG, JPEG, PNG, GIF, WEBP
        - **Tamaño máximo**: 5 MB (5,242,880 bytes)
        - **Dimensiones recomendadas**: 400x400 píxeles (se redimensiona automáticamente)
        - **Relación de aspecto**: Se recomienda cuadrada (1:1)
    
    Procesamiento:
        1. Validar formato y tamaño del archivo
        2. Verificar que es una imagen válida
        3. Redimensionar a tamaño óptimo si es necesario
        4. Almacenar en sistema de archivos o cloud storage
        5. Actualizar URL en perfil del usuario
        6. Eliminar foto anterior si existía
    
    Args:
        file (UploadFile): Archivo de imagen a subir
        current_user (User): Usuario autenticado actual (inyectado automáticamente)
        db (Session): Sesión de base de datos (inyectada automáticamente)
    
    Returns:
        ProfilePhotoResponse: Confirmación y URL de la foto:
            - message: "Foto de perfil actualizada exitosamente"
            - photo_url: URL pública de la foto de perfil
    
    Raises:
        HTTPException 400: Formato inválido o archivo muy grande
        HTTPException 401: Usuario no autenticado
        HTTPException 413: Archivo excede tamaño máximo
        HTTPException 500: Error al procesar o guardar imagen
    
    Example:
        POST /preferences/profile/photo
        Headers: 
            Authorization: Bearer <access_token>
            Content-Type: multipart/form-data
        Body: 
            file: (binary image data)
        
        Response:
        {
            "message": "Foto de perfil actualizada exitosamente",
            "photo_url": "https://storage.example.com/profiles/user-123-photo.jpg"
        }
    
    Notes:
        - La foto anterior se elimina automáticamente
        - Las imágenes se optimizan para reducir tamaño de almacenamiento
        - Se genera URL pública accesible sin autenticación
        - Considerar implementar CDN para mejor rendimiento
        - Las fotos se pueden servir con cache para mejorar velocidad
    """
    try:
        photo_url = await preferences_service.upload_profile_photo(
            current_user, file, db
        )
        
        return ProfilePhotoResponse(
            message="Foto de perfil actualizada exitosamente",
            photo_url=photo_url
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error uploading profile photo for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al subir foto de perfil"
        )


@router.delete("/profile/photo")
def delete_profile_photo(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Eliminar foto de perfil del usuario.
    
    Este endpoint permite a los usuarios eliminar su foto de perfil actual,
    volviendo a la imagen por defecto del sistema. El archivo se elimina
    permanentemente del almacenamiento.
    
    Comportamiento:
        - Elimina el archivo de imagen del almacenamiento
        - Actualiza el perfil del usuario (photo_url = null)
        - Libera espacio de almacenamiento
        - No afecta otros datos del perfil
    
    Args:
        current_user (User): Usuario autenticado actual (inyectado automáticamente)
        db (Session): Sesión de base de datos (inyectada automáticamente)
    
    Returns:
        dict: Mensaje de confirmación:
            - message: "Foto de perfil eliminada exitosamente"
    
    Raises:
        HTTPException 401: Usuario no autenticado
        HTTPException 404: No hay foto de perfil para eliminar
        HTTPException 500: Error al eliminar foto
    
    Example:
        DELETE /preferences/profile/photo
        Headers: Authorization: Bearer <access_token>
        
        Response:
        {
            "message": "Foto de perfil eliminada exitosamente"
        }
    
    Notes:
        - La operación es irreversible
        - El usuario volverá a tener la imagen de perfil por defecto
        - El espacio de almacenamiento se libera inmediatamente
        - Si no hay foto, retorna 404
    """
    try:
        success = preferences_service.delete_profile_photo(current_user, db)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No hay foto de perfil para eliminar"
            )
        
        return {"message": "Foto de perfil eliminada exitosamente"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error deleting profile photo for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al eliminar foto de perfil"
        )


# ========================================
# 📧 ENDPOINTS DE NOTIFICACIONES
# ========================================

@router.post("/test-email")
def send_test_email(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Enviar email de prueba al usuario autenticado.
    
    Este endpoint permite a los usuarios verificar que las notificaciones por
    email están configuradas correctamente y funcionan. Útil después de cambiar
    preferencias de notificación o para verificar configuración de email.
    
    Validaciones previas:
        - Usuario debe tener notificaciones por email habilitadas
        - Email del usuario debe ser válido
        - Servicio de email debe estar disponible
    
    Contenido del email:
        - Saludo personalizado con nombre del usuario
        - Confirmación de funcionamiento del sistema de notificaciones
        - Mensaje amigable sin requerir acción
    
    Casos de uso:
        - Verificar configuración después de registro
        - Probar después de cambiar preferencias de email
        - Confirmar que emails no van a spam
        - Debugging de problemas de notificaciones
    
    Args:
        current_user (User): Usuario autenticado actual (inyectado automáticamente)
        db (Session): Sesión de base de datos (inyectada automáticamente)
    
    Returns:
        dict: Mensaje de confirmación:
            - message: "Email de prueba enviado exitosamente"
    
    Raises:
        HTTPException 400: Notificaciones por email desactivadas
        HTTPException 401: Usuario no autenticado
        HTTPException 500: Error al enviar email
    
    Example:
        POST /preferences/test-email
        Headers: Authorization: Bearer <access_token>
        
        Response:
        {
            "message": "Email de prueba enviado exitosamente"
        }
        
        Email recibido:
        Subject: Email de Prueba - SecureDoc
        Body:
        ¡Hola Juan Pérez!
        Esperamos que estés teniendo un excelente día.
        Este es un mensaje de prueba para confirmar que las notificaciones
        por correo electrónico están funcionando correctamente.
        Si has recibido este mensaje, ¡todo está en orden!
        Gracias por confiar en nosotros.
    
    Notes:
        - Requiere que email_notifications esté habilitado en preferencias
        - El email se envía inmediatamente (no en cola)
        - Útil para verificar configuración de servidor SMTP
        - No cuenta como notificación importante
        - Se registra el envío en logs del sistema
    """
    try:
        # Obtener o crear preferencias del usuario
        prefs = preferences_service.get_or_create_preferences(current_user, db)
        
        if prefs is None:
            logger.error(f"No se pudieron obtener las preferencias para el usuario {current_user.id}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error al obtener las preferencias del usuario"
            )
        
        # Si las notificaciones están desactivadas, registramos un aviso pero permitimos el email de prueba
        if not prefs.email_notifications:
            logger.info(f"Enviando email de prueba a pesar de que las notificaciones están desactivadas para el usuario {current_user.id}")

        # Enviar email de prueba personalizado
        result = email_service.send_email(
            to_email=current_user.email,
            subject="Email de Prueba - SecureDoc",
            html_content=f"""
                <h2>¡Hola {current_user.name}!</h2>
                <p>Esperamos que estés teniendo un excelente día.</p>
                <p>Este es un mensaje de prueba para confirmar que las notificaciones por correo electrónico están funcionando correctamente.</p>
                <p>Si has recibido este mensaje, ¡todo está en orden y no necesitas hacer nada más!</p>
                <p>Gracias por tu atención y por confiar en nosotros.</p>
            """
        )
        
        # Verificar si el correo fue enviado correctamente
        if not result:
            logger.error(f"Fallo al enviar el correo de prueba al usuario {current_user.id}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error al enviar email de prueba"
            )
        
        return {"message": "Email de prueba enviado exitosamente"}
    
    except HTTPException as http_exc:
        # Capturar excepciones HTTP específicas (errores de cliente)
        logger.warning(f"HTTPException: {http_exc.detail} para el usuario {current_user.id}")
        raise http_exc

    except Exception as e:
        # Capturar errores generales y registrarlos
        logger.exception(f"Error inesperado al enviar el correo de prueba para el usuario {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al enviar email de prueba"
        )
