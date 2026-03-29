import os
import sys
import shutil
import logging

# Añadir el directorio raíz al path para importar la app
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db.database import SessionLocal
from app.models.models import Document
from app.services.Curim.rag_engine import VoiceRAGEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("reindex_all")

def reindex_all():
    db = SessionLocal()
    try:
        # 1. Inicializar Engine
        logger.info("Inicializando VoiceRAGEngine...")
        engine = VoiceRAGEngine()
        
        # 2. Limpiar base de datos vectorial actual
        try:
            logger.info("Limpiando colección de ChromaDB vía API...")
            # Acceder directamente a la colección de Chroma subyacente
            if hasattr(engine.vectorstore, "_collection"):
                # Esto borra todos los documentos de la colección actual
                engine.vectorstore._collection.delete()
                logger.info("Colección vaciada correctamente.")
            else:
                logger.warning("No se pudo acceder a la colección interna para borrar.")
        except Exception as e:
            logger.error(f"Error al limpiar la colección: {e}")
            logger.info("Intentando continuar sin limpieza previa (esto puede duplicar chunks si no se maneja bien)...")
        
        # 3. Obtener todos los documentos con texto
        logger.info("Obteniendo documentos de la base de datos...")
        documents = db.query(Document).filter(Document.text != None).all()
        logger.info(f"Encontrados {len(documents)} documentos para re-indexar.")
        
        # 4. Procesar cada documento
        count = 0
        for doc in documents:
            try:
                logger.info(f"Procesando [{doc.id}] {doc.filename}...")
                chunks = engine.index_document(doc)
                count += 1
                logger.info(f"Completado: {chunks} chunks indexados.")
            except Exception as e:
                logger.error(f"Error procesando documento {doc.id}: {e}")
        
        logger.info(f"Proceso finalizado. {count}/{len(documents)} documentos re-indexados con éxito.")
        
    finally:
        db.close()

if __name__ == "__main__":
    reindex_all()
