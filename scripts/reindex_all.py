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
from datetime import datetime, timezone
from typing import List, Tuple

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db.database import SessionLocal
from app.models.models import CurimDocumentIndex, Document

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("reindex_all")


def reindex_documents(db, engine, documents) -> Tuple[int, List[int]]:
    """Devuelve (reindexados, ids con error). Un fallo no detiene el resto."""
    done, failed = 0, []
    for doc in documents:
        record = db.query(CurimDocumentIndex).filter_by(document_id=doc.id).first()
        if record is None:
            record = CurimDocumentIndex(document_id=doc.id, is_indexed=False, chunks_count=0)
            db.add(record)
        try:
            record.chunks_count = engine.index_document(doc)
            record.is_indexed = True
            record.last_indexed_at = datetime.now(timezone.utc)
            record.error_message = None
            done += 1
        except Exception as e:
            # Si ya estaba indexado, el índice anterior se conserva
            record.error_message = str(e)
            failed.append(doc.id)
            logger.error(f"Error reindexando documento {doc.id}: {e}")
        db.commit()
    return done, failed


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
