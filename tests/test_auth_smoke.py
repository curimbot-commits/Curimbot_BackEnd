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


def _login_2fa(client, email, code, password=TEST_PASSWORD):
    return client.post(
        "/auth/login-with-2fa",
        data={"username": email, "password": password, "totp_code": code},
    )


def test_login_with_2fa_success(client, make_user):
    user, secret = _two_fa_user(make_user)
    r = _login_2fa(client, user.email, pyotp.TOTP(secret).now())
    assert r.status_code == 200, r.text


def test_login_with_2fa_rejects_inactive_user(client, make_user):
    user, secret = _two_fa_user(make_user, is_active=False)
    r = _login_2fa(client, user.email, pyotp.TOTP(secret).now())
    assert r.status_code in (401, 423)


def test_login_with_2fa_rejects_locked_user(client, make_user):
    user, secret = _two_fa_user(
        make_user,
        failed_attempts=5,
        locked_until=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    r = _login_2fa(client, user.email, pyotp.TOTP(secret).now())
    assert r.status_code == 423


def test_login_with_2fa_bad_codes_lock_the_account(client, make_user, db):
    user, _ = _two_fa_user(make_user)
    for _ in range(5):
        assert _login_2fa(client, user.email, "000000").status_code == 401
    db.rollback()  # cierra el snapshot REPEATABLE READ de MySQL
    db.refresh(user)
    assert user.failed_attempts >= 5
    assert user.locked_until is not None
