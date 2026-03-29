from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

# ===========================
# REQUEST SCHEMAS
# ===========================

class CurimQueryRequest(BaseModel):
    """Request para consultar a Curim"""
    question: str = Field(..., min_length=1, max_length=1000, description="Pregunta del usuario")
    document_ids: Optional[List[int]] = Field(default=None, description="IDs de documentos específicos (opcional)")
    use_cache: bool = Field(default=True, description="Usar caché de respuestas")
    
    class Config:
        json_schema_extra = {
            "example": {
                "question": "¿Qué es AudacIA?",
                "document_ids": [1, 2, 3],
                "use_cache": True
            }
        }

class CurimVoiceRequest(BaseModel):
    """Request para consulta por voz"""
    audio_base64: str = Field(..., description="Audio en base64")
    use_cache: bool = Field(default=True, description="Usar caché de respuestas")

class DocumentSyncRequest(BaseModel):
    """Request para sincronizar documentos con Curim"""
    document_ids: Optional[List[int]] = Field(default=None, description="IDs específicos o None para todos")
    force_reindex: bool = Field(default=False, description="Forzar reindexación")

# ===========================
# RESPONSE SCHEMAS
# ===========================

class CurimSourceInfo(BaseModel):
    """Información detallada de fuente"""
    document_id: int
    filename: str
    snippet: Optional[str] = None
    relevance_score: Optional[float] = None

class CurimResponse(BaseModel):
    """Response de Curim"""
    answer: str = Field(..., description="Respuesta generada")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Nivel de confianza (0-1)")
    sources: List[int] = Field(default=[], description="IDs de documentos usados como fuente")
    sources_info: List[CurimSourceInfo] = Field(default=[], description="Información detallada de fuentes")
    from_cache: bool = Field(..., description="Si la respuesta viene del caché")
    processing_time_ms: float = Field(..., description="Tiempo de procesamiento en ms")
    conversation_id: int = Field(..., description="ID de la conversación")
    
    class Config:
        json_schema_extra = {
            "example": {
                "answer": "AudacIA es un centro especializado en inteligencia artificial...",
                "confidence": 0.95,
                "sources": [1, 3, 5],
                "sources_info": [
                    {"document_id": 1, "filename": "Doc1.pdf", "relevance_score": 0.9}
                ],
                "from_cache": False,
                "processing_time_ms": 847.3,
                "conversation_id": 42
            }
        }

class ConversationMessage(BaseModel):
    """Mensaje individual de conversación"""
    id: int
    role: str = Field(..., description="'user' o 'assistant'")
    content: str
    timestamp: datetime
    sources: List[int] = Field(default=[])
    sources_info: List[CurimSourceInfo] = Field(default=[])

class ConversationHistory(BaseModel):
    """Historial de conversación"""
    conversation_id: int
    user_id: int
    messages: List[ConversationMessage]
    created_at: datetime
    updated_at: datetime
    total_messages: int

class CurimStatus(BaseModel):
    """Estado del sistema Curim"""
    is_ready: bool
    documents_indexed: int
    cache_size: int
    last_sync: Optional[datetime]
    vector_db_size_mb: float

class DocumentSyncResponse(BaseModel):
    """Response de sincronización de documentos"""
    success: bool
    documents_processed: int
    documents_indexed: int
    errors: List[str] = Field(default=[])
    processing_time_ms: float


class TTSRequest(BaseModel):
    text: str
    voice: str = "es-PA-MargaritaNeural"
    rate: str = "+0%"
    pitch: str = "+0Hz"

class VoiceInfo(BaseModel):
    name: str
    gender: str
    locale: str

class VoicesResponse(BaseModel):
    voices: List[VoiceInfo]

