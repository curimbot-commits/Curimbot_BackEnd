"""Configuración y gestión del 2FA (/auth/2fa/*)."""

import time

import pyotp

from app.services.auth_service import TwoFactorAuthService
from tests.conftest import login


def _login(client, user):
    client.cookies.clear()
    assert login(client, user.email).status_code == 200


def _enable(client, db, user):
    """setup + confirm; devuelve (secreto, códigos de respaldo)."""
    r = client.post("/auth/2fa/setup")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "backup_codes" not in body  # ya no se dan antes de confirmar
    secret = body["secret"]

    r = client.post("/auth/2fa/confirm", json={"code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200, r.text
    codes = r.json()["backup_codes"]
    db.rollback()  # cierra el snapshot REPEATABLE READ de MySQL
    assert len(codes) == 8
    db.rollback()
    db.refresh(user)
    return secret, codes


def test_setup_confirm_stores_encrypted_secret(client, make_user, db):
    user = make_user()
    _login(client, user)
    secret, _ = _enable(client, db, user)

    assert user.two_factor_enabled
    assert user.two_factor_secret_temp is None
    assert user.two_factor_secret != secret  # no en claro
    assert user.two_factor_secret.startswith("gAAAA")
    assert TwoFactorAuthService.decrypt_secret(user.two_factor_secret) == secret


def test_qr_issuer_is_curim(client, make_user):
    user = make_user()
    _login(client, user)
    secret = client.post("/auth/2fa/setup").json()["secret"]
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=TwoFactorAuthService.ISSUER_NAME)
    assert "issuer=Curim" in uri


def test_totp_code_cannot_be_reused(make_user, db):
    secret = pyotp.random_base32()
    user = make_user(two_factor_enabled=True, two_factor_secret=TwoFactorAuthService.encrypt_secret(secret))
    code = pyotp.TOTP(secret).now()
    assert TwoFactorAuthService.verify_user_totp(user, code)
    assert not TwoFactorAuthService.verify_user_totp(user, code)  # mismo código otra vez


def test_legacy_plaintext_secret_still_works(make_user):
    secret = pyotp.random_base32()
    user = make_user(two_factor_enabled=True, two_factor_secret=secret)
    assert TwoFactorAuthService.verify_user_totp(user, pyotp.TOTP(secret).now())


def test_disable_with_backup_code(client, make_user, db):
    user = make_user()
    _login(client, user)
    _, codes = _enable(client, db, user)

    r = client.post("/auth/2fa/disable", json={"code": codes[0].lower()})
    assert r.status_code == 200, r.text
    db.rollback()
    db.refresh(user)
    assert not user.two_factor_enabled
    assert user.two_factor_secret is None
    assert user.backup_codes is None


def test_disable_with_wrong_code_keeps_2fa(client, make_user, db):
    user = make_user()
    _login(client, user)
    _enable(client, db, user)
    r = client.post("/auth/2fa/disable", json={"code": "000000"})
    assert r.status_code == 400
    db.rollback()
    db.refresh(user)
    assert user.two_factor_enabled


def test_regenerate_requires_totp_and_replaces_codes(client, make_user, db):
    user = make_user()
    _login(client, user)
    secret, old_codes = _enable(client, db, user)

    assert client.post("/auth/2fa/regenerate-backup-codes", json={"code": "000000"}).status_code == 400

    # El código usado en confirm ya no vale: se usa el del siguiente periodo.
    totp = pyotp.TOTP(secret)
    next_code = totp.at(time.time() + 30)
    r = client.post("/auth/2fa/regenerate-backup-codes", json={"code": next_code})
    assert r.status_code == 200, r.text
    new_codes = r.json()["backup_codes"]
    assert set(new_codes).isdisjoint(old_codes)

    db.rollback()
    db.refresh(user)
    assert not TwoFactorAuthService.verify_backup_code(user, old_codes[0], db)
    assert TwoFactorAuthService.verify_backup_code(user, new_codes[0], db)


def test_removed_endpoints_are_gone(client, make_user):
    user = make_user()
    _login(client, user)
    assert client.get("/auth/2fa/status").status_code in (404, 405)
    assert client.post("/auth/2fa/backup-codes").status_code in (404, 405)


def test_two_factor_code_endpoints_are_rate_limited():
    """Los endpoints que verifican códigos de 6 dígitos tienen límite de intentos."""
    from app.api.v1.routes.auth_endpoints import verficacion2p

    for route in verficacion2p.router.routes:
        names = [d.call.__qualname__ for d in route.dependant.dependencies]
        assert any("rate_limit" in n for n in names), route.path
