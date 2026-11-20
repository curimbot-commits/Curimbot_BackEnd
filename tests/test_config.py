"""Validaciones de configuración para producción."""

import pytest

from app.core.config import Settings

STRONG = "x" * 48


def _settings(**overrides) -> Settings:
    # _env_file=None: no leer .env; solo los valores del test.
    return Settings(_env_file=None, **overrides)


def test_production_rejects_default_secret_key():
    s = _settings(ENV="production", SECRET_KEY="defaultsecret", COOKIE_SECURE=True)
    with pytest.raises(ValueError, match="SECRET_KEY"):
        s.validate_production()


def test_production_rejects_short_secret_key():
    s = _settings(ENV="production", SECRET_KEY="corta", COOKIE_SECURE=True)
    with pytest.raises(ValueError, match="SECRET_KEY"):
        s.validate_production()


def test_production_requires_secure_cookies():
    s = _settings(ENV="production", SECRET_KEY=STRONG, COOKIE_SECURE=False)
    with pytest.raises(ValueError, match="COOKIE_SECURE"):
        s.validate_production()


def test_production_rejects_debug():
    s = _settings(ENV="production", SECRET_KEY=STRONG, COOKIE_SECURE=True, DEBUG=True)
    with pytest.raises(ValueError, match="DEBUG"):
        s.validate_production()


def test_valid_production_config_passes():
    s = _settings(ENV="production", SECRET_KEY=STRONG, COOKIE_SECURE=True)
    s.validate_production()
    assert s.is_production


def test_development_is_not_validated():
    s = _settings(ENV="development", SECRET_KEY="defaultsecret")
    s.validate_production()  # no-op fuera de producción
    assert not s.is_production
    assert s.DEBUG is False  # el default ya no es True
