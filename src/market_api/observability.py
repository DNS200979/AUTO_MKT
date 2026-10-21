from __future__ import annotations

import json
import logging
import time
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

correlation_id_context: ContextVar[str] = ContextVar("correlation_id", default="")

HTTP_REQUESTS = Counter(
    "market_http_requests_total",
    "Total de requisicoes HTTP.",
    ("method", "route", "status"),
)
HTTP_DURATION = Histogram(
    "market_http_request_duration_seconds",
    "Duracao das requisicoes HTTP.",
    ("method", "route"),
)
BUSINESS_EVENTS = Counter(
    "market_business_events_total",
    "Eventos operacionais relevantes.",
    ("event", "result"),
)
WORKER_DELIVERIES = Counter(
    "market_notification_deliveries_total",
    "Resultados de entrega do worker.",
    ("channel", "result"),
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        correlation_id = getattr(record, "correlation_id", None) or correlation_id_context.get()
        if correlation_id:
            payload["correlation_id"] = correlation_id
        for key in ("event", "result", "resource_id", "attempt", "duration_ms"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    if any(getattr(handler, "_market_json", False) for handler in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler._market_json = True  # type: ignore[attr-defined]
    root.handlers.clear()
    root.addHandler(handler)


def new_correlation_id(value: str | None) -> str:
    if value and 1 <= len(value) <= 128 and all(char.isalnum() or char in "-_." for char in value):
        return value
    return str(uuid4())


def observe_http(method: str, route: str, status_code: int, started_at: float) -> float:
    duration = time.perf_counter() - started_at
    HTTP_REQUESTS.labels(method, route, str(status_code)).inc()
    HTTP_DURATION.labels(method, route).observe(duration)
    return duration


def record_business_event(event: str, result: str) -> None:
    BUSINESS_EVENTS.labels(event, result).inc()


def metrics_payload() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
