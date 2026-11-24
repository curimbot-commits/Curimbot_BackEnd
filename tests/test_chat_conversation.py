"""Conversación del chat (memoria, saludos) y contexto completo para la voz."""

import inspect
import threading
import time
from types import SimpleNamespace

import pytest

from app.api.v1.routes import assistant
from app.models.models import AIInteractionLog, CurimMessage
from app.services.Curim.small_talk import small_talk_reply
from app.services.Curim.voice_rag_service import VoiceRAGService
from tests.test_assistant_history import _ask, _login

service = assistant.Curim_service
engine = service.rag_engine


@pytest.fixture
def chat(client, make_user, monkeypatch):
    """Usuario con sesión; anota lo que se busca y lo que se pide reescribir."""
    seen = SimpleNamespace(searched=[], rewritten=[])

    def fake_query(question, documents):
        seen.searched.append(question)
        return f"Respuesta a: {question}", 0.9, [1], []

    def fake_rewrite(question, history):
        seen.rewritten.append((question, history))
        return f"{question} [completa]"

    monkeypatch.setattr(engine, "query", fake_query)
    monkeypatch.setattr(engine, "rewrite_question", fake_rewrite)
    seen.user = make_user()
    _login(client, seen.user)
    return seen


# ── Memoria ──────────────────────────────────────────────────

def test_first_question_is_searched_as_written(client, chat):
    _ask(client, "¿Cuál es el deducible?")
    assert chat.searched == ["¿Cuál es el deducible?"]
    assert chat.rewritten == []


def test_follow_up_is_completed_with_the_conversation(client, chat):
    first = _ask(client, "¿Cuál es el deducible?")
    _ask(client, "¿y cuánto tarda?", conversation_id=first["conversation_id"])
    question, history = chat.rewritten[0]
    assert question == "¿y cuánto tarda?"
    assert history == [
        ("user", "¿Cuál es el deducible?"),
        ("assistant", "Respuesta a: ¿Cuál es el deducible?"),
    ]
    assert chat.searched[-1] == "¿y cuánto tarda? [completa]"


def test_history_keeps_what_the_user_wrote(client, chat, db):
    conv = _ask(client, "¿Cuál es el deducible?")["conversation_id"]
    _ask(client, "¿y cuánto tarda?", conversation_id=conv)
    db.rollback()
    last = (db.query(CurimMessage).filter_by(conversation_id=conv, role="user")
            .order_by(CurimMessage.id.desc()).first())
    assert last.content == "¿y cuánto tarda?"


def test_only_recent_messages_are_used(client, chat):
    conv = _ask(client, "pregunta inicial sobre pólizas")["conversation_id"]
    for i in range(5):
        _ask(client, f"pregunta número {i}", conversation_id=conv)
    _question, history = chat.rewritten[-1]
    assert len(history) == service.HISTORY_MESSAGES
    assert history[-1] == ("assistant", "Respuesta a: pregunta número 3 [completa]")


def test_other_users_conversation_is_never_used_as_memory(client, make_user, chat):
    conv = _ask(client, "dato privado")["conversation_id"]
    _login(client, make_user())
    _ask(client, "¿y cuánto tarda?", conversation_id=conv)
    assert chat.rewritten == []


def test_follow_ups_do_not_use_the_answer_cache(client, chat):
    conv = _ask(client, "¿Cuál es el deducible?")["conversation_id"]
    service.cache_manager.set(user_id=chat.user.id, question="¿y cuánto tarda?",
                              answer="de otra conversación", confidence=0.9, sources=[], sources_info=[])
    r = _ask(client, "¿y cuánto tarda?", conversation_id=conv, use_cache=True)
    assert r["from_cache"] is False
    assert r["answer"] != "de otra conversación"
    # y la respuesta, que depende de la conversación, tampoco se guarda
    assert service.cache_manager.get(chat.user.id, "¿y cuánto tarda?")["answer"] == "de otra conversación"
    service.clear_all_cache(chat.user.id)


# ── Reescritura ──────────────────────────────────────────────

HISTORY = [("user", "¿Cuál es el deducible?"), ("assistant", "1500 dólares.")]


def test_rewrite_sends_history_and_question_to_the_model(monkeypatch):
    seen = {}

    def fake(prompt, system_instruction=None, models=None):
        seen["prompt"], seen["models"] = prompt, models
        return "  ¿Cuánto tarda el deducible?\n"

    monkeypatch.setattr(engine, "_generate_text", fake)
    assert engine.rewrite_question("¿y cuánto tarda?", HISTORY) == "¿Cuánto tarda el deducible?"
    assert "1500 dólares." in seen["prompt"] and "¿y cuánto tarda?" in seen["prompt"]
    # tarea sencilla: primero el modelo ligero, el más rápido
    assert seen["models"] == list(reversed(engine._text_models()))


@pytest.mark.parametrize("result", ["", "   ", "x" * 1001, RuntimeError("503")],
                         ids=["vacía", "espacios", "demasiado larga", "error"])
def test_rewrite_falls_back_to_the_original_question(monkeypatch, result):
    def fake(prompt, system_instruction=None, models=None):
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(engine, "_generate_text", fake)
    assert engine.rewrite_question("¿y cuánto tarda?", HISTORY) == "¿y cuánto tarda?"


def test_slow_rewrite_does_not_hold_the_answer(monkeypatch):
    release = threading.Event()

    def slow(prompt, system_instruction=None, models=None):
        release.wait(5)
        return "tarde"

    monkeypatch.setattr(engine, "_generate_text", slow)
    monkeypatch.setattr(type(engine), "REWRITE_TIMEOUT_SECONDS", 0.2)
    start = time.monotonic()
    assert engine.rewrite_question("¿y cuánto tarda?", HISTORY) == "¿y cuánto tarda?"
    assert time.monotonic() - start < 2
    release.set()


# ── Saludos ──────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("hola", "Hola"), ("¡Hola!", "Hola"), ("Buenos días", "Hola"), ("hola, buenas tardes", "Hola"),
    ("gracias", "gusto"), ("Muchas gracias!", "gusto"), ("¿Qué puedes hacer?", "documentos"),
    ("hello", "Hello"), ("Good morning", "Hello"), ("thanks", "welcome"), ("What can you do?", "documents"),
])
def test_small_talk_gets_a_natural_reply(text, expected):
    assert expected in small_talk_reply(text)


@pytest.mark.parametrize("text", [
    "hola, ¿cuál es el deducible?", "¿Qué puedes hacer si me niegan un reclamo?",
    "gracias a qué cláusula aplica", "deducible", "", "hi risk policies",
])
def test_real_questions_are_not_small_talk(text):
    assert small_talk_reply(text) is None


def test_greeting_is_answered_without_searching_and_logged_as_success(client, chat, db):
    r = _ask(client, "hola")
    assert "Hola" in r["answer"] and r["sources"] == []
    assert chat.searched == []
    db.rollback()
    log = db.query(AIInteractionLog).filter(AIInteractionLog.user_id == chat.user.id).one()
    assert log.status.value == "success"


def test_greeting_does_not_count_as_conversation_memory(client, chat):
    conv = _ask(client, "hola")["conversation_id"]
    _ask(client, "¿Cuál es el deducible?", conversation_id=conv)
    assert chat.rewritten == []
    assert chat.searched == ["¿Cuál es el deducible?"]


# ── Contexto de voz ──────────────────────────────────────────

def _hit(doc_id, block):
    return SimpleNamespace(page_content=block[:20], metadata={
        "document_id": doc_id, "filename": f"{doc_id}.pdf", "block_text": block}), 0.2


def _voice(monkeypatch, hits, max_chars):
    monkeypatch.setattr("app.services.Curim.Curim_service.accessible_documents",
                        lambda db, uid: [SimpleNamespace(id=1, text="x")])
    context = "\n\n".join(doc.metadata["block_text"] for doc, _ in hits)
    monkeypatch.setattr(engine, "_retrieve_context_sync", lambda q, d: (context, hits))
    return VoiceRAGService().retrieve_context_with_sources("consulta", 1, None, max_chars=max_chars)


def test_voice_context_keeps_whole_blocks_and_their_sources(monkeypatch):
    a, b, c = "A" * 100, "B" * 100, "C" * 100
    context, sources = _voice(monkeypatch, [_hit(1, a), _hit(2, b), _hit(3, c)], max_chars=250)
    assert context == f"{a}\n\n{b}"
    assert [s["document_id"] for s in sources] == [1, 2]


def test_voice_context_always_has_the_best_block(monkeypatch):
    context, sources = _voice(monkeypatch, [_hit(1, "A" * 300), _hit(2, "B" * 10)], max_chars=250)
    assert context == "A" * 250
    assert [s["document_id"] for s in sources] == [1]


def test_voice_default_limit_fits_the_configured_context():
    limit = inspect.signature(VoiceRAGService.retrieve_context_with_sources).parameters["max_chars"].default
    assert limit >= 6000
