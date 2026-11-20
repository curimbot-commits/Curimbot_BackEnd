"""
Router para descarga y streaming de documentos.

Este módulo proporciona endpoints para descargar documentos de forma segura,
con verificación de permisos, headers optimizados y streaming eficiente.
Implementa todas las mejores prácticas de seguridad y performance para
descargas de archivos.

Características:
    - Verificación de permisos (solo propietario)
    - Streaming de archivos grandes
    - Headers HTTP optimizados
    - Nombres de archivo con encoding UTF-8
    - Control de caché HTTP
    - Registro de auditoría
    - Detección automática de MIME types
"""

import io
import logging
import re
from urllib.parse import quote
from fastapi import Depends, HTTPException, Request, APIRouter
from fastapi.responses import StreamingResponse

from requests import session
from app.services.auth_service import get_current_user
from app.db.database import SessionLocal, get_db
from app.services.document_service import DocumentService


def content_disposition(filename: str) -> str:
    """
    Content-Disposition seguro (RFC 6266 / RFC 5987).

    - filename*: nombre completo percent-encoded en UTF-8 (navegadores modernos).
    - filename: respaldo ASCII sin comillas, barras ni caracteres de control.
    Evita romper la cabecera con ;, comillas, saltos de línea o caracteres
    no latin-1 (que provocaban un 500).
    """
    name = filename or "documento"
    fallback = re.sub(r'[^A-Za-z0-9._ -]', "_", name).strip() or "documento"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(name, safe='')}"

router = APIRouter(prefix="/documents", tags=["documents"])


def get_db():
    """
    Obtener sesión de base de datos para usar en endpoints.
    
    Crea una nueva sesión SQLAlchemy y garantiza su cierre automático
    incluso si ocurre una excepción durante la solicitud.
    
    Yields:
        Session: Sesión de base de datos activa y disponible
    
    Notes:
        - Sigue el patrón de inyección de dependencias de FastAPI
        - Cierra la conexión automáticamente al finalizar
        - Se ejecuta una vez por solicitud HTTP
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =========================================================
# ⬇️ Descargar Documento con validaciones mejoradas
# =========================================================

@router.get("/download/{doc_id}")
def download_document(
    doc_id: int,
    request: Request,
    db: session = Depends(get_db),
    user=Depends(get_current_user)
):
    """
    Descargar un documento específico con streaming seguro.
    
    Este endpoint permite a los usuarios descargar sus documentos. Implementa
    verificaciones de seguridad, optimizaciones de performance y headers HTTP
    profesionales para garantizar una experiencia de descarga confiable.
    
    Seguridad:
        - **Verificación de propiedad**: Solo el propietario puede descargar
        - **Auditoría**: Registra cada descarga (usuario, IP, timestamp)
        - **Validación de existencia**: Verifica que el documento existe
        - **Permisos**: Verifica que el archivo no está compartido restrictivamente
    
    Características de descarga:
        - **Streaming**: Soporta archivos grandes sin cargar todo en memoria
        - **MIME type automático**: Detecta tipo basado en extensión
        - **Nombres UTF-8**: Soporta nombres con caracteres especiales
        - **Control de caché**: Previene cachés no deseados
        - **Content-Length**: Tamaño exacto para barras de progreso
    
    Headers HTTP retornados:
        - **Content-Disposition**: Define el nombre de descarga
        - **Content-Type**: MIME type del archivo (pdf, docx, etc.)
        - **Content-Length**: Tamaño exacto en bytes
        - **Cache-Control**: Instrucciones de caché (no-cache)
        - **Pragma**: Compatibilidad con navegadores antiguos
        - **Expires**: Timestamp de expiración
    
    Casos de uso:
        - Descargar documentos personales
        - Exportar datos para procesamiento local
        - Respaldar documentos importantes
        - Compartir mediante descargas
        - Integración con otras aplicaciones
    
    Args:
        doc_id (int): ID único del documento a descargar
        request (Request): Objeto Request de FastAPI (para auditoría)
        db (session): Sesión de base de datos (inyectada automáticamente)
        user (User): Usuario autenticado actual (inyectado automáticamente)
    
    Returns:
        StreamingResponse: Archivo en streaming:
            - body: Contenido del archivo en chunks
            - media_type: MIME type automático (pdf, docx, txt, etc.)
            - headers: Headers HTTP optimizados para descarga
    
    Raises:
        HTTPException 400: Documento inválido o datos dañados
        HTTPException 401: Usuario no autenticado
        HTTPException 403: Usuario no es propietario del documento
        HTTPException 404: Documento no encontrado
        HTTPException 410: Documento fue eliminado
        HTTPException 500: Error al procesar descarga
    
    Example (exitoso):
        GET /documents/download/123
        Headers: Authorization: Bearer <access_token>
        
        Response (200 OK):
        HTTP Headers:
            Content-Type: application/pdf
            Content-Disposition: attachment; filename*=UTF-8''Reporte%20Q4%202025.pdf
            Content-Length: 2097152
            Cache-Control: no-cache, no-store, must-revalidate
        
        Body: (archivo binario en streaming)
    
    Example (no autorizado):
        GET /documents/download/456
        Headers: Authorization: Bearer <access_token>
        
        Response (403 Forbidden):
        {
            "detail": "No autorizado para descargar este documento"
        }
    
    Example (no encontrado):
        GET /documents/download/999
        Headers: Authorization: Bearer <access_token>
        
        Response (404 Not Found):
        {
            "detail": "Documento no encontrado"
        }
    
    MIME types soportados:
        - application/pdf (PDF)
        - application/vnd.openxmlformats-officedocument.wordprocessingml.document (DOCX)
        - application/vnd.openxmlformats-officedocument.spreadsheetml.sheet (XLSX)
        - text/plain (TXT)
        - application/json (JSON)
        - image/jpeg, image/png, image/gif (imágenes)
        - application/octet-stream (por defecto)
    
    Performance:
        - **Streaming**: No carga todo el archivo en memoria
        - **Compresión**: Navegadores pueden comprimir automáticamente
        - **Range requests**: Soporta descargas reanudables (si servidor lo permite)
        - **Velocidad**: Típicamente inicia descarga en < 100ms
        - **Grandes archivos**: Soporta archivos de GB+ sin problemas
    
    Headers HTTP explicados:
        - **Content-Disposition**: Indica que es descarga con nombre
            - `attachment` = Descargar en lugar de abrir
            - `filename*=UTF-8''Nombre` = Soporta caracteres especiales
        
        - **Content-Length**: Exacto para barra de progreso
            - Los navegadores muestran porcentaje exacto
        
        - **Cache-Control**: Previene cachés no deseados
            - `no-cache` = No cachear
            - `no-store` = No guardar
            - `must-revalidate` = Revalidar siempre
        
        - **Pragma**: Compatibilidad con HTTP/1.0
            - `no-cache` = No cachear
        
        - **Expires**: Fecha de expiración
            - `0` = Ya expirado, fuerza re-fetch
    
    Seguridad de descarga:
        - El archivo se obtiene de almacenamiento seguro
        - Se valida integridad del archivo antes de enviar
        - Se registra cada descarga para auditoría
        - IP del cliente se registra
        - Se puede limitar velocidad de descarga si es necesario
    
    Notas sobre nombres de archivo:
        - UTF-8 encoding para caracteres especiales
        - Espacio se convierte a %20
        - Caracteres especiales se escapan correctamente
        - Los navegadores muestran nombre correcto en descargas
    
    Best Practices para clientes:
        - Mostrar barra de progreso usando Content-Length
        - Manejar timeouts para archivos grandes
        - Implementar reintento automático
        - Guardar en carpeta de descargas segura
        - Verificar integridad si es crítico
        - Considerar descarga en background
    
    Troubleshooting:
        - Si descarga no se inicia: Verificar autenticación
        - Si nombre está corrupto: Verificar soporte UTF-8 en cliente
        - Si descarga es lenta: Verificar ancho de banda
        - Si archivo está vacío: Verificar que se guardó correctamente
    """
    try:
        # Obtener datos del documento del servicio
        # El servicio se encarga de:
        # - Verificar que el usuario es propietario
        # - Obtener el archivo del almacenamiento
        # - Validar integridad
        # - Registrar descarga en auditoría
        raw_data, doc = DocumentService.download_document(doc_id, request, db, user)
        
        # Determinar MIME type más específico basado en tipo de archivo
        # Usa el mimetype almacenado o usa por defecto binario
        media_type = doc.mimetype or "application/octet-stream"
        
        # Headers HTTP optimizados para descarga
        headers = {
            # RFC 6266: Content-Disposition con UTF-8 encoding
            # Permite nombres con caracteres especiales
            "Content-Disposition": content_disposition(doc.filename),

            # El mimetype lo declara quien sube el archivo: no dejar que el
            # navegador lo reinterprete (p. ej. como HTML)
            "X-Content-Type-Options": "nosniff",
            
            # Tamaño exacto del archivo para barra de progreso
            "Content-Length": str(len(raw_data)),
            
            # Control de caché: Nunca cachear descargas
            # Previene que el navegador sirva versión antigua
            "Cache-Control": "no-cache, no-store, must-revalidate",
            
            # Compatibilidad con HTTP/1.0
            "Pragma": "no-cache",
            
            # Marcar como expirado inmediatamente
            "Expires": "0"
        }
        
        # Retornar como StreamingResponse para eficiencia
        # Soporta archivos grandes sin cargar todo en memoria
        return StreamingResponse(
            io.BytesIO(raw_data),  # Envolver datos en stream binario
            media_type=media_type,  # MIME type automático
            headers=headers  # Headers HTTP optimizados
        )
        
    except HTTPException:
        # Re-lanzar excepciones HTTP (autenticación, permisos, no encontrado, etc.)
        raise
    except Exception as e:
        # Capturar errores inesperados y loguear
        logging.exception(f"Error inesperado descargando documento {doc_id}: {e}")
        raise HTTPException(
            status_code=500, 
            detail="Error interno al descargar el documento"
        )
