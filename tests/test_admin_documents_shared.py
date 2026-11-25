"""Lo que sube un administrador queda disponible para todos, incluidos los usuarios nuevos."""

import pytest
from langchain_chroma import Chroma

from app.api.v1.routes import assistant
from app.models.models import CurimDocumentIndex
from app.services.Curim.reindex import index_missing_documents
from tests.test_documents_access import _as

service = assistant.Curim_service
engine = service.rag_engine
TEXT = "El deducible por hospitalizacion de la poliza Horizonte es de 1500 dolares por evento. "
QUESTION = "¿Cuál es el deducible por hospitalización?"


@pytest.fixture(autouse=True)
def temp_index(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "vectorstore", Chroma(
        persist_directory=str(tmp_path), embedding_function=engine.embeddings,
        collection_metadata={"hnsw:space": "cosine"}))


def _upload(client, user, name="poliza.txt", text=TEXT):
    r = _as(client, user).post("/documents/upload",
                               files=[("files", (name, text.encode(), "text/plain"))])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["success_count"] == 1 and body["Curim_indexed_count"] == 1, body
    return body["successful_uploads"][0]["id"]


def _visible(client, user):
    c = _as(client, user)
    listed = {d["id"] for d in c.get("/documents/", params={"limit": 100}).json()["items"]}
    found = {d["id"] for d in c.get("/documents/search", params={"text": "Horizonte"}).json()["items"]}
    return listed, found


def _retrieved(db, user):
    db.rollback()
    docs = service._get_user_documents(db, user.id)
    _context, hits = engine._retrieve_context_sync(QUESTION, docs)
    return {d.metadata["document_id"] for d, _ in hits}


def test_new_user_gets_admin_document(client, make_user, db):
    doc_id = _upload(client, make_user("admin"))
    new_user = make_user()
    listed, found = _visible(client, new_user)
    assert doc_id in listed and doc_id in found
    assert client.get(f"/documents/download/{doc_id}").status_code == 200
    assert doc_id in _retrieved(db, new_user)


def test_user_document_stays_private(client, make_user, db):
    doc_id = _upload(client, make_user())
    other = make_user()
    listed, found = _visible(client, other)
    assert doc_id not in listed | found | _retrieved(db, other)


def test_status_counts_shared_documents(client, make_user):
    _upload(client, make_user("admin"))
    status = _as(client, make_user()).get("/assistant/status").json()
    assert status["is_ready"] and status["documents_indexed"] >= 1
    assert status["last_sync"]


# ── Reparación del índice al arrancar ────────────────────────

def _lose_index(doc_id):
    """Como un redespliegue sin volumen: la BD dice indexado, pero no hay fragmentos."""
    engine.vectorstore.delete(where={"document_id": doc_id})


def _repair(db):
    db.rollback()  # REPEATABLE READ: ver lo que se acaba de subir
    return index_missing_documents(db, service)


def test_document_without_fragments_is_indexed_again(client, make_user, db):
    doc_id = _upload(client, make_user("admin"))
    _lose_index(doc_id)
    new_user = make_user()
    assert doc_id not in _retrieved(db, new_user)

    _repair(db)

    assert doc_id in _retrieved(db, new_user)
    record = db.query(CurimDocumentIndex).filter_by(document_id=doc_id).one()
    assert record.is_indexed and record.chunks_count >= 1


def test_indexed_documents_are_left_alone(client, make_user, db, monkeypatch):
    doc_id = _upload(client, make_user("admin"))
    _repair(db)
    indexed = []
    monkeypatch.setattr(engine, "index_document", lambda d: indexed.append(d.id) or 1)
    cleared = []
    monkeypatch.setattr(service, "clear_all_cache", lambda *a: cleared.append(a))
    _repair(db)
    assert doc_id not in indexed and cleared == []


def test_fragments_of_another_file_do_not_count(client, make_user, db):
    """BD reiniciada con el índice viejo: el id se reutiliza y trae texto ajeno."""
    doc_id = _upload(client, make_user("admin"))
    _lose_index(doc_id)
    engine.vectorstore.add_texts(["texto de otro archivo"], metadatas=[
        {"document_id": doc_id, "filename": "otro.pdf", "chunk_index": 0}])

    _repair(db)

    found = engine.vectorstore.get(where={"document_id": doc_id}, include=["metadatas"])["metadatas"]
    assert {m["filename"] for m in found} == {"poliza.txt"}


def test_documents_that_cannot_be_indexed_are_skipped(make_user, db, monkeypatch):
    from tests.test_documents_access import _make_doc

    short = _make_doc(db, make_user("admin"), is_public=1)  # texto demasiado corto
    indexed = []
    monkeypatch.setattr(engine, "index_document", lambda d: indexed.append(d.id) or 1)
    _repair(db)
    assert short.id not in indexed


def test_one_failure_does_not_stop_the_rest(client, make_user, db, monkeypatch):
    admin = make_user("admin")
    bad, good = _upload(client, admin, "a.txt"), _upload(client, admin, "b.txt", TEXT + "Anexo dos.")
    _lose_index(bad)
    _lose_index(good)
    real = type(engine).index_document

    def flaky(doc):
        if doc.id == bad:
            raise RuntimeError("falla")
        return real(engine, doc)

    monkeypatch.setattr(engine, "index_document", flaky)
    _repair(db)
    has_fragments = lambda i: bool(engine.vectorstore.get(where={"document_id": i})["ids"])
    assert has_fragments(good) and not has_fragments(bad)
