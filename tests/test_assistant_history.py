"""Indexación/recuperación (texto y voz) e historial de interacciones."""

import json
from types import SimpleNamespace

from app.api.v1.routes import assistant
from app.models.models import AIInteractionLog, CurimMessage
from tests.conftest import login
from tests.test_documents_access import _make_doc

service = assistant.Curim_service


def _login(client, user):
    client.cookies.clear()
    assert login(client, user.email).status_code == 200


def _ask(client, question, **extra):
    r = client.post("/assistant/query", json={"question": question, "use_cache": False, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_text_without_context_is_logged_as_no_context(client, make_user, db, monkeypatch):
    monkeypatch.setattr(service.rag_engine, "query",
                        lambda question, documents: ("No encontré información.", 0.0, [], []))
    user = make_user()
    _login(client, user)
    _ask(client, "¿algo que no está?")
    db.rollback()
    log = db.query(AIInteractionLog).filter(AIInteractionLog.user_id == user.id).one()
    assert log.status.value == "no_context"


def test_text_with_sources_is_logged_as_success(client, make_user, db, monkeypatch):
    monkeypatch.setattr(service.rag_engine, "query", lambda question, documents: (
        "Respuesta", 0.9, [7], [{"document_id": 7, "filename": "a.pdf", "snippet": "..."}]))
    user = make_user()
    _login(client, user)
    _ask(client, "¿algo que sí está?")
    db.rollback()
    log = db.query(AIInteractionLog).filter(AIInteractionLog.user_id == user.id).one()
    assert log.status.value == "success" and json.loads(log.sources) == [7]


def test_follow_up_questions_stay_in_same_conversation(client, make_user, db, monkeypatch):
    monkeypatch.setattr(service.rag_engine, "query",
                        lambda question, documents: ("R", 0.9, [1], []))
    user = make_user()
    _login(client, user)
    first = _ask(client, "primera pregunta")
    second = _ask(client, "segunda pregunta", conversation_id=first["conversation_id"])
    assert second["conversation_id"] == first["conversation_id"]
    db.rollback()
    count = db.query(CurimMessage).filter(
        CurimMessage.conversation_id == first["conversation_id"]).count()
    assert count == 4  # 2 preguntas + 2 respuestas


def test_cannot_append_to_another_users_conversation(client, make_user, monkeypatch):
    monkeypatch.setattr(service.rag_engine, "query",
                        lambda question, documents: ("R", 0.9, [1], []))
    owner, other = make_user(), make_user()
    _login(client, owner)
    conv = _ask(client, "privada")["conversation_id"]
    _login(client, other)
    assert _ask(client, "intruso", conversation_id=conv)["conversation_id"] != conv


def test_voice_searches_own_and_public_admin_documents(client, make_user, db, monkeypatch):
    admin, user, stranger = make_user("admin"), make_user(), make_user()
    public = _make_doc(db, admin, is_public=1)
    own = _make_doc(db, user, is_public=0)
    private_other = _make_doc(db, stranger, is_public=0)

    seen = {}

    def fake_retrieve(question, documents):
        seen["ids"] = {d.id for d in documents}
        hit = SimpleNamespace(metadata={"document_id": public.id, "filename": public.filename})
        return "fragmento", [(hit, 0.2), (hit, 0.3)]

    monkeypatch.setattr(service.rag_engine, "_retrieve_context_sync", fake_retrieve)
    _login(client, user)
    r = client.post("/api/v1/voice/context", json={"query": "qué dice el documento"})
    assert r.status_code == 200
    body = r.json()
    assert {public.id, own.id} <= seen["ids"]
    assert private_other.id not in seen["ids"]
    assert body["found"] is True
    assert body["sources_info"] == [{"document_id": public.id, "filename": public.filename}]


def test_deleting_document_purges_index_and_caches(client, make_user, db, monkeypatch):
    user = make_user()
    doc = _make_doc(db, user, is_public=0)
    purged = []
    monkeypatch.setattr(service.rag_engine, "delete_document_chunks", purged.append)
    service.cache_manager.set(user_id=user.id, question="q", answer="a", confidence=0.9,
                              sources=[doc.id], sources_info=[])
    assert service.cache_manager.get_size(user.id) == 1

    _login(client, user)
    r = client.delete(f"/documents/{doc.id}")
    assert r.status_code in (200, 204), r.text
    assert purged == [doc.id]
    assert service.cache_manager.get_size(user.id) == 0


def test_voice_is_not_logged_and_history_has_utc_timestamps(client, make_user, db):
    """El historial es solo de texto: la voz ya no se registra."""
    from app.enums.enums import AIChannel
    from app.services.handlers.log_activity import LogAIInteractionHandler

    user = make_user()
    _login(client, user)
    r = client.post("/api/v1/voice/log-interaction", json={"question": "q", "answer": "a"})
    assert r.status_code == 404

    LogAIInteractionHandler.log(db=db, user_id=user.id, question="pregunta", answer="respuesta",
                                channel=AIChannel.text, sources=[3])
    history = client.get("/documents/ai-interactions/recent", params={"limit": 10}).json()
    assert [h["channel"] for h in history] == ["text"]
    assert history[0]["sources"] == [3]
    ts = history[0]["timestamp"]
    assert ts.endswith("Z") or ts.endswith("+00:00"), ts  # UTC explicito
