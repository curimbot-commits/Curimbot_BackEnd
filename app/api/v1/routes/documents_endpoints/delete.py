"""
Router para operaciones de eliminación y gestión de documentos.

Este módulo proporciona endpoints para eliminar documentos de forma segura.
Implementa verificaciones de permisos, limpieza de archivos físicos,
actualización de registros de base de datos y auditoría completa.

Características de seguridad:
    - Verificación de propiedad del documento
    - Eliminación en cascada de datos relacionados
    - Registro de IP y timestamp del usuario
    - Auditoría de eliminaciones
    - Recuperación de espacio de almacenamiento
    - Confirmación de operación
"""

from fastapi import Depends, HTTPException, Request, APIRouter
import logging
from requests import session
from app.services.auth_service import get_current_user
from app.db.database import SessionLocal, get_db
from app.services.document_service import DocumentService

router = APIRouter(prefix="/documents", tags=["documents"])


def get_db():
    """
    Obtener sesión de base de datos para uso en endpoints.
    
    Crea una nueva sesión SQLAlchemy y la cierra automáticamente
    después de que se complete la solicitud, aunque ocurra una excepción.
    
    Yields:
        Session: Sesión de base de datos activa
    
    Notes:
        - Follows FastAPI dependency injection pattern
        - Ensures database connections are properly closed
        - Automatically handles transactions
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =========================================================
# 🗑️ Eliminar documento con confirmación
# =========================================================

@router.delete("/{doc_id}", response_model=dict)
def delete_document(
    doc_id: int,
    request: Request,
    db: session = Depends(get_db),
    user=Depends(get_current_user)
):
    """
    Eliminar un documento específico del sistema de forma segura.
    
    Este endpoint elimina un documento completamente del sistema, incluyendo
    el archivo físico y todos los registros asociados. La operación es segura
    y verifica permisos antes de proceder. Se registra toda la actividad para
    auditoría.
    
    Flujo de eliminación:
        1. Verificar que el usuario está autenticado
        2. Verificar que el documento existe
        3. Verificar que el usuario es propietario del documento
        4. Registrar la eliminación antes de proceder
        5. Obtener información del archivo a eliminar
        6. Eliminar archivo físico del almacenamiento
        7. Eliminar registros de base de datos (en cascada si aplica)
        8. Liberar espacio de cuota del usuario
        9. Confirmar operación con timestamp
    
    Seguridad:
        - **Verificación de propiedad**: Solo el propietario puede eliminar
        - **Validación de existencia**: Verificar que el documento existe
        - **Auditoría**: Registrar IP, timestamp, usuario y documento
        - **Transacciones**: Usar transacciones para consistencia
        - **Cascada segura**: Eliminar documentos relacionados de forma controlada
    
    Información registrada:
        - **User ID**: ID del usuario que realizó la eliminación
        - **User Email**: Email del usuario
        - **User IP**: Dirección IP desde donde se ejecutó
        - **Document ID**: ID del documento eliminado
        - **Document Name**: Nombre del documento
        - **Document Size**: Tamaño del documento (para cuota)
        - **Timestamp**: Cuándo ocurrió la eliminación
        - **User Agent**: Navegador/cliente usado (si disponible)
    
    Args:
        doc_id (int): ID único del documento a eliminar
        request (Request): Objeto Request de FastAPI (para obtener IP del cliente)
        db (session): Sesión de base de datos (inyectada automáticamente)
        user (User): Usuario autenticado actual (inyectado automáticamente)
    
    Returns:
        dict: Confirmación de eliminación incluyendo:
            - success: True si fue exitoso
            - message: "Documento eliminado exitosamente"
            - document_id: ID del documento eliminado
            - document_name: Nombre del documento que fue eliminado
            - freed_space_bytes: Espacio liberado en bytes
            - freed_space_formatted: Espacio liberado (formato legible)
            - deleted_at: Timestamp de cuándo fue eliminado (ISO 8601)
    
    Raises:
        HTTPException 400: Documento inválido o ya eliminado
        HTTPException 401: Usuario no autenticado
        HTTPException 403: Usuario no es propietario del documento
        HTTPException 404: Documento no encontrado
        HTTPException 500: Error interno al eliminar documento
    
    Example (exitoso):
        DELETE /documents/123
        Headers: Authorization: Bearer <access_token>
        
        Response (200 OK):
        {
            "success": true,
            "message": "Documento eliminado exitosamente",
            "document_id": 123,
            "document_name": "Reporte Q4 2025.pdf",
            "freed_space_bytes": 2097152,
            "freed_space_formatted": "2.0 MB",
            "deleted_at": "2025-11-02T20:41:00Z"
        }
    
    Example (no autorizado):
        DELETE /documents/456
        Headers: Authorization: Bearer <access_token>
        
        Response (403 Forbidden):
        {
            "detail": "No autorizado para eliminar este documento"
        }
    
    Example (no encontrado):
        DELETE /documents/999
        Headers: Authorization: Bearer <access_token>
        
        Response (404 Not Found):
        {
            "detail": "Documento no encontrado"
        }
    
    Security Notes:
        - **Solo propietario**: El usuario debe ser el propietario para eliminar
        - **Eliminación permanente**: La operación es irreversible
        - **Cascada**: Si el documento tiene versiones o comentarios, se eliminan
        - **Recuperación**: Se pueden recuperar desde backups durante período de retención
        - **Auditoría**: Se registra para investigación post-eliminación
        - **IP Logging**: Se registra la IP del cliente para seguridad
    
    Comportamiento de eliminación:
        - Archivo físico se elimina del almacenamiento
        - Registros de base de datos se marcan como deleted (soft delete)
        - O se eliminan completamente si se configura (hard delete)
        - Las búsquedas no retornarán el documento
        - Los compartimientos se revocan automáticamente
        - Las notificaciones se envían a colaboradores (si aplica)
    
    Performance:
        - La eliminación es asíncrona si el archivo es grande
        - Típicamente completa en < 1 segundo
        - Se libera la cuota inmediatamente en la BD
        - El espacio en disco se recupera según política de almacenamiento
    
    Best Practices:
        - Confirmar con usuario antes de eliminar (hacer desde frontend)
        - No recuperable, así que advertir claramente
        - Guardar cualquier información necesaria del documento ANTES de eliminar
        - Revisar el nombre del documento para evitar confusiones
        - Considerar eliminación programada (soft delete con retención)
    """
    try:
        # Extraer dirección IP del cliente para auditoría
        ip = getattr(request.client, 'host', 'unknown') if request.client else 'unknown'
        
        # Llamar al servicio de documentos para eliminar
        # El servicio se encarga de:
        # - Verificar permisos
        # - Eliminar archivo físico
        # - Actualizar base de datos
        # - Registrar auditoría
        result = DocumentService.delete_document(doc_id, user, db, ip)
        
        return result
        
    except HTTPException:
        # Re-lanzar excepciones HTTP tal cual (errores de validación, permisos, etc.)
        raise
    except Exception as e:
        # Capturar errores inesperados y registrar
        logging.exception(f"Error inesperado eliminando documento {doc_id}: {e}")
        raise HTTPException(
            status_code=500, 
            detail="Error interno del servidor"
        )
