"""Flujo OAuth (Google) con los servicios externos simulados."""

import uuid
from urllib.parse import parse_qs, urlparse

import pytest

from app.services.oauth_service import OAuthService


@pytest.fixture
def fake_google(monkeypatch):
    profile = {"sub": f"g-{uuid.uuid4().hex}", "email": "", "name": "G User", "email_verified": True}

    async def fake_exchange(code, redirect_uri):
        return {"access_token": "google-access"}

    async def fake_profile(access_token):
        return dict(profile)

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client")
    monkeypatch.setattr(OAuthService, "_exchange_google_code", staticmethod(fake_exchange))
    monkeypatch.setattr(OAuthService, "_get_google_profile", staticmethod(fake_profile))
    return profile


def _start(client):
    """Inicia el login: devuelve el state que el navegador mandaría de vuelta."""
    client.cookies.clear()
    r = client.get("/auth/google/login", follow_redirects=False)
    assert r.status_code in (302, 307), r.text
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    assert client.cookies.get("oauth_state") == state
    return state


def _callback(client, state):
    return client.get(
        "/auth/google/callback",
        params={"code": "abc", "state": state},
        follow_redirects=False,
    )


def test_oauth_success_sets_cookies_without_tokens_in_url(client, make_user, fake_google):
    user = make_user()
    fake_google["email"] = user.email
    r = _callback(client, _start(client))

    location = r.headers["location"]
    assert location.endswith("/auth/callback?status=success"), location
    assert "token" not in location
    assert "access_token" in r.cookies

    client.cookies.clear()
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {r.cookies['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == user.email


def test_oauth_rejects_state_without_matching_cookie(client, fake_google):
    state = _start(client)
    client.cookies.clear()  # otro navegador: no tiene la cookie oauth_state
    r = _callback(client, state)
    assert r.headers["location"].endswith("error=invalid_state")


def test_oauth_rejects_forged_state(client, fake_google):
    _start(client)
    client.cookies.set("oauth_state", "1.forjado.firma")
    r = _callback(client, "1.forjado.firma")
    assert r.headers["location"].endswith("error=invalid_state")


def test_oauth_requires_verified_google_email(client, make_user, fake_google):
    user = make_user()
    fake_google.update(email=user.email, email_verified=False)
    r = _callback(client, _start(client))
    assert r.headers["location"].endswith("error=email_not_verified")
    assert "access_token" not in r.cookies


def test_oauth_rejects_inactive_user(client, make_user, fake_google):
    user = make_user(is_active=False)
    fake_google["email"] = user.email
    r = _callback(client, _start(client))
    assert r.headers["location"].endswith("error=account_disabled")
    assert "access_token" not in r.cookies


def test_oauth_with_2fa_returns_challenge_in_fragment(client, make_user, fake_google):
    import pyotp

    user = make_user(two_factor_enabled=True, two_factor_secret=pyotp.random_base32())
    fake_google["email"] = user.email
    r = _callback(client, _start(client))

    location = r.headers["location"]
    assert "access_token" not in r.cookies
    path, _, fragment = location.partition("#")
    assert path.endswith("/auth/callback")
    params = parse_qs(fragment)
    assert params["requires_2fa"] == ["1"]
    assert params["email"] == [user.email]
    challenge = params["challenge"][0]

    code = pyotp.TOTP(user.two_factor_secret).now()
    r2 = client.post("/auth/login-with-2fa", data={"challenge_token": challenge, "totp_code": code})
    assert r2.status_code == 200, r2.text


def test_set_cookies_endpoint_was_removed(client):
    r = client.post("/auth/oauth/set-cookies", json={"token": "x", "refresh": "y"})
    assert r.status_code in (404, 405)


def test_github_login_was_removed(client):
    assert client.get("/auth/github/login", follow_redirects=False).status_code == 404
    assert client.get("/auth/github/callback", follow_redirects=False).status_code == 404
