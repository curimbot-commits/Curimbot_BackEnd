"""El resumen semanal solo lo ejecuta el proceso que obtiene el lock de MySQL."""

from sqlalchemy import text

from app.core.scheduler import run_with_lock
from app.db.database import engine


def test_job_runs_when_lock_is_free():
    calls = []
    assert run_with_lock("curim_test_lock", lambda: calls.append(1)) is True
    assert calls == [1]


def test_job_skipped_when_another_process_holds_lock():
    calls = []
    with engine.connect() as other:  # simula otro worker/contenedor
        assert other.execute(text("SELECT GET_LOCK('curim_test_lock', 0)")).scalar() == 1
        try:
            assert run_with_lock("curim_test_lock", lambda: calls.append(1)) is False
        finally:
            other.execute(text("SELECT RELEASE_LOCK('curim_test_lock')"))
    assert calls == []


def test_lock_released_even_if_job_fails():
    def boom():
        raise RuntimeError("fallo")

    try:
        run_with_lock("curim_test_lock", boom)
    except RuntimeError:
        pass
    assert run_with_lock("curim_test_lock", lambda: None) is True
