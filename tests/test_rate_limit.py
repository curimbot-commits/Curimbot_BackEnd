"""Rate limiting en endpoints sensibles."""

import pytest

from app.core import rate_limit


@pytest.fixture
def limiter_on(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    rate_limit.reset()
    yield
    rate_limit.reset()


def test_login_is_rate_limited(client, limiter_on):
    data = {"username": "nadie@test.local", "password": "x"}
    codes = [client.post("/auth/login", data=data).status_code for _ in range(11)]
    assert codes[:10] == [401] * 10
    assert codes[10] == 429


def test_check_email_is_rate_limited(client, limiter_on):
    codes = [
        client.get("/password-reset/check-email", params={"email": "a@b.co"}).status_code
        for _ in range(11)
    ]
    assert 429 not in codes[:10]
    assert codes[10] == 429


def test_limit_is_per_endpoint(client, limiter_on):
    data = {"username": "nadie@test.local", "password": "x"}
    for _ in range(10):
        client.post("/auth/login", data=data)
    assert client.post("/auth/login", data=data).status_code == 429
    # Otro endpoint no comparte el contador
    r = client.get("/password-reset/check-email", params={"email": "a@b.co"})
    assert r.status_code != 429
