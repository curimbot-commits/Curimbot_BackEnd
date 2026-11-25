"""
Reindexa todos los documentos con la configuración actual del RAG.

Uso, desde BackEnd/ (en Docker, dentro del contenedor):
    python scripts/reindex_all.py

Nadie debe subir ni borrar documentos mientras corre. Al terminar hay que
REINICIAR el backend: el proceso en marcha tiene el índice y las cachés de
respuestas cargados en memoria. Se puede repetir sin duplicar fragmentos.
"""

import logging
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db.database import SessionLocal
from app.models.models import Document
from app.services.Curim.reindex import reindex_documents

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("reindex_all")


def main() -> int:
    from app.services.Curim.Curim_service import get_curim_service

    service = get_curim_service()
    with SessionLocal() as db:
        documents = db.query(Document).filter(Document.text.isnot(None)).all()
        logger.info(f"{len(documents)} documentos para reindexar")
        done, failed = reindex_documents(db, service.rag_engine, documents)
    service.clear_all_cache()  # las respuestas guardadas venían del índice anterior
    logger.info(f"Reindexados {done}; con error {failed}. Reinicia el backend.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
