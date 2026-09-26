from __future__ import annotations

import inspect
import json
from types import SimpleNamespace

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.responses import JSONResponse

from backend.app import main


class FakeDatabase:
    def __init__(self, revisions: set[str], *, reachable: bool = True) -> None:
        self.revisions = revisions
        self.reachable = reachable
        self.closed = False

    def execute(self, _statement):
        if not self.reachable:
            raise ConnectionError("database unavailable")
        return SimpleNamespace()

    def scalars(self, _statement):
        return SimpleNamespace(all=lambda: list(self.revisions))

    def close(self) -> None:
        self.closed = True


def _body(response: JSONResponse) -> dict:
    return json.loads(response.body)


def test_readiness_accepts_exact_current_migration_heads(monkeypatch) -> None:
    heads = set(main.expected_migration_heads())
    database = FakeDatabase(heads)
    monkeypatch.setattr(main, "SessionLocal", lambda: database)

    response = main.ready()

    assert response["status"] == "ready"
    reported = response["migration"]
    assert set([reported] if isinstance(reported, str) else reported) == heads
    assert database.closed is True


def test_readiness_rejects_stale_database_revision(monkeypatch) -> None:
    database = FakeDatabase({"stale-revision"})
    monkeypatch.setattr(main, "SessionLocal", lambda: database)

    response = main.ready()

    assert isinstance(response, JSONResponse)
    assert response.status_code == 503
    assert _body(response) == {"status": "not_ready", "reason": "migration"}
    assert database.closed is True


def test_expected_head_is_resolved_from_alembic_scripts() -> None:
    config = Config(str(main.REPOSITORY_ROOT / "alembic.ini"))
    config.set_main_option(
        "script_location", str(main.REPOSITORY_ROOT / "backend" / "alembic")
    )
    repository_heads = frozenset(ScriptDirectory.from_config(config).get_heads())

    assert main.expected_migration_heads() == repository_heads
    assert repository_heads
    assert "20260926_0005" not in inspect.getsource(main.expected_migration_heads)


def test_readiness_reports_unreachable_database(monkeypatch) -> None:
    database = FakeDatabase(set(), reachable=False)
    monkeypatch.setattr(main, "SessionLocal", lambda: database)

    response = main.ready()

    assert isinstance(response, JSONResponse)
    assert response.status_code == 503
    assert _body(response) == {"status": "not_ready", "reason": "database"}
    assert database.closed is True
