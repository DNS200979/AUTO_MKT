from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from market_api.config import get_settings
from market_api.main import app
from market_api.operations import migration_revisions
from market_api.repository import SqlRepository, metadata


def alembic_config() -> Config:
    return Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))


def test_initial_migration_upgrades_and_downgrades(tmp_path, monkeypatch) -> None:
    database_url = f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("MARKET_DATABASE_URL", database_url)
    get_settings.cache_clear()

    command.upgrade(alembic_config(), "head")

    engine = create_engine(database_url)
    tables = set(inspect(engine).get_table_names())
    assert set(metadata.tables) <= tables
    repository = SqlRepository.connect(database_url, create_schema=False)
    current, head = migration_revisions(repository)
    assert current == head

    command.downgrade(alembic_config(), "base")
    assert not (set(metadata.tables) & set(inspect(engine).get_table_names()))


def test_readiness_reports_database_and_schema(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARKET_DATABASE_URL", f"sqlite:///{tmp_path / 'ready.db'}")
    monkeypatch.setenv("MARKET_AUTO_CREATE_SCHEMA", "true")
    monkeypatch.setenv("MARKET_ENFORCE_MIGRATION_HEAD", "false")
    get_settings.cache_clear()

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok", "schema": "ok"}


def test_readiness_fails_when_schema_is_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARKET_DATABASE_URL", f"sqlite:///{tmp_path / 'missing.db'}")
    monkeypatch.setenv("MARKET_AUTO_CREATE_SCHEMA", "false")
    monkeypatch.setenv("MARKET_ENFORCE_MIGRATION_HEAD", "false")
    get_settings.cache_clear()

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert "missing tables" in response.json()["detail"]


def test_operator_overview_is_safe_and_empty_for_new_store(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARKET_DATABASE_URL", f"sqlite:///{tmp_path / 'overview.db'}")
    monkeypatch.setenv("MARKET_AUTO_CREATE_SCHEMA", "true")
    get_settings.cache_clear()

    with TestClient(app) as client:
        response = client.get("/operator/overview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["customers_by_status"] == {}
    assert payload["payments_by_status"] == {}
    assert payload["open_debts"] == {"count": 0, "amount_cents": 0}
    assert payload["failed_notifications"] == 0
    assert payload["recent_events"] == []


def test_operator_console_origin_is_allowed(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARKET_DATABASE_URL", f"sqlite:///{tmp_path / 'cors.db'}")
    monkeypatch.setenv("MARKET_AUTO_CREATE_SCHEMA", "true")
    get_settings.cache_clear()

    with TestClient(app) as client:
        response = client.get("/operator/overview", headers={"Origin": "http://127.0.0.1:5173"})

    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
