"""Alembic es la única fuente del esquema: los modelos y las migraciones coinciden."""

from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext

from app.db.database import Base, engine
from app.db.migrations import current_revision, head_revision


def test_database_is_at_head():
    assert current_revision() == head_revision()


def test_models_match_migrations():
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        diff = compare_metadata(ctx, Base.metadata)
    assert diff == [], f"Modelos sin migración: ejecuta 'alembic revision --autogenerate'. {diff}"


def test_startup_migration_is_idempotent():
    import main

    main.ensure_database()  # ya en head: no debe fallar ni cambiar nada
    assert current_revision() == head_revision()
