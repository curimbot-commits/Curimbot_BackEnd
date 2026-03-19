import os
import re
import logging
import hashlib
import time
import base64
import asyncio
from typing import List, Tuple, Dict, Optional, Callable, Any
import numpy as np
from collections import defaultdict
from contextlib import contextmanager
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document as LangchainDocument
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from google import genai as genai_client  # Para Live API
from google.genai import types
import sounddevice as sd
import soundfile as sf
from io import BytesIO

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class VoiceRAGEngineError(Exception):
    """Excepción base para errores del Voice RAG Engine"""
    pass


class VoiceRAGEngine:
    """
    Motor RAG completamente por voz usando Gemini Live API.
    
    Características:
    - Entrada: Texto o voz (micrófono)
    - Salida: Texto o audio (sintetizado)
    - Modelo: gemini-2.5-flash-native-audio-preview-12-2025 (Live API)
    - Voz: Zephyr (prebuilt voice)
    """
    
    def __init__(self, on_status_change: Optional[Callable[[str], None]] = None):
        """
        Inicializa el motor RAG por voz.
        
        Args:
            on_status_change: Callback opcional para notificar cambios de estado
        """
        self._status = 'initializing'
        self._on_status_change = on_status_change
        self._initialized = False
        self._is_recording = False
        self._audio_queue = asyncio.Queue()
        
        try:
            self._set_status('initializing')
            
            # === CONFIGURACIÓN BÁSICA ===
            self.gemini_api_key = os.getenv("GEMINI_API_KEY")
            if not self.gemini_api_key:
                raise ValueError("GEMINI_API_KEY no configurada en .env")

            self.vector_db_path = "./storage/Curim_data/chroma_db"
            self.chunk_size = 500
            self.chunk_overlap = 100

            # === CONFIGURACIÓN DE AUDIO ===
            self.sample_rate = 16000  # Para entrada de voz
            self.output_sample_rate = 24000  # Para salida de Gemini
            self.channels = 1
            self.audio_buffer = []
            
            # === CONFIGURAR GEMINI ===
            self._init_gemini()
            
            # === EMBEDDINGS PARA RETRIEVAL ===
            self._init_embeddings()
            
            # === VECTOR STORE ===
            self._init_vectorstore()
            
            # === ESTADO DE CONVERSACIÓN ===
            self.conversation_history = []
            self.max_history = 5
            
            # === CACHE DE CONTEXTO ===
            self.context_cache = {}
            
            self._initialized = True
            self._set_status('ready')
            logger.info("VoiceRAGEngine inicializado correctamente")
            
        except Exception as e:
            self._set_status('error')
            logger.error(f"Error en inicialización: {e}")
            raise VoiceRAGEngineError(f"Fallo al inicializar VoiceRAGEngine: {e}") from e

    def _set_status(self, status: str) -> None:
        """Actualiza el estado y notifica via callback"""
        old_status = self._status
        self._status = status
        logger.info(f"Estado cambiado: {old_status} -> {status}")
        
        if self._on_status_change:
            try:
                self._on_status_change(status)
            except Exception as e:
                logger.warning(f"Error en callback de estado: {e}")

    @property
    def status(self) -> str:
        """Estado actual del motor"""
        return self._status

    @property
    def is_ready(self) -> bool:
        """Verifica si el motor está listo para operar"""
        return self._initialized and self._status == 'ready'

    def _init_gemini(self, max_retries: int = 3) -> None:
        """Inicializa Gemini con soporte para Live API y texto"""
        for attempt in range(max_retries):
            try:
                # Configuración estándar para generate_content
                genai.configure(api_key=self.gemini_api_key)
                
                # Modelo para texto (siempre funciona)
                self.text_model = genai.GenerativeModel(
                    'gemini-2.5-flash',  # Modelo estándar para texto
                    safety_settings={
                        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                    }
                )
                
                # Cliente para Live API (audio en tiempo real)
                self.live_client = genai_client.Client(
                    api_key=self.gemini_api_key,
                    http_options={'api_version': 'v1alpha'}
                )
                self.live_model = 'gemini-2.5-flash-native-audio-preview-12-2025'
                
                # Configuración para Live API
                self.live_config = {
                    "response_modalities": ["AUDIO"],
                    "speech_config": {
                        "voice_config": {
                            "prebuilt_voice_config": {
                                "voice_name": "Zephyr"
                            }
                        }
                    },
                    "system_instruction": {
                        "parts": [{
                            "text": """Eres un asistente de voz experto en documentos.
Responde de forma natural y conversacional basándote en el contexto proporcionado."""
                        }]
                    }
                }
                
                # Modelo por defecto (para compatibilidad)
                self.model = self.text_model
                
                logger.info("Gemini inicializado correctamente: Texto + Live API")
                return
                
            except Exception as e:
                logger.warning(f"Intento {attempt + 1}/{max_retries} falló: {e}")
                if attempt == max_retries - 1:
                    raise VoiceRAGEngineError(f"No se pudo conectar con Gemini: {e}") from e
                time.sleep(2 ** attempt)

    def _init_embeddings(self) -> None:
        """Inicializa el modelo de embeddings para retrieval"""
        try:
            import torch
            
            # Detectar si hay GPU disponible
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
            
            if device == 'cuda':
                logger.info("✅ GPU detectada para embeddings")
            else:
                logger.warning("⚠️ Usando CPU para embeddings (será lento)")
            
            self.embeddings = HuggingFaceEmbeddings(
                model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                model_kwargs={'device': device},
                encode_kwargs={
                    'normalize_embeddings': True,
                    'batch_size': 32  # Procesar en lotes para mayor velocidad
                }
            )
            logger.info(f"Embeddings inicializados en {device}")
        except Exception as e:
            raise VoiceRAGEngineError(f"Error al inicializar embeddings: {e}") from e

    def _init_vectorstore(self) -> None:
        """Inicializa o carga el vector store"""
        try:
            os.makedirs(self.vector_db_path, exist_ok=True)
            
            if os.path.exists(self.vector_db_path) and os.listdir(self.vector_db_path):
                self.vectorstore = Chroma(
                    persist_directory=self.vector_db_path,
                    embedding_function=self.embeddings
                )
                logger.info("VectorDB cargada desde disco")
            else:
                self.vectorstore = Chroma(
                    persist_directory=self.vector_db_path,
                    embedding_function=self.embeddings,
                    collection_metadata={"hnsw:space": "cosine", "hnsw:M": 16}
                )
                logger.info("VectorDB creada nueva")
        except Exception as e:
            raise VoiceRAGEngineError(f"Error al inicializar vectorstore: {e}") from e

    # === MÉTODOS DE AUDIO ===

    def _audio_callback(self, indata, frames, time_info, status):
        """Callback para capturar audio del micrófono"""
        if status:
            logger.warning(f"Audio callback status: {status}")
        
        if self._is_recording:
            self.audio_buffer.append(indata.copy())

    def start_listening(self) -> None:
        """Inicia la captura de audio del micrófono"""
        if not self.is_ready:
            raise VoiceRAGEngineError(f"Motor no está listo (estado: {self._status})")
        
        self._set_status('listening')
        self._is_recording = True
        self.audio_buffer = []
        
        self.stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            callback=self._audio_callback,
            dtype='int16'
        )
        self.stream.start()
        logger.info("Micrófono activado - Escuchando...")

    def stop_listening(self) -> bytes:
        """Detiene la captura de audio y devuelve el buffer grabado"""
        self._is_recording = False
        
        if hasattr(self, 'stream'):
            self.stream.stop()
            self.stream.close()
        
        if self.audio_buffer:
            audio_data = np.concatenate(self.audio_buffer, axis=0)
            logger.info(f"Audio capturado: {len(audio_data)} samples")
            return audio_data.tobytes()
        
        return b''

    def _encode_audio_to_base64(self, audio_bytes: bytes) -> str:
        """Codifica audio a base64"""
        return base64.b64encode(audio_bytes).decode('utf-8')

    def _decode_audio_from_base64(self, base64_audio: str) -> bytes:
        """Decodifica audio base64"""
        return base64.b64decode(base64_audio)

    def _play_audio(self, audio_data: bytes) -> None:
        """Reproduce audio"""
        try:
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            sd.play(audio_array, self.output_sample_rate)
            sd.wait()
            logger.info("Audio reproducido correctamente")
        except Exception as e:
            logger.error(f"Error reproduciendo audio: {e}")

    # === MÉTODOS DE CONSULTA ===

    def query(
        self, 
        question: str, 
        documents: List
    ) -> Tuple[str, float, List[int], List[Dict]]:
        """
        Método para consultas de texto (síncrono).
        Usa gemini-1.5-flash para respuestas de texto.
        
        Args:
            question: Pregunta en texto
            documents: Lista de documentos disponibles
        
        Returns:
            Tuple[str, float, List[int], List[Dict]]: 
                - answer: Respuesta en texto
                - confidence: Confianza 0-1
                - source_ids: Lista de IDs de documentos fuente
                - sources_info: Información detallada de fuentes
        """
        if not self.is_ready:
            raise VoiceRAGEngineError(f"Motor no está listo (estado: {self._status})")
        
        try:
            # 1. RETRIEVAL DE CONTEXTO
            logger.info(f"🔍 Buscando información para: {question}")
            context = self._retrieve_context_sync(question, documents)
            
            if not context or context == "No hay documentos disponibles.":
                return (
                    "No tengo documentos disponibles para responder tu pregunta.",
                    0.0,
                    [],
                    []
                )
            
            # 2. GENERAR RESPUESTA EN TEXTO
            system_instruction = (
                "Eres ATHENIA, un asistente experto en análisis de documentos. "
                "Tu objetivo es responder preguntas basándote ÚNICAMENTE en el contexto proporcionado. "
                "REGLA CRÍTICA: Responde siempre en el mismo idioma en el que el usuario te hable (Español o Inglés). "
                "Si no sabes la respuesta basándote en el contexto, dilo honestamente."
            )
            prompt = f"""{system_instruction}

Basado en el siguiente contexto, responde la pregunta de forma DETALLADA y COMPLETA.
Incluye todos los detalles relevantes, ejemplos si los hay, y explica con profundidad.
No resumas innecesariamente — se espera una respuesta extensa y bien desarrollada.

CONTEXTO:
{context}

PREGUNTA:
{question}

RESPUESTA DETALLADA:"""
            
            # Usar text_model (gemini-1.5-flash)
            response = self.text_model.generate_content(
                prompt,
                generation_config={
                    'temperature': 0.9,
                    'top_p': 0.95,
                    'max_output_tokens': 2048
                }
            )
            
            answer = response.text if response.text else "Lo siento, no pude generar una respuesta."
            
            # 3. OBTENER IDs DE FUENTES
            source_ids = list(set([doc.id for doc in documents if hasattr(doc, 'id')]))
            
            # 4. CREAR INFORMACIÓN DETALLADA DE FUENTES
            sources_info = []
            for doc in documents[:3]:
                sources_info.append({
                    "document_id": doc.id if hasattr(doc, 'id') else 0,
                    "filename": doc.filename if hasattr(doc, 'filename') else "Desconocido",
                    "snippet": context[:200] + "...",
                    "relevance_score": 0.8
                })
            
            # 5. CALCULAR CONFIANZA
            confidence = self._calculate_confidence(context, question)
            
            logger.info(f"✅ Respuesta generada con confianza: {confidence}")
            
            return answer, confidence, source_ids, sources_info
            
        except Exception as e:
            logger.error(f"Error en query: {e}", exc_info=True)
            return (
                f"Lo siento, ocurrió un error al procesar tu pregunta: {str(e)}",
                0.0,
                [],
                []
            )

    async def query_by_voice(
        self, 
        documents: List,
        max_duration_seconds: int = 10
    ) -> Tuple[bytes, float]:
        """
        Consulta por voz usando el pipeline tradicional (grabar -> transcribir -> responder).
        Útil para clientes HTTP simples.
        
        Args:
            documents: Lista de documentos disponibles
            max_duration_seconds: Duración máxima de grabación
            
        Returns:
            Tuple[bytes, float]: (audio_respuesta, confianza)
        """
        if not self.is_ready:
            raise VoiceRAGEngineError(f"Motor no está listo (estado: {self._status})")
        
        try:
            # 1. CAPTURAR VOZ
            logger.info("🎤 Iniciando captura de voz...")
            self.start_listening()
            await asyncio.sleep(max_duration_seconds)
            audio_input = self.stop_listening()
            
            if not audio_input:
                logger.warning("No se capturó audio")
                return b'', 0.0
            
            # 2. TRANSCRIBIR
            self._set_status('processing')
            logger.info("📝 Transcribiendo pregunta...")
            
            transcribed_question = await self._transcribe_audio(audio_input)
            logger.info(f"Pregunta transcrita: {transcribed_question}")
            
            if not transcribed_question:
                error_audio = await self._generate_error_audio(
                    "No pude entender tu pregunta. Por favor, intenta de nuevo."
                )
                return error_audio, 0.0
            
            # 3. RETRIEVAL
            logger.info("🔍 Buscando información relevante...")
            context = self._retrieve_context_sync(transcribed_question, documents)
            
            # 4. GENERAR RESPUESTA EN AUDIO
            logger.info("🎯 Generando respuesta por voz...")
            audio_response, confidence = await self._generate_voice_response(
                transcribed_question,
                context
            )
            
            # 5. REPRODUCIR
            self._set_status('speaking')
            logger.info("🔊 Reproduciendo respuesta...")
            self._play_audio(audio_response)
            
            self._set_status('ready')
            return audio_response, confidence
            
        except Exception as e:
            logger.error(f"Error en query por voz: {e}")
            self._set_status('error')
            raise VoiceRAGEngineError(f"Error al procesar consulta por voz: {e}") from e

    async def create_live_session(self, document_ids: Optional[List[int]] = None):
        """
        Crea una sesión Live de Gemini para streaming de audio en tiempo real.
        Este método es usado por el WebSocket.
        
        Args:
            document_ids: IDs de documentos a usar para contexto
        
        Returns:
            Live session de Gemini
        """
        if not hasattr(self, 'live_client'):
            raise VoiceRAGEngineError("Live API no está disponible")
        
        # Preparar contexto de documentos si se especificaron
        system_prompt = """Eres un asistente de voz experto en documentos.
Responde de forma natural y conversacional basándote en el contexto proporcionado."""
        
        if document_ids and document_ids in self.context_cache:
            context = self.context_cache.get(str(document_ids))
            if context:
                system_prompt = f"""Contexto de documentos:
{context}

{system_prompt}"""
        
        # Configurar sesión
        config_dict = self.live_config.copy()
        config_dict["system_instruction"]["parts"][0]["text"] = system_prompt
        
        # Crear sesión
        session = await self.live_client.aio.live.connect(
            model=self.live_model,
            config=types.LiveConnectConfig(**config_dict)
        )
        
        return session

    # === MÉTODOS DE RETRIEVAL ===

    def _retrieve_context_sync(self, question: str, documents: List) -> str:
        """Versión síncrona de retrieve_context"""
        try:
            if not documents:
                return "No hay documentos disponibles."
            
            doc_ids = [doc.id for doc in documents]
            
            retrieved = self.vectorstore.similarity_search_with_score(
                query=question,
                k=8,  # Reducido de 12 para optimizar velocidad
                filter={"document_id": {"$in": doc_ids}}
            )
            
            if not retrieved:
                return "No se encontró información relevante."
            
            selected_docs = [doc for doc, score in retrieved[:5] if score < 1.5]
            
            if not selected_docs:
                return "No se encontraron chunks con suficiente relevancia."
            
            context_parts = []
            for doc in selected_docs:
                context_parts.append(doc.page_content.strip())
            
            context = "\n\n".join(context_parts)
            logger.info(f"Contexto recuperado: {len(context)} caracteres de {len(selected_docs)} chunks")
            
            # Guardar en caché
            doc_ids_key = str(sorted(doc_ids))
            self.context_cache[doc_ids_key] = context
            
            return context
            
        except Exception as e:
            logger.error(f"Error en retrieval: {e}")
            return ""

    async def _retrieve_context(
        self, 
        question: str, 
        documents: List
    ) -> str:
        """Versión asíncrona (wrapper)"""
        return await asyncio.to_thread(
            self._retrieve_context_sync,
            question,
            documents
        )

    # === MÉTODOS DE AUDIO CON GEMINI ===

    async def _transcribe_audio(self, audio_bytes: bytes) -> str:
        """Transcribe audio a texto usando Gemini"""
        try:
            base64_audio = self._encode_audio_to_base64(audio_bytes)
            
            prompt = """Transcribe exactamente lo que escuchas en el audio. 
Devuelve solo la transcripción, sin comentarios adicionales."""
            
            response = await self.text_model.generate_content_async(
                [
                    {
                        "mime_type": "audio/wav",
                        "data": base64_audio
                    },
                    prompt
                ]
            )
            
            return response.text.strip() if response.text else ""
            
        except Exception as e:
            logger.error(f"Error en transcripción: {e}")
            return ""

    async def _generate_voice_response(
        self,
        question: str,
        context: str
    ) -> Tuple[bytes, float]:
        """Genera respuesta en audio usando Gemini"""
        try:
            prompt = f"""CONTEXTO DISPONIBLE:
{context}

PREGUNTA DEL USUARIO:
{question}

Responde de forma natural y conversacional:"""

            # Generar respuesta con audio
            response = await self.text_model.generate_content_async(
                prompt,
                generation_config={
                    'response_modalities': ['AUDIO'],
                    'speech_config': {
                        'voice_config': {
                            'prebuilt_voice_config': {
                                'voice_name': 'Zephyr'
                            }
                        }
                    },
                    'temperature': 0.7,
                    'top_p': 0.9,
                    'max_output_tokens': 500
                }
            )
            
            # Extraer audio
            audio_data = None
            if response.candidates:
                candidate = response.candidates[0]
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if hasattr(part, 'inline_data') and part.inline_data:
                            if part.inline_data.mime_type.startswith('audio'):
                                audio_data = self._decode_audio_from_base64(part.inline_data.data)
                                break
            
            if not audio_data:
                logger.warning("No se encontró audio en la respuesta")
                return await self._generate_error_audio("Error al generar audio."), 0.3
            
            confidence = self._calculate_confidence(context, question)
            return audio_data, confidence
            
        except Exception as e:
            logger.error(f"Error generando respuesta de voz: {e}")
            return await self._generate_error_audio("Ocurrió un error al procesar tu pregunta."), 0.0

    async def _generate_error_audio(self, error_message: str) -> bytes:
        """Genera audio de error"""
        try:
            response = await self.text_model.generate_content_async(
                f"Di con voz natural y empática: {error_message}",
                generation_config={
                    'response_modalities': ['AUDIO'],
                    'speech_config': {
                        'voice_config': {
                            'prebuilt_voice_config': {
                                'voice_name': 'Zephyr'
                            }
                        }
                    }
                }
            )
            
            if response.candidates:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'inline_data'):
                        return self._decode_audio_from_base64(part.inline_data.data)
            
            return b''
            
        except Exception as e:
            logger.error(f"Error generando audio de error: {e}")
            return b''

    def _calculate_confidence(self, context: str, question: str) -> float:
        """Calcula confianza de la respuesta"""
        try:
            factors = []
            
            # Longitud del contexto
            context_length = len(context.split())
            if context_length > 100:
                factors.append(0.8)
            elif context_length > 50:
                factors.append(0.6)
            else:
                factors.append(0.4)
            
            # Relevancia semántica
            try:
                question_emb = self.embeddings.embed_query(question)
                context_emb = self.embeddings.embed_query(context[:500])
                
                similarity = np.dot(question_emb, context_emb) / (
                    np.linalg.norm(question_emb) * np.linalg.norm(context_emb)
                )
                factors.append(float(similarity))
            except:
                factors.append(0.5)
            
            confidence = np.mean(factors) if factors else 0.5
            return max(0.0, min(1.0, round(confidence, 2)))
            
        except Exception as e:
            logger.error(f"Error calculando confianza: {e}")
            return 0.5

    def _update_conversation_history(self, question: str, answer: str) -> None:
        """Actualiza el historial de conversación"""
        self.conversation_history.append((question, answer))
        if len(self.conversation_history) > self.max_history:
            self.conversation_history.pop(0)

    def get_db_size(self) -> float:
        """Retorna el tamaño del vector store en MB"""
        try:
            if not os.path.exists(self.vector_db_path):
                return 0.0
            
            total_size = 0
            for dirpath, _, filenames in os.walk(self.vector_db_path):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    total_size += os.path.getsize(fp)
            
            return round(total_size / (1024 * 1024), 2)
        except Exception:
            return 0.0

    def index_document(self, document) -> int:
        """
        Indexa documento en el vector store.
        
        Args:
            document: Documento a indexar
            
        Returns:
            int: Número de chunks creados
        """
        if not self.is_ready:
            raise VoiceRAGEngineError(f"Motor no está listo (estado: {self._status})")
        
        try:
            if not document or not hasattr(document, 'text') or not document.text:
                raise ValueError("Documento inválido")
            
            self._set_status('processing')
            
            # Chunking
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
                separators=["\n\n", "\n", ". ", " ", ""]
            )
            chunks = text_splitter.split_text(document.text)
            
            if not chunks:
                logger.warning(f"Documento {document.filename} no generó chunks")
                return 0
            
            # Crear documentos para indexar
            docs = []
            for i, chunk in enumerate(chunks):
                metadata = {
                    "chunk_index": i,
                    "filename": document.filename,
                    "document_id": document.id,
                    "word_count": len(chunk.split()),
                }
                
                docs.append(
                    LangchainDocument(
                        page_content=chunk,
                        metadata=metadata
                    )
                )
            
            # Agregar al vector store
            self.vectorstore.add_documents(docs)
            
            # Persistir cambios (Chroma 0.4+ lo hace automático, pero por si acaso)
            if hasattr(self.vectorstore, 'persist'):
                self.vectorstore.persist()
            
            self._set_status('ready')
            logger.info(f"Indexado {len(chunks)} chunks de {document.filename}")
            
            # Limpiar caché de contexto para este documento
            keys_to_remove = [k for k in self.context_cache if str(document.id) in k]
            for k in keys_to_remove:
                self.context_cache.pop(k, None)
            
            return len(chunks)
            
        except Exception as e:
            logger.error(f"Error indexando documento: {e}")
            self._set_status('error')
            raise VoiceRAGEngineError(f"Fallo al indexar documento: {e}") from e

    def cleanup(self) -> None:
        """Limpia recursos antes de cerrar"""
        try:
            self._set_status('closing')
            
            if hasattr(self, 'stream'):
                try:
                    self.stream.stop()
                    self.stream.close()
                except:
                    pass
            
            logger.info("VoiceRAGEngine cerrado correctamente")
            
        except Exception as e:
            logger.error(f"Error en cleanup: {e}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        return False


# === ALIAS PARA COMPATIBILIDAD ===
RAGEngine = VoiceRAGEngine
RAGEngineError = VoiceRAGEngineError
__all__ = ['VoiceRAGEngine', 'VoiceRAGEngineError', 'RAGEngine', 'RAGEngineError']