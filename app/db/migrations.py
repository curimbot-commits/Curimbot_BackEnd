"""
Migraciones de esquema con Alembic (única fuente del esquema).

`upgrade_to_head()` aplica las migraciones pendientes. Se ejecuta al
arrancar la app bajo un lock con nombre de MySQL, para que dos procesos
(varios workers o dos contenedores durante un redeploy) no migren a la vez.

Para crear una migración nueva tras cambiar un modelo:
    alembic revision --autogenerate -m "descripcion"
y revisar el archivo generado antes de hacer commit.
"""

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.db.database import engine

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[2]
MIGRATION_LOCK = "curim_schema_migration"
MIGRATION_LOCK_TIMEOUT_SECONDS = 120


def alembic_config() -> Config:
    """
    Config de Alembic sin alembic.ini: así env.py no llama a fileConfig()
    y no reconfigura (ni desactiva) los loggers de la aplicación.
    La URL de la BD la pone env.py desde settings.
    """
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


def head_revision() -> str:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def current_revision():
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def upgrade_to_head() -> None:
    """Aplica las migraciones pendientes (no hace nada si ya está en head)."""
    with engine.connect() as conn:
        acquired = conn.execute(
            text("SELECT GET_LOCK(:name, :timeout)"),
            {"name": MIGRATION_LOCK, "timeout": MIGRATION_LOCK_TIMEOUT_SECONDS},
        ).scalar()
        if acquired != 1:
            raise RuntimeError("No se pudo obtener el lock de migraciones")
        try:
            before = current_revision()
            command.upgrade(alembic_config(), "head")
            after = current_revision()
            if before != after:
                logger.info(f"Esquema migrado: {before} -> {after}")
            else:
                logger.info(f"Esquema al día ({after})")
        finally:
            conn.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": MIGRATION_LOCK})
