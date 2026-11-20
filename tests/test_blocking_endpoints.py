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
])
def test_sync_work_runs_in_threadpool(endpoint):
    assert not inspect.iscoroutinefunction(endpoint)


def test_assistant_query_works_from_threadpool(client, make_user, monkeypatch):
    from tests.conftest import login

    captured = {}

    def fake_ask(db, user, question, document_ids, use_cache, conversation_id=None):
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


def test_llm_failure_returns_500_and_logs_error(client, make_user, db, monkeypatch):
    """Si Gemini falla, no se devuelve un texto de error como respuesta válida."""
    from app.models.models import AIInteractionLog
    from tests.conftest import login

    service = assistant.Curim_service

    def boom(question, documents):
        raise RuntimeError("404 model no longer available")

    monkeypatch.setattr(service.rag_engine, "query", boom)
    monkeypatch.setattr(service, "_get_user_documents", lambda db, uid, ids: [])
    monkeypatch.setattr(service.cache_manager, "get", lambda **kw: None, raising=False)

    user = make_user()
    assert login(client, user.email).status_code == 200
    r = client.post("/assistant/query", json={"question": "¿algo?", "use_cache": False})
    assert r.status_code == 500
    assert "no longer available" not in r.text

    db.rollback()
    log = db.query(AIInteractionLog).filter(AIInteractionLog.user_id == user.id).one()
    assert log.status.value == "error"


def _engine_with(responses):
    """VoiceRAGEngine sin inicializar, con un cliente falso de google-genai."""
    from types import SimpleNamespace

    from app.services.Curim.rag_engine import VoiceRAGEngine

    calls = []

    def generate_content(model, contents, config):
        calls.append(model)
        result = responses[model]
        if isinstance(result, Exception):
            raise result
        return SimpleNamespace(text=result)

    engine = VoiceRAGEngine.__new__(VoiceRAGEngine)
    engine.text_client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    return engine, calls


def _api_error(code):
    from google.genai import errors

    return errors.APIError(code, {"error": {"code": code, "message": "x", "status": "X"}})


def test_text_generation_falls_back_when_model_unavailable(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "GEMINI_TEXT_MODEL", "principal")
    monkeypatch.setattr(settings, "GEMINI_TEXT_FALLBACK_MODELS", "saturado,respaldo")
    engine, calls = _engine_with({
        "principal": _api_error(404),   # "no longer available to new users"
        "saturado": _api_error(503),    # high demand
        "respaldo": "respuesta",
    })
    assert engine._generate_text("p") == "respuesta"
    assert calls == ["principal", "saturado", "respaldo"]


def test_text_generation_does_not_retry_auth_errors(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "GEMINI_TEXT_MODEL", "principal")
    monkeypatch.setattr(settings, "GEMINI_TEXT_FALLBACK_MODELS", "respaldo")
    engine, calls = _engine_with({"principal": _api_error(403), "respaldo": "no"})
    with pytest.raises(Exception):
        engine._generate_text("p")
    assert calls == ["principal"]


def test_text_generation_sends_rules_as_system_instruction(monkeypatch):
    """Las reglas van en system_instruction, no en el texto del prompt (el modelo las repetía)."""
    from types import SimpleNamespace

    from app.core.config import settings
    from app.services.Curim.rag_engine import VoiceRAGEngine

    monkeypatch.setattr(settings, "GEMINI_TEXT_MODEL", "principal")
    monkeypatch.setattr(settings, "GEMINI_TEXT_FALLBACK_MODELS", "")
    seen = {}

    def generate_content(model, contents, config):
        seen["contents"] = contents
        seen["config"] = config
        return SimpleNamespace(text="ok", candidates=[])

    engine = VoiceRAGEngine.__new__(VoiceRAGEngine)
    engine.text_client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))

    assert engine._generate_text("CONTEXTO: x", "REGLAS") == "ok"
    assert seen["contents"] == "CONTEXTO: x"
    assert seen["config"].system_instruction == "REGLAS"
    assert seen["config"].max_output_tokens == settings.GEMINI_TEXT_MAX_OUTPUT_TOKENS
    assert seen["config"].thinking_config.thinking_budget == settings.GEMINI_TEXT_THINKING_BUDGET


def test_text_generation_retries_without_thinking_config(monkeypatch):
    """Si el modelo rechaza thinking_budget (400), se reintenta sin esa opción."""
    from types import SimpleNamespace

    from google.genai import errors

    from app.core.config import settings
    from app.services.Curim.rag_engine import VoiceRAGEngine

    monkeypatch.setattr(settings, "GEMINI_TEXT_MODEL", "principal")
    monkeypatch.setattr(settings, "GEMINI_TEXT_FALLBACK_MODELS", "")
    configs = []

    def generate_content(model, contents, config):
        configs.append(config)
        if config.thinking_config is not None:
            raise errors.APIError(400, {"error": {"code": 400, "message": "Request contains an invalid argument.", "status": "INVALID_ARGUMENT"}})
        return SimpleNamespace(text="ok")

    engine = VoiceRAGEngine.__new__(VoiceRAGEngine)
    engine.text_client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))

    assert engine._generate_text("p", "r") == "ok"
    assert len(configs) == 2
    assert configs[1].thinking_config is None
    assert configs[1].system_instruction == "r"
