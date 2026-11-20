import os
import sys
import logging

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db.database import SessionLocal
from app.models.models import Document
from app.services.Curim.rag_engine import VoiceRAGEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("reindex_all")


def reindex_all():
    db = SessionLocal()
    try:
        logger.info("Inicializando VoiceRAGEngine...")
        engine = VoiceRAGEngine()

        logger.info("Obteniendo documentos de la base de datos...")
        documents = db.query(Document).filter(Document.text != None).all()
        logger.info(f"Encontrados {len(documents)} documentos para re-indexar.")

        count = 0
        for doc in documents:
            try:
                logger.info(f"Procesando [{doc.id}] {doc.filename}...")
                # index_document borra chunks previos del mismo document_id
                chunks = engine.index_document(doc)
                count += 1
                logger.info(f"Completado: {chunks} chunks indexados.")
            except Exception as e:
                logger.error(f"Error procesando documento {doc.id}: {e}")

        logger.info(
            f"Proceso finalizado. {count}/{len(documents)} documentos re-indexados."
        )
    finally:
        db.close()


if __name__ == "__main__":
    reindex_all()