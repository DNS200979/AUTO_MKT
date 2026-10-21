import json
import logging

from fastapi.testclient import TestClient

from market_api.config import get_settings
from market_api.main import app
from market_api.observability import JsonFormatter, correlation_id_context


def configure(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARKET_DATABASE_URL", f"sqlite:///{tmp_path / 'observability.db'}")
    monkeypatch.setenv("MARKET_METRICS_ENABLED", "true")
    get_settings.cache_clear()


def test_correlation_id_is_echoed_and_included_in_errors(tmp_path, monkeypatch) -> None:
    configure(tmp_path, monkeypatch)

    with TestClient(app) as client:
        response = client.get(
            "/customers/CUST-MISSING", headers={"X-Correlation-ID": "pilot-request-123"}
        )

    assert response.status_code == 404
    assert response.headers["X-Correlation-ID"] == "pilot-request-123"
    assert response.json() == {
        "error": {"code": "NOT_FOUND", "message": "customer not found"},
        "correlation_id": "pilot-request-123",
    }


def test_validation_errors_use_stable_envelope(tmp_path, monkeypatch) -> None:
    configure(tmp_path, monkeypatch)

    with TestClient(app) as client:
        response = client.post("/customers", json={"name": "X", "phone": "invalid"})

    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "VALIDATION_ERROR",
        "message": "request validation failed",
    }
    assert response.json()["correlation_id"] == response.headers["X-Correlation-ID"]


def test_metrics_expose_http_series(tmp_path, monkeypatch) -> None:
    configure(tmp_path, monkeypatch)

    with TestClient(app) as client:
        client.get("/health")
        response = client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["Content-Type"]
    assert "market_http_requests_total" in response.text
    assert 'route="/health"' in response.text


def test_json_formatter_includes_context_without_sensitive_payload() -> None:
    token = correlation_id_context.set("correlation-test")
    try:
        record = logging.LogRecord(
            "market_api.test", logging.INFO, __file__, 1, "operation_completed", (), None
        )
        record.event = "test_event"
        record.result = "ok"
        payload = json.loads(JsonFormatter().format(record))
    finally:
        correlation_id_context.reset(token)

    assert payload["message"] == "operation_completed"
    assert payload["correlation_id"] == "correlation-test"
    assert payload["event"] == "test_event"
    assert payload["result"] == "ok"
