"""El endpoint de voz debe entregar un token efímero, nunca la API key real."""

import os
from types import SimpleNamespace

from app.api.v1.routes import voice_endpoints
from tests.conftest import login


def test_voice_token_requires_auth(client):
    client.cookies.clear()
    assert client.get("/api/v1/voice/token").status_code == 401


def test_voice_token_returns_ephemeral_token_not_api_key(client, make_user, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-real-key-que-no-debe-salir")
    captured = {}

    async def fake_create(config):
        captured["config"] = config
        return SimpleNamespace(name="auth_tokens/efimero123")

    monkeypatch.setattr(voice_endpoints, "_create_auth_token", fake_create)

    user = make_user()
    client.cookies.clear()
    assert login(client, user.email).status_code == 200
    r = client.get("/api/v1/voice/token")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token"] == "auth_tokens/efimero123"
    assert "AIza" not in r.text
    cfg = captured["config"]
    assert cfg.uses == 1
    assert cfg.live_connect_constraints.model == voice_endpoints.GEMINI_LIVE_MODEL


def test_voice_token_unavailable_without_api_key(client, make_user, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    user = make_user()
    client.cookies.clear()
    assert login(client, user.email).status_code == 200
    assert client.get("/api/v1/voice/token").status_code == 503
