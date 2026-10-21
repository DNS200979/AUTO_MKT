from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from .repository import SqlRepository, metadata


def migration_revisions(repository: SqlRepository) -> tuple[str | None, str]:
    candidates = (
        Path.cwd() / "alembic.ini",
        Path(__file__).resolve().parents[2] / "alembic.ini",
    )
    config_path = next((path for path in candidates if path.is_file()), None)
    if config_path is None:
        raise RuntimeError("alembic.ini was not found")
    config = Config(str(config_path))
    scripts = ScriptDirectory.from_config(config)
    with repository.engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
    return current, scripts.get_current_head()


def readiness(repository: SqlRepository, *, enforce_migration_head: bool) -> dict[str, object]:
    repository.ping()
    existing = set(inspect(repository.engine).get_table_names())
    required = set(metadata.tables)
    missing = sorted(required - existing)
    if missing:
        raise RuntimeError(f"database schema is missing tables: {', '.join(missing)}")
    details: dict[str, object] = {"database": "ok", "schema": "ok"}
    if enforce_migration_head:
        current, head = migration_revisions(repository)
        if current != head:
            raise RuntimeError(f"database migration is not current: current={current}, head={head}")
        details["migration"] = head
    return details
