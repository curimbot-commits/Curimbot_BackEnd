"""Tests de humo del flujo de autenticación (login, /me, refresh, 2FA)."""

from datetime import datetime, timedelta, timezone

import pyotp

from tests.conftest import TEST_PASSWORD, login


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Login básico ────────────────────────────────────────────────────────────

def test_login_success_returns_tokens_and_cookies(client, make_user):
    user = make_user()
    r = login(client, user.email)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"] and body["refresh_token"]
    assert "access_token" in r.cookies


def test_login_wrong_password_is_401(client, make_user):
    user = make_user()
    r = login(client, user.email, "wrong-password")
    assert r.status_code == 401


def test_me_with_access_token(client, make_user):
    user = make_user()
    access = login(client, user.email).json()["access_token"]
    client.cookies.clear()
    r = client.get("/auth/me", headers=_bearer(access))
    assert r.status_code == 200, r.text
    assert r.json()["email"] == user.email


def test_refresh_token_is_rejected_as_access_token(client, make_user):
    user = make_user()
    refresh = login(client, user.email).json()["refresh_token"]
    client.cookies.clear()
    r = client.get("/auth/me", headers=_bearer(refresh))
    assert r.status_code == 401


def test_invalid_or_expired_token_is_401_not_500(client):
    from datetime import timedelta as _td

    from app.services import security_service

    expired = security_service.create_access_token({"sub": "1"}, expires_delta=_td(seconds=-5))
    for token in ("basura.no.jwt", expired):
        r = client.get("/auth/me", headers=_bearer(token))
        assert r.status_code == 401, (token[:10], r.status_code, r.text)


# ── Login con 2FA ───────────────────────────────────────────────────────────

def _two_fa_user(make_user, **fields):
    secret = pyotp.random_base32()
    user = make_user(two_factor_enabled=True, two_factor_secret=secret, **fields)
    return user, secret


def _challenge(client, email) -> str:
    """Paso 1: login con contraseña → challenge_token (sin cookies de sesión)."""
    client.cookies.clear()
    r = login(client, email)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["requires_2fa"] is True
    assert "access_token" not in body and "access_token" not in r.cookies
    return body["challenge_token"]


def _login_2fa(client, challenge, code):
    """Paso 2: challenge_token + código. La contraseña ya no se reenvía."""
    return client.post(
        "/auth/login-with-2fa",
        data={"challenge_token": challenge, "totp_code": code},
    )


def test_login_with_2fa_success(client, make_user):
    user, secret = _two_fa_user(make_user)
    challenge = _challenge(client, user.email)
    r = _login_2fa(client, challenge, pyotp.TOTP(secret).now())
    assert r.status_code == 200, r.text
    assert "access_token" in r.cookies


def test_login_with_2fa_challenge_is_single_use(client, make_user):
    user, secret = _two_fa_user(make_user)
    challenge = _challenge(client, user.email)
    assert _login_2fa(client, challenge, pyotp.TOTP(secret).now()).status_code == 200
    assert _login_2fa(client, challenge, pyotp.TOTP(secret).now()).status_code == 401


def test_login_with_2fa_rejects_access_token_as_challenge(client, make_user):
    user, secret = _two_fa_user(make_user)
    from app.services import security_service

    access = security_service.create_access_token({"sub": str(user.id)})
    r = _login_2fa(client, access, pyotp.TOTP(secret).now())
    assert r.status_code == 401


def test_challenge_token_is_not_an_access_token(client, make_user):
    user, _ = _two_fa_user(make_user)
    challenge = _challenge(client, user.email)
    assert client.get("/auth/me", headers=_bearer(challenge)).status_code == 401


def test_login_with_2fa_rejects_inactive_user(client, make_user, db):
    user, secret = _two_fa_user(make_user)
    challenge = _challenge(client, user.email)
    user.is_active = False
    db.commit()
    r = _login_2fa(client, challenge, pyotp.TOTP(secret).now())
    assert r.status_code in (401, 423)


def test_login_with_2fa_rejects_locked_user(client, make_user, db):
    user, secret = _two_fa_user(make_user)
    challenge = _challenge(client, user.email)
    user.failed_attempts = 5
    user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=10)
    db.commit()
    r = _login_2fa(client, challenge, pyotp.TOTP(secret).now())
    assert r.status_code == 423


def test_login_with_2fa_bad_codes_lock_the_account(client, make_user, db):
    user, _ = _two_fa_user(make_user)
    challenge = _challenge(client, user.email)
    for _ in range(5):
        assert _login_2fa(client, challenge, "000000").status_code == 401
    db.rollback()  # cierra el snapshot REPEATABLE READ de MySQL
    db.refresh(user)
    assert user.failed_attempts >= 5
    assert user.locked_until is not None
