"""Tests de la carga de la clave de cifrado (ENC_KEY / ENC_KEY_PATH / ENV)."""

import importlib

import pytest
from cryptography.fernet import Fernet

from app.services import storage_service


@pytest.fixture
def reload_storage(monkeypatch):
    # Aislar de .env: storage_service llama load_dotenv() al importarse.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)

    def _reload():
        return importlib.reload(storage_service)

    yield _reload
    monkeypatch.undo()
    importlib.reload(storage_service)  # restaura la clave real para el resto de tests


def test_env_key_takes_priority(monkeypatch, reload_storage, tmp_path):
    key = Fernet.generate_key()
    monkeypatch.setenv("ENC_KEY", key.decode())
    monkeypatch.setenv("ENC_KEY_PATH", str(tmp_path / "no-existe.key"))
    mod = reload_storage()
    token = mod.encrypt_bytes(b"hola")
    assert Fernet(key).decrypt(token) == b"hola"
    assert not (tmp_path / "no-existe.key").exists()


def test_production_without_key_fails_fast(monkeypatch, reload_storage, tmp_path):
    monkeypatch.delenv("ENC_KEY", raising=False)
    monkeypatch.setenv("ENC_KEY_PATH", str(tmp_path / "no-existe.key"))
    monkeypatch.setenv("ENV", "production")
    with pytest.raises(RuntimeError, match="ENC_KEY"):
        reload_storage()
    assert not (tmp_path / "no-existe.key").exists()
