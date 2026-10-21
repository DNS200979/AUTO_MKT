from __future__ import annotations

import argparse
import logging
import random
import time
from collections.abc import Callable
from datetime import timedelta
from uuid import uuid4

from .config import Settings, get_settings
from .delivery import (
    DeliveryError,
    DeliveryResult,
    NotificationProvider,
    PermanentDeliveryError,
    TransientDeliveryError,
)
from .domain import Notification, NotificationStatus, now_utc
from .observability import WORKER_DELIVERIES, configure_logging, correlation_id_context
from .repository import NotFoundError, Repository, SqlRepository
from .resilience import CircuitBreaker, CircuitOpenError

logger = logging.getLogger("market_api.notification_worker")


class ConsoleProvider:
    """Adaptador local; substituivel por WhatsApp, SMS ou e-mail em producao."""

    def send(self, notification: Notification, destination: str) -> DeliveryResult:
        logger.info(
            "console_notification_sent",
            extra={
                "event": "console_notification_sent",
                "resource_id": notification.notification_id,
                "result": notification.channel,
            },
        )
        return DeliveryResult(provider_reference=f"console-{uuid4().hex[:16]}")


class NotificationWorker:
    def __init__(
        self,
        repository: Repository,
        provider: NotificationProvider,
        *,
        batch_size: int = 25,
        max_attempts: int = 5,
        retry_base_seconds: float = 30,
        retry_max_seconds: float = 3600,
        retry_jitter_ratio: float = 0.20,
        jitter_source: Callable[[], float] = random.random,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        self.repository = repository
        self.provider = provider
        self.batch_size = batch_size
        self.max_attempts = max_attempts
        self.retry_base_seconds = retry_base_seconds
        self.retry_max_seconds = retry_max_seconds
        self.retry_jitter_ratio = retry_jitter_ratio
        self.jitter_source = jitter_source
        self.circuit_breaker = circuit_breaker or CircuitBreaker()

    def run_once(self) -> int:
        notifications = self.repository.claim_notifications(self.batch_size)
        for notification in notifications:
            self._deliver(notification)
        return len(notifications)

    def _deliver(self, notification: Notification) -> None:
        context_token = correlation_id_context.set(notification.notification_id)
        try:
            self._deliver_with_context(notification)
        finally:
            correlation_id_context.reset(context_token)

    def _deliver_with_context(self, notification: Notification) -> None:
        notification.attempts += 1
        try:
            customer = self.repository.get_customer(notification.customer_id)
            destination = (
                customer.phone if notification.channel in {"WHATSAPP", "SMS"} else customer.email
            )
            if not destination:
                raise ValueError(f"customer has no destination for {notification.channel}")
            result = self.circuit_breaker.call(
                lambda: self.provider.send(notification, destination),
                counts_as_failure=lambda exc: isinstance(exc, TransientDeliveryError),
            )
        except (PermanentDeliveryError, NotFoundError, ValueError) as exc:
            self._record_failure(notification, exc, permanent=True)
            return
        except (DeliveryError, CircuitOpenError) as exc:
            self._record_failure(notification, exc, permanent=False)
            return
        notification.status = NotificationStatus.SENT
        notification.sent_at = now_utc()
        notification.provider_reference = result.provider_reference
        notification.last_error = None
        self.repository.save_notification(notification)
        self.repository.audit(
            "NotificationSent",
            notification.customer_id,
            notification.notification_id,
            channel=notification.channel,
            provider_reference=result.provider_reference,
        )
        WORKER_DELIVERIES.labels(notification.channel, "sent").inc()
        logger.info(
            "notification_delivered",
            extra={
                "event": "NotificationSent",
                "result": "sent",
                "resource_id": notification.notification_id,
                "attempt": notification.attempts,
            },
        )

    def _record_failure(
        self, notification: Notification, exc: Exception, *, permanent: bool
    ) -> None:
        notification.last_error = str(exc)[:500]
        exhausted = notification.attempts >= self.max_attempts
        if permanent or exhausted:
            notification.status = NotificationStatus.FAILED
            event_type = "NotificationDeadLettered"
            result = "dead_letter"
        else:
            notification.status = NotificationStatus.QUEUED
            base_delay = min(
                self.retry_max_seconds,
                self.retry_base_seconds * 2 ** (notification.attempts - 1),
            )
            jitter = base_delay * self.retry_jitter_ratio * self.jitter_source()
            delay_seconds = min(self.retry_max_seconds, base_delay + jitter)
            notification.next_attempt_at = now_utc() + timedelta(seconds=delay_seconds)
            event_type = "NotificationRetryScheduled"
            result = "retry"
        self.repository.save_notification(notification)
        self.repository.audit(
            event_type,
            notification.customer_id,
            notification.notification_id,
            attempt=notification.attempts,
            error=notification.last_error,
            permanent=permanent,
        )
        WORKER_DELIVERIES.labels(notification.channel, result).inc()
        logger.warning(
            "notification_delivery_failed",
            extra={
                "event": event_type,
                "result": result,
                "resource_id": notification.notification_id,
                "attempt": notification.attempts,
            },
        )


def build_worker(settings: Settings | None = None) -> NotificationWorker:
    settings = settings or get_settings()
    repository = SqlRepository.connect(
        settings.database_url,
        create_schema=settings.auto_create_schema,
        encryption_keys=settings.data_encryption_keys,
    )
    provider: NotificationProvider
    if settings.notification_provider.lower() == "whatsapp":
        from .whatsapp import WhatsAppProvider

        required = {
            "MARKET_WHATSAPP_PHONE_NUMBER_ID": settings.whatsapp_phone_number_id,
            "MARKET_WHATSAPP_ACCESS_TOKEN": settings.whatsapp_access_token,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(f"missing WhatsApp settings: {', '.join(missing)}")
        provider = WhatsAppProvider(
            graph_version=settings.whatsapp_graph_version,
            phone_number_id=settings.whatsapp_phone_number_id,
            access_token=settings.whatsapp_access_token,
            template_name=settings.whatsapp_template_name,
            template_language=settings.whatsapp_template_language,
            timeout_seconds=settings.whatsapp_timeout_seconds,
        )
    else:
        provider = ConsoleProvider()
    return NotificationWorker(
        repository,
        provider,
        batch_size=settings.notification_batch_size,
        max_attempts=settings.notification_max_attempts,
        retry_base_seconds=settings.notification_retry_base_seconds,
        retry_max_seconds=settings.notification_retry_max_seconds,
        retry_jitter_ratio=settings.notification_retry_jitter_ratio,
        circuit_breaker=CircuitBreaker(
            failure_threshold=settings.integration_circuit_failure_threshold,
            recovery_seconds=settings.integration_circuit_recovery_seconds,
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Worker de notificacoes transacionais")
    parser.add_argument("--once", action="store_true", help="Processa um lote e encerra")
    args = parser.parse_args()
    settings = get_settings()
    configure_logging(settings.log_level)
    worker = build_worker(settings)
    while True:
        processed = worker.run_once()
        if args.once:
            return
        if processed == 0:
            time.sleep(min(settings.notification_poll_seconds, 60))


if __name__ == "__main__":
    main()
