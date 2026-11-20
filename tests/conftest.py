"""
Fixtures compartidas para los tests de humo del backend.

Los tests usan una base de datos MySQL aislada (`<DB_NAME>_test`) en el mismo
servidor configurado en `.env`, para no tocar la base de datos de desarrollo.
La variable DATABASE_URL se sobrescribe ANTES de importar la aplicación.
"""

import os
import re
import uuid
from pathlib import Path

import pytest
from dotenv import dotenv_values

BACKEND_DIR = Path(__file__).resolve().parent.parent
os.chdir(BACKEND_DIR)  # .env, enc.key y uploads/ se resuelven relativos a BackEnd/

_env = dotenv_values(BACKEND_DIR / ".env")
_base_url = os.getenv("DATABASE_URL") or _env.get("DATABASE_URL")
if not _base_url or not _base_url.startswith("mysql"):
    raise RuntimeError("Los tests requieren DATABASE_URL de MySQL en .env")

# mysql+pymysql://user:pass@host:port/curim_db?charset=...  ->  .../curim_db_test?...
TEST_DB_URL = re.sub(r"/([^/?]+)(\?|$)", r"/\1_test\2", _base_url, count=1)
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["TESTING"] = "1"
os.environ["RATE_LIMIT_ENABLED"] = "false"  # los tests de rate limit lo activan explícitamente

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

_url = make_url(TEST_DB_URL)
_server_engine = create_engine(_url.set(database=""))
assert _url.database.endswith("_test"), "Abortado: no es la BD de tests"
with _server_engine.connect() as conn:
    # Se recrea vacía en cada ejecución: el esquema lo crean las migraciones
    conn.execute(text(f"DROP DATABASE IF EXISTS `{_url.database}`"))
    conn.execute(text(f"CREATE DATABASE `{_url.database}` CHARACTER SET utf8mb4"))
_server_engine.dispose()

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from app.core.init_roles import init_roles  # noqa: E402
from app.db.database import SessionLocal, engine  # noqa: E402
from app.db.migrations import upgrade_to_head  # noqa: E402
from app.models.auth_models import Role, User  # noqa: E402
from app.services import security_service  # noqa: E402

TEST_PASSWORD = "Sup3r-Secret-Pass!"


@pytest.fixture(scope="session", autouse=True)
def _schema():
    assert engine.url.database.endswith("_test"), "Abortado: no es la BD de tests"
    upgrade_to_head()  # valida la migración en cada ejecución
    with SessionLocal() as db:
        init_roles(db)
        db.commit()
    yield
    engine.dispose()


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    """Cliente HTTP sin lifespan (no arranca scheduler ni motor de voz)."""
    return TestClient(main.app)


@pytest.fixture
def make_user(db):
    def _make(role: str = "user", **fields) -> User:
        role_obj = db.query(Role).filter(Role.name == role).one()
        fields.setdefault("is_active", True)
        user = User(
            email=f"{role}-{uuid.uuid4().hex[:10]}@test.local",
            name=f"Test {role}",
            password_hash=security_service.hash_password(TEST_PASSWORD),
            role_id=role_obj.id,
            **fields,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    return _make


def login(client: TestClient, email: str, password: str = TEST_PASSWORD):
    return client.post("/auth/login", data={"username": email, "password": password})
