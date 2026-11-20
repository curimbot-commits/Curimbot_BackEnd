"""Los endpoints con trabajo síncrono (BD, RAG, LLM) no deben ser `async def`:
FastAPI los ejecuta en el threadpool y así no bloquean el event loop."""

import inspect

import pytest

from app.api.v1.routes import assistant, voice_endpoints


@pytest.mark.parametrize("endpoint", [
    assistant.ask_Curim,
    assistant.get_conversation_history,
    assistant.sync_documents,
    assistant.get_Curim_status,
    assistant.clear_cache,
    assistant.get_cache_stats,
    voice_endpoints.get_voice_context,
    voice_endpoints.log_voice_interaction,
])
def test_sync_work_runs_in_threadpool(endpoint):
    assert not inspect.iscoroutinefunction(endpoint)


def test_assistant_query_works_from_threadpool(client, make_user, monkeypatch):
    from tests.conftest import login

    captured = {}

    def fake_ask(db, user, question, document_ids, use_cache):
        captured["question"] = question
        return {
            "answer": "respuesta", "sources": [], "confidence": 0.9,
            "from_cache": False, "processing_time_ms": 1, "conversation_id": 1,
        }

    monkeypatch.setattr(assistant.Curim_service, "ask_question", fake_ask)
    user = make_user()
    assert login(client, user.email).status_code == 200
    r = client.post("/assistant/query", json={"question": "¿hola?"})
    assert r.status_code == 200, r.text
    assert captured["question"] == "¿hola?"
