"""
(Re)indexación de documentos fuera de la subida.

- reindex_documents: usada por scripts/reindex_all.py.
- index_missing_documents: al arrancar, indexa los documentos que no tienen
  fragmentos (índice perdido al redesplegar o fallo al subirlos). Sin esto,
  el documento se ve en la lista pero el asistente no lo encuentra, y no se
  puede volver a subir porque se detecta como duplicado.
"""

import logging
from datetime import datetime, timezone
from typing import List, Tuple

from sqlalchemy.orm import defer

from app.models.models import CurimDocumentIndex, Document
from app.services.Curim.document_processor import DocumentProcessor

logger = logging.getLogger(__name__)

STARTUP_LOCK = "curim_index_missing"


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


def index_missing_documents(db, service) -> Tuple[int, List[int]]:
    """Indexa solo lo que falta; no toca documentos que ya tienen sus fragmentos."""
    engine = service.rag_engine
    processor = DocumentProcessor(rag_engine=engine)
    done, failed = 0, []
    rows = db.query(Document.id, Document.filename).filter(Document.text.isnot(None)).all()
    for doc_id, filename in rows:
        # El nombre también cuenta: si la BD se reinició, un id puede traer
        # fragmentos de otro archivo, y esos se reemplazan.
        own = {"$and": [{"document_id": doc_id}, {"filename": filename}]}
        if engine.vectorstore.get(where=own, limit=1, include=[])["ids"]:
            continue
        doc = db.query(Document).options(defer(Document.blob_enc)).filter_by(id=doc_id).first()
        if doc is None or not processor.validate_document(doc):
            continue
        ok, errors = reindex_documents(db, engine, [doc])
        done += ok
        failed += errors
    if done:
        service.clear_all_cache()
    if done or failed:
        logger.info(f"Índice reparado: {done} documentos indexados; con error {failed}")
    return done, failed


def run_startup_repair() -> None:
    """Punto de entrada del arranque: un solo proceso a la vez; un fallo no lo detiene."""
    from app.core.scheduler import run_with_lock
    from app.db.database import SessionLocal
    from app.services.Curim.Curim_service import get_curim_service

    def job():
        with SessionLocal() as db:
            index_missing_documents(db, get_curim_service())

    try:
        run_with_lock(STARTUP_LOCK, job)
    except Exception as e:
        logger.error(f"No se pudo revisar el índice de documentos: {e}", exc_info=True)
