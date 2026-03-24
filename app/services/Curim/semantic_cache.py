
from datetime import datetime, timezone
from sentence_transformers import SentenceTransformer
import numpy as np
from typing import Optional, Dict
import json
import os

import logging

logger = logging.getLogger(__name__)

class SemanticCache:
    """
    Caché basado en similitud semántica
    Permite reutilizar respuestas para preguntas similares
    """
    
    def __init__(self, similarity_threshold: float = 0.85, embedding_model=None):
        self.cache_file = "./storage/Curim_data/cache/semantic_cache.json"
        self.similarity_threshold = similarity_threshold
        
        # Inyección de modelo para evitar doble carga en memoria
        if embedding_model:
            self.model = embedding_model
            logger.info("SemanticCache: Usando modelo de embeddings inyectado")
        else:
            # Fallback a carga local si no se provee
            logger.warning("SemanticCache: Cargando modelo localmente (posible redundancia)")
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
        
        self.cache = self._load_cache()
    
    def _load_cache(self) -> Dict:
        if os.path.exists(self.cache_file):
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    
    def _save_cache(self):
        os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
        with open(self.cache_file, 'w', encoding='utf-8') as f:
            json.dump(self.cache, f, ensure_ascii=False, indent=2)
    
    def get(self, user_id: int, question: str) -> Optional[Dict]:
        """
        Buscar respuesta para pregunta similar
        
        Retorna respuesta si encuentra pregunta con similitud >= threshold
        """
        if not self.cache:
            return None
        
        # Generar embedding de la pregunta
        if hasattr(self.model, 'encode'):
            question_embedding = self.model.encode(question)
        else:
            question_embedding = self.model.embed_query(question)
        
        # Buscar pregunta más similar del usuario
        best_match = None
        best_similarity = 0
        
        for key, entry in self.cache.items():
            if entry.get('user_id') != user_id:
                continue
            
            cached_embedding = np.array(entry['embedding'])
            
            # Calcular similitud coseno
            similarity = np.dot(question_embedding, cached_embedding) / (
                np.linalg.norm(question_embedding) * np.linalg.norm(cached_embedding)
            )
            
            if similarity > best_similarity:
                best_similarity = similarity
                best_match = entry
        
        # Retornar si supera threshold
        if best_similarity >= self.similarity_threshold:
            return {
                "answer": best_match['answer'],
                "confidence": best_match['confidence'],
                "sources": best_match['sources'],
                "sources_info": best_match.get('sources_info', [])
            }
        
        return None
    
    def set(self, user_id: int, question: str, answer: str, confidence: float, sources: list, sources_info: list = []):
        """Guardar respuesta con embedding"""
        
        # Generar embedding - Soporta tanto SentenceTransformer como LangChain Embeddings
        if hasattr(self.model, 'encode'):
            embedding = self.model.encode(question).tolist()
        else:
            embedding = self.model.embed_query(question)
        
        # Generar key única
        import hashlib
        key = hashlib.md5(f"{user_id}:{question}".encode()).hexdigest()
        
        self.cache[key] = {
            'user_id': user_id,
            'question': question,
            'answer': answer,
            'confidence': confidence,
            'sources': sources,
            'sources_info': sources_info,
            'embedding': embedding,
            'cached_at': datetime.now(timezone.utc).isoformat()
        }
        
        self._save_cache()
