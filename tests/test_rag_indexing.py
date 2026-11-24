"""Indexación y recuperación del RAG con el modelo de embeddings real.

Cada test usa un Chroma temporal: no toca storage/ ni llama a Gemini.
"""

import copy
import inspect
from types import SimpleNamespace

import pytest
from langchain_chroma import Chroma
from langchain_core.documents import Document as LangchainDocument

from app.api.v1.routes.assistant import Curim_service as service

FILLER = (
    "La presente póliza cubre los gastos médicos derivados de accidentes ocurridos durante la "
    "vigencia del contrato, siempre que el asegurado notifique el siniestro dentro de los plazos "
    "establecidos en las condiciones generales y presente la documentación exigida. "
)
FACT = "El deducible por hospitalización es de 1500 dólares por evento. "
QUESTION = "¿Cuál es el deducible por hospitalización?"
TABLE = "\n".join(f"ZX-{i:04d}/B | 12.345,{i:02d} | 2025-0{i % 9 + 1}-15 | 98,7%" for i in range(60))


@pytest.fixture
def engine(tmp_path):
    eng = copy.copy(service.rag_engine)  # mismo modelo, sin compartir índice ni estado
    # monkeypatch, al deshacer, deja en la instancia el método ligado al motor
    # original; heredarlo haría que este motor consultara el índice real.
    for name in [n for n, v in vars(eng).items() if inspect.ismethod(v) and hasattr(type(eng), n)]:
        delattr(eng, name)
    eng.vectorstore = Chroma(
        persist_directory=str(tmp_path),
        embedding_function=eng.embeddings,
        collection_metadata={"hnsw:space": "cosine"},
    )
    eng._on_status_change = None
    eng._status = "ready"
    eng.chunk_size, eng.chunk_overlap, eng.top_k = 1000, 200, 3
    return eng


def _doc(text, id=1):
    return SimpleNamespace(id=id, filename=f"doc{id}.pdf", text=text)


def _stored(engine):
    return engine.vectorstore.get()["documents"]


@pytest.mark.parametrize("text", [FILLER * 20, TABLE, "palabra" * 500], ids=["prosa", "tabla", "sin espacios"])
def test_every_fragment_fits_in_the_embedding_model(engine, text):
    engine.index_document(_doc(text))
    model = engine.embeddings._client
    lengths = [len(model.tokenizer(t)["input_ids"]) for t in _stored(engine)]
    assert max(lengths) <= model.max_seq_length


def test_fact_at_the_end_of_a_block_is_found(engine):
    target = (FILLER * 4)[: 990 - len(FACT)] + FACT
    engine.index_document(_doc(FILLER * 4, id=1))
    engine.index_document(_doc(target, id=2))
    _context, retrieved = engine._retrieve_context_sync(QUESTION, [_doc("", 1), _doc("", 2)])
    assert retrieved[0][0].metadata["document_id"] == 2
    assert FACT.strip() in retrieved[0][0].page_content


def test_context_is_the_whole_block_without_repeating_it(engine):
    block = (FILLER * 4)[: 990 - len(FACT)] + FACT
    engine.index_document(_doc(block))
    context, _ = engine._retrieve_context_sync(QUESTION, [_doc("")])
    assert context == block.strip()


def test_old_index_entries_still_work(engine):
    engine.vectorstore.add_documents([LangchainDocument(
        page_content=FACT, metadata={"document_id": 7, "filename": "viejo.pdf", "chunk_index": 0},
    )])
    context, retrieved = engine._retrieve_context_sync(QUESTION, [_doc("", 7)])
    assert context == FACT.strip()
    assert len(retrieved) == 1


def test_reindexing_replaces_previous_fragments(engine):
    engine.index_document(_doc(FILLER * 10))
    count = engine.index_document(_doc(FACT * 3))
    assert len(_stored(engine)) == count
    assert all("deducible" in t for t in _stored(engine))


def test_failed_reindex_keeps_the_previous_index_and_the_assistant_up(engine, monkeypatch):
    engine.index_document(_doc(FACT))

    def boom(*a, **k):
        raise RuntimeError("disco lleno")

    monkeypatch.setattr(engine.vectorstore, "add_documents", boom)
    with pytest.raises(Exception, match="disco lleno"):
        engine.index_document(_doc(FILLER * 5))
    assert _stored(engine) == [FACT.strip()]
    assert engine.is_ready


def test_assistant_can_answer_while_a_document_is_indexed(engine, monkeypatch):
    seen = []
    real = engine.vectorstore.add_documents

    def spy(docs, **kw):
        seen.append(engine.is_ready)
        return real(docs, **kw)

    monkeypatch.setattr(engine.vectorstore, "add_documents", spy)
    engine.index_document(_doc(FILLER))
    assert seen and all(seen)


def test_reindex_script_updates_the_index_records(engine, make_user, db):
    from app.models.models import CurimDocumentIndex
    from scripts.reindex_all import reindex_documents
    from tests.test_assistant_history import _make_doc

    good, empty = _make_doc(db, make_user(), is_public=0), _make_doc(db, make_user(), is_public=0)
    good.text, empty.text = FACT * 5, ""
    db.add(CurimDocumentIndex(document_id=good.id, is_indexed=True, chunks_count=99))
    db.commit()

    done, failed = reindex_documents(db, engine, [good, empty])

    assert (done, failed) == (1, [empty.id])
    record = db.query(CurimDocumentIndex).filter_by(document_id=good.id).one()
    assert record.chunks_count == len(_stored(engine))
    failed_record = db.query(CurimDocumentIndex).filter_by(document_id=empty.id).one()
    assert not failed_record.is_indexed and failed_record.error_message
