"""
Router para recuperación de contraseña.

Este módulo implementa un sistema seguro de recuperación de contraseña mediante
tokens de un solo uso enviados por email. Incluye validación de tokens, cambio de
contraseña y limpieza automática de tokens expirados.

Flujo de recuperación:
    1. Usuario solicita recuperación con su email
    2. Sistema genera token único con expiración
    3. Se envía email con enlace de recuperación
    4. Usuario verifica el token
    5. Usuario establece nueva contraseña
    6. Sistema confirma cambio por email

Security Features:
    - Tokens de un solo uso con expiración de 1 hora
    - Respuestas genéricas para prevenir enumeración de usuarios
    - Validación estricta de contraseñas
    - Notificación por email de cambios exitosos
    - Limpieza automática de tokens expirados
"""

import logging
import os
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from app.db.database import get_db
from app.models.models import User
from app.schemas.password_reset_schemas import (
    PasswordResetRequest,
    PasswordResetVerify,
    PasswordResetConfirm,
    PasswordResetResponse,
    TokenValidationResponse
)
from app.services.email_service import EmailService
from app.services.notification_service import NotificationService
from app.services.password_reset_service import PasswordResetService

# Cargar variables de entorno
load_dotenv()

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
FROM_EMAIL = os.getenv("FROM_EMAIL")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:4200")

# Configuración
router = APIRouter(prefix="/password-reset", tags=["password-reset"])
logger = logging.getLogger(__name__)

# Inicializar servicios
email_service = EmailService(api_key=RESEND_API_KEY, from_email=FROM_EMAIL)
notification_service = NotificationService(email_service)
password_reset_service = PasswordResetService(
    notification_service=notification_service,
    frontend_url=FRONTEND_URL
)


@router.post("/request", response_model=PasswordResetResponse, status_code=status.HTTP_200_OK)
def request_password_reset(
    request_data: PasswordResetRequest,
    db: Session = Depends(get_db)
):
    """
    Solicitar recuperación de contraseña mediante email.
    
    Este endpoint inicia el proceso de recuperación de contraseña. Si el email
    existe en el sistema, se genera un token único y se envía un correo con
    instrucciones. Por razones de seguridad, siempre retorna el mismo mensaje
    exitoso independientemente de si el email existe o no.
    
    Flujo de seguridad:
        1. Verificar si el email existe en la base de datos
        2. Si existe, generar token único con expiración de 1 hora
        3. Guardar token en base de datos asociado al usuario
        4. Enviar email con enlace de recuperación
        5. Retornar mensaje genérico (mismo para email existente o no)
    
    Características de seguridad:
        - **Prevención de enumeración**: Respuesta idéntica para emails existentes y no existentes
        - **Tokens de un solo uso**: Cada token solo puede usarse una vez
        - **Expiración temporal**: Tokens expiran en 1 hora
        - **Rate limiting**: Limitar solicitudes por IP (implementado en capa externa)
        - **Enlace seguro**: URL incluye token único generado criptográficamente
    
    Args:
        request_data (PasswordResetRequest): Email del usuario que solicita recuperación
        db (Session): Sesión de base de datos (inyectada automáticamente)
    
    Returns:
        PasswordResetResponse: Respuesta genérica indicando que se envió el email:
            - message: "Si el correo está registrado, recibirás instrucciones"
            - success: True (siempre)
    
    Raises:
        HTTPException 500: Error interno al procesar la solicitud
    
    Example:
        POST /password-reset/request
        Body: {
            "email": "usuario@example.com"
        }
        
        Response:
        {
            "success": true,
            "message": "Si el correo está registrado, recibirás instrucciones para recuperar tu contraseña"
        }
    
    Security Notes:
        - NO revela si el email existe en el sistema (previene enumeración)
        - El token se envía SOLO por email, nunca en la respuesta HTTP
        - Los tokens son UUID v4 criptográficamente seguros
        - Se registran todos los intentos en logs para auditoría
        - Considerar implementar rate limiting por IP
    """
    try:
        result = password_reset_service.request_password_reset(
            email=request_data.email,
            db=db
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error in password reset request: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al procesar la solicitud"
        )


@router.post("/verify-token", response_model=TokenValidationResponse)
def verify_reset_token(
    verify_data: PasswordResetVerify,
    db: Session = Depends(get_db)
):
    """
    Verificar validez de un token de recuperación de contraseña.
    
    Este endpoint permite validar un token de recuperación antes de mostrar
    el formulario de nueva contraseña. Verifica que el token existe, no ha
    sido usado y no ha expirado.
    
    Validaciones realizadas:
        - Token existe en la base de datos
        - Token no ha sido usado previamente
        - Token no ha expirado (< 1 hora desde creación)
        - Token está asociado a un usuario válido
    
    Casos de uso:
        - Validar token antes de mostrar formulario de cambio
        - Mostrar mensaje de error si token inválido/expirado
        - Redirigir a solicitud nueva si token no es válido
    
    Args:
        verify_data (PasswordResetVerify): Token a verificar
        db (Session): Sesión de base de datos (inyectada automáticamente)
    
    Returns:
        TokenValidationResponse: Estado de validación del token:
            - valid: True si el token es válido, False si no
            - message: Descripción del estado ("Token válido" o "Token inválido o expirado")
    
    Raises:
        HTTPException 500: Error al verificar el token
    
    Example:
        POST /password-reset/verify-token
        Body: {
            "token": "550e8400-e29b-41d4-a716-446655440000"
        }
        
        Response (válido):
        {
            "valid": true,
            "message": "Token válido"
        }
        
        Response (inválido):
        {
            "valid": false,
            "message": "Token inválido o expirado"
        }
    
    Notes:
        - Este endpoint NO consume el token, solo lo valida
        - Puede llamarse múltiples veces con el mismo token
        - Útil para UX: verificar antes de solicitar contraseña
        - No revela detalles específicos del error por seguridad
    """
    try:
        token_record = password_reset_service.verify_reset_token(
            token=verify_data.token,
            db=db
        )
        
        if token_record:
            return TokenValidationResponse(
                valid=True,
                message="Token válido"
            )
        else:
            return TokenValidationResponse(
                valid=False,
                message="Token inválido o expirado"
            )
    except Exception as e:
        logger.exception(f"Error verifying token: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al verificar el token"
        )


@router.post("/reset", response_model=PasswordResetResponse)
def reset_password(
    reset_data: PasswordResetConfirm,
    db: Session = Depends(get_db)
):
    """
    Restablecer contraseña del usuario con token válido.
    
    Este endpoint completa el proceso de recuperación de contraseña. Valida
    el token, verifica que la nueva contraseña cumple requisitos de seguridad,
    actualiza la contraseña y envía confirmación por email. El token se marca
    como usado para prevenir reutilización.
    
    Flujo de operación:
        1. Validar que el token existe y no ha expirado
        2. Verificar que el token no ha sido usado
        3. Validar nueva contraseña contra requisitos de seguridad
        4. Hash de la nueva contraseña con bcrypt
        5. Actualizar contraseña en base de datos
        6. Marcar token como usado
        7. Enviar email de confirmación al usuario
        8. Registrar operación en logs de auditoría
    
    Requisitos de contraseña:
        - **Longitud mínima**: 8 caracteres
        - **Letra mayúscula**: Al menos una (A-Z)
        - **Letra minúscula**: Al menos una (a-z)
        - **Dígito numérico**: Al menos uno (0-9)
        - **Carácter especial**: Al menos uno (!@#$%^&*()_+-=[]{}|;:,.<>?)
        - **No común**: No puede ser una contraseña común conocida
    
    Args:
        reset_data (PasswordResetConfirm): Datos de recuperación incluyendo:
            - token: Token de recuperación válido
            - new_password: Nueva contraseña que cumple requisitos
        db (Session): Sesión de base de datos (inyectada automáticamente)
    
    Returns:
        PasswordResetResponse: Confirmación de la operación:
            - success: True si se cambió exitosamente
            - message: "Contraseña restablecida exitosamente"
    
    Raises:
        HTTPException 400: Token inválido, expirado o contraseña no cumple requisitos
        HTTPException 404: Token no encontrado o usuario no existe
        HTTPException 500: Error interno al restablecer contraseña
    
    Example:
        POST /password-reset/reset
        Body: {
            "token": "550e8400-e29b-41d4-a716-446655440000",
            "new_password": "NuevaContraseña123!"
        }
        
        Response:
        {
            "success": true,
            "message": "Contraseña restablecida exitosamente. Se ha enviado un email de confirmación."
        }
    
    Security Notes:
        - El token se invalida inmediatamente después de usarse
        - La contraseña se hashea con bcrypt antes de almacenarse
        - Se envía email de confirmación para alertar al usuario
        - Tokens expirados no pueden usarse (ventana de 1 hora)
        - Se registra la IP y timestamp del cambio en logs
        - Considerar invalidar sesiones activas después del cambio
    """
    try:
        result = password_reset_service.reset_password(
            token=reset_data.token,
            new_password=reset_data.new_password,
            db=db
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error resetting password: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al restablecer la contraseña"
        )


@router.delete("/cleanup-expired")
def cleanup_expired_tokens(
    db: Session = Depends(get_db)
):
    """
    Limpiar tokens de recuperación expirados de la base de datos.
    
    Este endpoint administrativo elimina permanentemente todos los tokens de
    recuperación que han expirado (más de 1 hora desde su creación). Útil
    para mantenimiento de base de datos y limpieza de datos obsoletos.
    
    Casos de uso:
        - **Cron job**: Ejecutar periódicamente (diariamente o semanalmente)
        - **Mantenimiento**: Limpieza manual de base de datos
        - **Optimización**: Reducir tamaño de tablas y mejorar rendimiento
        - **Auditoría**: Verificar cantidad de tokens expirados
    
    Criterios de eliminación:
        - Tokens con created_at > 1 hora en el pasado
        - Tokens ya usados (independiente de fecha)
        - Tokens asociados a usuarios eliminados
    
    Args:
        db (Session): Sesión de base de datos (inyectada automáticamente)
    
    Returns:
        dict: Resultado de la limpieza incluyendo:
            - message: Mensaje descriptivo con cantidad eliminada
            - deleted_count: Número de tokens eliminados
    
    Raises:
        HTTPException 500: Error al limpiar tokens expirados
    
    Example:
        DELETE /password-reset/cleanup-expired
        
        Response:
        {
            "message": "Se eliminaron 127 tokens expirados",
            "deleted_count": 127
        }
    
    Notes:
        - Este endpoint debería protegerse con autenticación de admin
        - Considerar implementar soft-delete para auditoría
        - Ejecutar durante horas de bajo tráfico si hay muchos tokens
        - Los tokens activos (< 1 hora) nunca se eliminan
        - La operación es irreversible
    
    Recommended Usage:
        - Configurar como cron job diario: 0 2 * * * (2 AM)
        - O ejecutar semanalmente durante ventana de mantenimiento
        - Monitorear deleted_count para detectar anomalías
    """
    try:
        deleted_count = password_reset_service.cleanup_expired_tokens(db)
        return {
            "message": f"Se eliminaron {deleted_count} tokens expirados",
            "deleted_count": deleted_count
        }
    except Exception as e:
        logger.exception(f"Error cleaning up tokens: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al limpiar tokens expirados"
        )


@router.get("/check-email")
def check_email_exists(email: str, db: Session = Depends(get_db)):
    """
    Verificar si un correo electrónico está registrado en el sistema.
    
    Este endpoint permite verificar la existencia de un email sin revelar
    información sensible. Útil para UX en formularios de recuperación.
    
    Advertencia de seguridad:
        Este endpoint puede usarse para enumerar usuarios del sistema.
        Considerar implementar rate limiting agresivo o eliminar si no
        es estrictamente necesario para la experiencia de usuario.
    
    Alternativas más seguras:
        - Usar el mismo flujo que /request (respuesta genérica)
        - Implementar CAPTCHA antes de verificar
        - Rate limiting estricto por IP (ej: 5 intentos/hora)
        - Registrar intentos sospechosos para análisis
    
    Args:
        email (str): Dirección de email a verificar (query parameter)
        db (Session): Sesión de base de datos (inyectada automáticamente)
    
    Returns:
        dict: Estado de existencia del email:
            - exists: True si el email está registrado, False si no
    
    Raises:
        HTTPException 500: Error al verificar el correo
    
    Example:
        GET /password-reset/check-email?email=usuario@example.com
        
        Response (existe):
        {
            "exists": true
        }
        
        Response (no existe):
        {
            "exists": false
        }
    
    Security Considerations:
        - **Vulnerabilidad**: Permite enumeración de usuarios registrados
        - **Mitigación**: Implementar rate limiting estricto
        - **Alternativa**: Considerar eliminar este endpoint
        - **Logging**: Registrar todas las consultas para detectar abuse
        - **CAPTCHA**: Requerir para prevenir scraping automatizado
    
    Recommendation:
        Si es posible, eliminar este endpoint y usar respuestas genéricas
        en /request para prevenir enumeración de usuarios. Si es necesario
        para UX, implementar protecciones robustas contra abuso.
    """
    try:
        user = db.query(User).filter(User.email == email).first()
        return {"exists": bool(user)}
    except Exception as e:
        logger.exception(f"Error checking email existence: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al verificar el correo"
        )
