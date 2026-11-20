"""
Router para Curim Assistant - Asistente inteligente de documentos.

Este módulo proporciona endpoints para interactuar con Curim, un asistente
inteligente basado en IA que permite hacer preguntas sobre documentos,
obtener respuestas contextualizadas, gestionar historial de conversaciones
y convertir texto a voz.

Características principales:
    - Búsqueda semántica en documentos
    - Preguntas y respuestas contextualizadas
    - Historial de conversaciones
    - Caché inteligente de respuestas
    - Sincronización de documentos con Curim
    - Conversión de texto a voz (TTS) con Edge TTS
    - Voces en múltiples idiomas

Componentes:
    - CurimService: Servicio principal de consultas
    - CacheManager: Gestión de caché de respuestas
    - Edge TTS: Conversión de texto a voz
"""

import io
import edge_tts
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.rate_limit import rate_limit
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Optional
import logging

from app.schemas.Curim_schemas import (
    CurimQueryRequest,
    CurimResponse,
    ConversationHistory,
    CurimStatus,
    DocumentSyncRequest,
    DocumentSyncResponse
)
from app.services.auth_service import get_current_user
from app.services.Curim import CurimService
from app.models.models import User
from app.db.database import SessionLocal

router = APIRouter(prefix="/assistant", tags=["Curim Assistant"])

# Instancia global del servicio
Curim_service = CurimService()
logger = logging.getLogger(__name__)


def get_db():
    """
    Obtener sesión de base de datos para usar en endpoints.
    
    Crea una nueva sesión SQLAlchemy y garantiza su cierre automático
    incluso si ocurre una excepción durante la solicitud.
    
    Yields:
        Session: Sesión de base de datos activa y disponible
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ===========================
# ENDPOINTS - CONSULTAS
# ===========================

@router.post("/query", response_model=CurimResponse, dependencies=[Depends(rate_limit(30, 60))])
async def ask_Curim(
    request: CurimQueryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Realizar pregunta a Curim sobre documentos del usuario.
    
    Este endpoint permite hacer preguntas sobre los documentos indexados
    del usuario. Curim busca información relevante usando búsqueda
    semántica y genera respuestas contextualizadas basadas en el contenido.
    
    Búsqueda semántica:
        - Convierte pregunta a vector (embedding)
        - Busca chunks similares en Curim
        - Ordena por relevancia
        - Genera respuesta con fuentes
    
    Caché inteligente:
        - Cachea preguntas frecuentes
        - Acelera respuestas para preguntas similares
        - Se puede desactivar por pregunta
    
    Alcance de documentos:
        - **document_ids=None**: Busca en todos los documentos del usuario
        - **document_ids=[1,2,3]**: Busca solo en documentos especificados
        - Útil para enfocar búsqueda en contexto específico
    
    Args:
        request (CurimQueryRequest): Solicitud con:
            - question: Pregunta del usuario (requerido)
            - document_ids: Documentos a buscar (opcional, None = todos)
            - use_cache: Usar caché si disponible (default: True)
        
        current_user (User): Usuario autenticado (inyectado automáticamente)
        db (Session): Sesión de base de datos (inyectada automáticamente)
    
    Returns:
        CurimResponse: Respuesta del asistente:
            - answer: Respuesta generada por IA
            - sources: Documentos y chunks usados en la respuesta
            - confidence: Confianza de la respuesta (0-1)
            - cached: Si fue respuesta cacheada
            - processing_time_ms: Tiempo de procesamiento
            - conversation_id: ID para historial
            - model_used: Modelo de IA usado
    
    Raises:
        HTTPException 400: Pregunta vacía o inválida
        HTTPException 401: Usuario no autenticado
        HTTPException 404: Documentos no encontrados
        HTTPException 500: Error en procesamiento
    
    Example:
        POST /assistant/query
        Headers: Authorization: Bearer <access_token>
        Body: {
            "question": "¿Cuáles fueron los ingresos totales en Q4 2025?",
            "document_ids": [1, 2, 3],
            "use_cache": true
        }
        
        Response (200 OK):
        {
            "answer": "Los ingresos totales en Q4 2025 fueron $2.5 millones, "
                     "representando un aumento del 15% respecto a Q3...",
            "sources": [
                {
                    "document_id": 1,
                    "document_name": "Reporte Q4 2025.pdf",
                    "chunks": [
                        {
                            "text": "Los ingresos totales alcanzaron $2.5M...",
                            "relevance": 0.95
                        }
                    ]
                }
            ],
            "confidence": 0.92,
            "cached": false,
            "processing_time_ms": 1240,
            "conversation_id": 42,
            "model_used": "gpt-4"
        }
    
    Casos de uso:
        - Búsqueda de información en reportes
        - Análisis de datos de múltiples documentos
        - Preguntas sobre políticas o procedimientos
        - Resumen de información relevante
        - Q&A sobre documentos completos
    
    Performance:
        - Caché: < 50ms para preguntas cacheadas
        - Búsqueda: 200-1000ms según cantidad de documentos
        - Escalable a documentos muy grandes
    
    Security:
        - Solo busca en documentos del usuario autenticado
        - Historial se guarda con usuario asociado
        - Respuestas personalizadas por usuario
    """
    try:
        result = Curim_service.ask_question(
            db=db,
            user=current_user,
            question=request.question,
            document_ids=request.document_ids,
            use_cache=request.use_cache
        )
        
        return CurimResponse(**result)
    
    except Exception as e:
        logger.exception(f"Error procesando pregunta para usuario {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error procesando pregunta: {str(e)}"
        )


@router.get("/history", response_model=List[ConversationHistory])
async def get_conversation_history(
    conversation_id: Optional[int] = None,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtener historial de conversaciones con Curim.
    
    Retorna el historial de preguntas y respuestas anteriores del usuario.
    Útil para referenciar conversaciones pasadas, contexto y análisis.
    
    Filtrado:
        - **conversation_id=None**: Todas las conversaciones del usuario
        - **conversation_id=42**: Conversación específica completa
        - **limit=50**: Últimos N mensajes (default 50)
    
    Estructura del historial:
        - Pregunta original
        - Respuesta de Curim
        - Documentos usados
        - Timestamp de la conversación
        - Relevancia/confianza
    
    Args:
        conversation_id (Optional[int]): ID de conversación específica.
            - None: Todas las conversaciones
            - >0: Conversación específica
        
        limit (int): Máximo de mensajes a retornar (default: 50)
        
        current_user (User): Usuario autenticado (inyectado automáticamente)
        db (Session): Sesión de base de datos (inyectada automáticamente)
    
    Returns:
        List[ConversationHistory]: Lista de mensajes ordenados cronológicamente:
            - id: ID único del mensaje
            - conversation_id: ID de la conversación
            - question: Pregunta del usuario
            - answer: Respuesta de Curim
            - sources: Documentos usados
            - timestamp: Cuándo ocurrió
            - confidence: Confianza de respuesta
    
    Raises:
        HTTPException 401: Usuario no autenticado
        HTTPException 404: Conversación no encontrada
        HTTPException 500: Error al obtener historial
    
    Example 1 (todas las conversaciones):
        GET /assistant/history?limit=10
        Headers: Authorization: Bearer <access_token>
        
        Response:
        [
            {
                "id": 100,
                "conversation_id": 5,
                "question": "¿Cuáles fueron los gastos?",
                "answer": "Los gastos fueron...",
                "sources": ["Reporte Financiero.pdf"],
                "timestamp": "2025-11-02T20:50:00Z",
                "confidence": 0.88
            },
            {
                "id": 99,
                "conversation_id": 5,
                "question": "¿Cuáles fueron los ingresos?",
                "answer": "Los ingresos fueron...",
                "sources": ["Reporte Financiero.pdf"],
                "timestamp": "2025-11-02T20:45:00Z",
                "confidence": 0.95
            }
        ]
    
    Example 2 (conversación específica):
        GET /assistant/history?conversation_id=5
        Headers: Authorization: Bearer <access_token>
        
        Response:
        [
            ...todos los mensajes de la conversación 5...
        ]
    
    Casos de uso:
        - Referenciar conversaciones pasadas
        - Contexto para nuevas preguntas
        - Análisis de qué se preguntó
        - Auditoría de interacciones
    """
    try:
        history = Curim_service.get_conversation_history(
            db=db,
            user_id=current_user.id,
            conversation_id=conversation_id,
            limit=limit
        )
        
        return history
    
    except Exception as e:
        logger.exception(f"Error obteniendo historial para usuario {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error obteniendo historial: {str(e)}"
        )


# ===========================
# ENDPOINTS - SINCRONIZACIÓN
# ===========================

@router.post("/documents/sync", response_model=DocumentSyncResponse)
async def sync_documents(
    request: DocumentSyncRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Sincronizar documentos del usuario con Curim.
    
    Asegura que todos los documentos del usuario estén indexados en Curim
    para búsqueda. Se ejecuta automáticamente en upload, pero puede usarse
    para reindexación manual o forzar actualización.
    
    Sincronización:
        - Verifica qué documentos están indexados
        - Indexa documentos nuevos o modificados
        - Opcionalmente fuerza reindexación completa
        - Retorna estadísticas de sincronización
    
    Casos de uso:
        - Después de editar documentos
        - Actualizar índices si hay cambios
        - Reindexación completa (force_reindex=true)
        - Verificar estado de sincronización
    
    Args:
        request (DocumentSyncRequest): Solicitud con:
            - document_ids: Documentos específicos (None = todos)
            - force_reindex: Reindexar incluso si ya estaban indexados
        
        current_user (User): Usuario autenticado (inyectado automáticamente)
        db (Session): Sesión de base de datos (inyectada automáticamente)
    
    Returns:
        DocumentSyncResponse: Resultado de sincronización:
            - synced_count: Documentos sincronizados
            - skipped_count: Documentos sin cambios (sin force)
            - failed_count: Documentos que fallaron
            - total_chunks: Total de chunks indexados
            - timestamp: Cuándo se completó
    
    Raises:
        HTTPException 401: Usuario no autenticado
        HTTPException 400: Parámetros inválidos
        HTTPException 500: Error en sincronización
    
    Example:
        POST /assistant/documents/sync
        Headers: Authorization: Bearer <access_token>
        Body: {
            "document_ids": [1, 2, 3],
            "force_reindex": false
        }
        
        Response (200 OK):
        {
            "synced_count": 3,
            "skipped_count": 0,
            "failed_count": 0,
            "total_chunks": 245,
            "timestamp": "2025-11-02T20:50:00Z"
        }
    """
    try:
        result = Curim_service.sync_documents(
            db=db,
            user_id=current_user.id,
            document_ids=request.document_ids,
            force_reindex=request.force_reindex
        )
        
        return DocumentSyncResponse(**result)
    
    except Exception as e:
        logger.exception(f"Error sincronizando documentos para usuario {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error sincronizando documentos: {str(e)}"
        )


# ===========================
# ENDPOINTS - ESTADO Y CACHÉ
# ===========================

@router.get("/status", response_model=CurimStatus)
async def get_Curim_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtener estado del sistema Curim para el usuario.
    
    Retorna información sobre documentos indexados, estado de caché,
    uso de recursos y estadísticas generales.
    
    Información incluida:
        - **Documentos indexados**: Cantidad y total de chunks
        - **Caché**: Hits/misses y tamaño
        - **Última sincronización**: Cuándo fue
        - **Uso de recursos**: Estadísticas de memoria/CPU
    
    Args:
        current_user (User): Usuario autenticado (inyectado automáticamente)
        db (Session): Sesión de base de datos (inyectada automáticamente)
    
    Returns:
        CurimStatus: Estado del sistema:
            - documents_indexed: Cantidad de documentos
            - total_chunks: Chunks indexados
            - last_sync: Última sincronización
            - cache_hits: Respuestas cacheadas
            - cache_size_mb: Tamaño del caché
            - system_healthy: Si sistema está OK
    
    Example:
        GET /assistant/status
        Headers: Authorization: Bearer <access_token>
        
        Response (200 OK):
        {
            "documents_indexed": 42,
            "total_chunks": 1250,
            "last_sync": "2025-11-02T19:30:00Z",
            "cache_hits": 156,
            "cache_size_mb": 45.2,
            "system_healthy": true
        }
    """
    try:
        status_info = Curim_service.get_status(db=db, user_id=current_user.id)
        return CurimStatus(**status_info)
    
    except Exception as e:
        logger.exception(f"Error obteniendo estado para usuario {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error obteniendo estado: {str(e)}"
        )


@router.delete("/cache")
async def clear_cache(
    current_user: User = Depends(get_current_user)
):
    """
    Limpiar caché de respuestas del usuario actual.
    
    Elimina todas las respuestas cacheadas del usuario. Útil para liberar
    memoria o forzar nuevas búsquedas sin caché.
    
    Returns:
        dict: Confirmación de limpieza:
            - message: "Caché limpiado exitosamente"
    
    Example:
        DELETE /assistant/cache
        Headers: Authorization: Bearer <access_token>
        
        Response (200 OK):
        {
            "message": "Caché limpiado exitosamente"
        }
    """
    try:
        Curim_service.cache_manager.clear(user_id=current_user.id)
        logger.info(f"Cache cleared for user {current_user.id}")
        return {"message": "Caché limpiado exitosamente"}
    
    except Exception as e:
        logger.exception(f"Error limpiando caché para usuario {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error limpiando caché: {str(e)}"
        )


@router.get("/cache/stats")
async def get_cache_stats(
    current_user: User = Depends(get_current_user)
):
    """
    Obtener estadísticas del caché del usuario.
    
    Retorna información sobre el uso del caché:
    - Número de hits/misses
    - Tamaño en memoria
    - Preguntas cacheadas
    - Eficiencia del caché
    
    Returns:
        dict: Estadísticas del caché:
            - total_requests: Total de solicitudes
            - cache_hits: Respuestas desde caché
            - cache_misses: Búsquedas nuevas
            - hit_rate: Porcentaje de hits (0-100)
            - cache_size_mb: Tamaño actual
            - max_cache_mb: Límite de caché
    
    Example:
        GET /assistant/cache/stats
        Headers: Authorization: Bearer <access_token>
        
        Response (200 OK):
        {
            "total_requests": 145,
            "cache_hits": 98,
            "cache_misses": 47,
            "hit_rate": 67.6,
            "cache_size_mb": 23.5,
            "max_cache_mb": 100.0
        }
    """
    try:
        stats = Curim_service.cache_manager.get_stats(user_id=current_user.id)
        return stats
    
    except Exception as e:
        logger.exception(f"Error obteniendo estadísticas de caché para usuario {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error obteniendo estadísticas: {str(e)}"
        )


# ===========================
# ENDPOINTS - TEXT TO SPEECH
# ===========================

@router.post("/tts", dependencies=[Depends(rate_limit(20, 60))])
async def text_to_speech(
    request: dict,
    current_user: User = Depends(get_current_user)
):
    """
    Convertir texto a voz usando Edge TTS.
    
    Genera audio MP3 a partir de texto usando síntesis de voz natural
    con Edge TTS. Soporta múltiples idiomas y voces, con control de
    velocidad y tono.
    
    Parámetros de voz:
        - **voice**: Identificador de voz (ej: es-PA-MargaritaNeural)
        - **rate**: Velocidad (ej: +0%, +20%, -10%)
        - **pitch**: Tono (ej: +0Hz, +50Hz, -25Hz)
    
    Voces disponibles (español):
        - es-PA-MargaritaNeural: Mujer, Panamá (default)
        - es-ES-AlvaroNeural: Hombre, España
        - es-MX-DariaNeural: Mujer, México
        - Y más (usar /assistant/voices para listar)
    
    Args:
        request (dict): Solicitud con:
            - text: Texto a convertir (requerido)
            - voice: Identificador de voz (default: es-PA-MargaritaNeural)
            - rate: Velocidad de habla (default: +0%)
            - pitch: Tono de voz (default: +0Hz)
        
        current_user (User): Usuario autenticado (inyectado automáticamente)
    
    Returns:
        StreamingResponse: Audio MP3 en streaming
            - Content-Type: audio/mpeg
            - Headers de descarga o inline
    
    Raises:
        HTTPException 400: Texto vacío o inválido
        HTTPException 401: Usuario no autenticado
        HTTPException 500: Error generando audio
    
    Example:
        POST /assistant/tts
        Headers: Authorization: Bearer <access_token>
        Body: {
            "text": "Hola, esto es una prueba de síntesis de voz",
            "voice": "es-PA-MargaritaNeural",
            "rate": "+0%",
            "pitch": "+0Hz"
        }
        
        Response (200 OK):
        - Content-Type: audio/mpeg
        - Contenido: Audio MP3 en streaming
    
    Casos de uso:
        - Reproducción de respuestas de Curim
        - Accesibilidad para usuarios con discapacidad visual
        - Podcasts autogenerados
        - Notificaciones por voz
        - Asistente de voz
    
    Performance:
        - Generación en tiempo real
        - Típicamente < 2 segundos para texto corto
        - Streaming directo sin almacenar en disco
    """
    try:
        text = request.get("text", "")
        voice = request.get("voice", "es-PA-MargaritaNeural")
        rate = request.get("rate", "+0%")
        pitch = request.get("pitch", "+0Hz")
        
        # Validar entrada
        if not text:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El texto es requerido"
            )
        
        if len(text) > 5000:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Texto demasiado largo (máximo 5000 caracteres)"
            )
        
        logger.info(f"Generating TTS for user {current_user.id}: {len(text)} chars with voice {voice}")
        
        # Generar audio con Edge TTS
        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        
        # Guardar audio en memoria
        audio_buffer = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_buffer.write(chunk["data"])
        
        audio_buffer.seek(0)
        
        # Retornar como streaming response
        return StreamingResponse(
            audio_buffer,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=audio.mp3"
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error generando TTS para usuario {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generando audio: {str(e)}"
        )


@router.get("/voices")
async def get_available_voices(
    current_user: User = Depends(get_current_user)
):
    """
    Obtener lista de voces disponibles en español.
    
    Retorna todas las voces en español disponibles en Edge TTS,
    incluyendo información de género, locales, etc.
    
    Información por voz:
        - **name**: Identificador (ej: es-PA-MargaritaNeural)
        - **gender**: Género (Male/Female)
        - **locale**: Localidad (es-PA, es-ES, es-MX, etc.)
    
    Returns:
        dict: Lista de voces disponibles:
            - voices: Array de voces con name, gender, locale
    
    Example:
        GET /assistant/voices
        Headers: Authorization: Bearer <access_token>
        
        Response (200 OK):
        {
            "voices": [
                {
                    "name": "es-PA-MargaritaNeural",
                    "gender": "Female",
                    "locale": "es-PA"
                },
                {
                    "name": "es-ES-AlvaroNeural",
                    "gender": "Male",
                    "locale": "es-ES"
                },
                {
                    "name": "es-MX-DariaNeural",
                    "gender": "Female",
                    "locale": "es-MX"
                },
                ...
            ]
        }
    
    Casos de uso:
        - Dropdown para seleccionar voz
        - Documentar voces disponibles
        - Validar voz antes de usar TTS
    """
    try:
        voices = await edge_tts.list_voices()
        
        # Filtrar solo voces en español
        spanish_voices = [
            {
                "name": voice["ShortName"],
                "gender": voice["Gender"],
                "locale": voice["Locale"]
            }
            for voice in voices
            if voice["Locale"].startswith("es")
        ]
        
        logger.info(f"Retrieved {len(spanish_voices)} Spanish voices for user {current_user.id}")
        
        return {"voices": spanish_voices}
    
    except Exception as e:
        logger.exception(f"Error obteniendo voces disponibles: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error obteniendo voces: {str(e)}"
        )
