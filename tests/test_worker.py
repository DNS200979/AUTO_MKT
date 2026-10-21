from market_api.delivery import PermanentDeliveryError
from market_api.domain import Customer, Notification, NotificationStatus
from market_api.repository import SqlRepository
from market_api.worker import DeliveryError, DeliveryResult, NotificationWorker


class SuccessfulProvider:
    def send(self, notification: Notification, destination: str) -> DeliveryResult:
        assert destination == "+5511955555555"
        return DeliveryResult("provider-message-1")


class FailingProvider:
    def send(self, notification: Notification, destination: str) -> DeliveryResult:
        raise DeliveryError("provider unavailable")


class PermanentlyFailingProvider:
    def send(self, notification: Notification, destination: str) -> DeliveryResult:
        raise PermanentDeliveryError("invalid destination")


def repository_with_notification(tmp_path) -> tuple[SqlRepository, Notification]:
    repository = SqlRepository.connect(f"sqlite:///{tmp_path / 'worker.db'}")
    customer = repository.add_customer(Customer("Worker Test", "+5511955555555"))
    notification = repository.add_notification(
        Notification(
            customer_id=customer.customer_id,
            event_type="PaymentDeclined",
            channel="WHATSAPP",
            template="payment_declined_v1",
            data={"amount_cents": 1000},
            deduplication_key="worker-test-1",
        )
    )
    return repository, notification


def test_worker_marks_successful_delivery_as_sent(tmp_path) -> None:
    repository, notification = repository_with_notification(tmp_path)
    worker = NotificationWorker(repository, SuccessfulProvider())

    assert worker.run_once() == 1

    saved = repository.list_notifications(notification.customer_id)[0]
    assert saved.status == NotificationStatus.SENT
    assert saved.attempts == 1
    assert saved.sent_at is not None
    assert saved.provider_reference == "provider-message-1"


def test_worker_moves_exhausted_delivery_to_failed(tmp_path) -> None:
    repository, notification = repository_with_notification(tmp_path)
    worker = NotificationWorker(repository, FailingProvider(), max_attempts=1)

    assert worker.run_once() == 1

    saved = repository.list_notifications(notification.customer_id)[0]
    assert saved.status == NotificationStatus.FAILED
    assert saved.attempts == 1
    assert saved.last_error == "provider unavailable"


def test_worker_schedules_retry_with_backoff(tmp_path) -> None:
    repository, notification = repository_with_notification(tmp_path)
    worker = NotificationWorker(repository, FailingProvider(), max_attempts=3)

    worker.run_once()

    saved = repository.list_notifications(notification.customer_id)[0]
    assert saved.status == NotificationStatus.QUEUED
    assert saved.attempts == 1
    assert saved.next_attempt_at > saved.created_at


def test_permanent_failure_goes_directly_to_dead_letter(tmp_path) -> None:
    repository, notification = repository_with_notification(tmp_path)
    worker = NotificationWorker(repository, PermanentlyFailingProvider(), max_attempts=5)

    worker.run_once()

    saved = repository.list_notifications(notification.customer_id)[0]
    assert saved.status == NotificationStatus.FAILED
    assert saved.attempts == 1
    assert saved.last_error == "invalid destination"


def test_dead_letter_can_be_requeued_for_operator_reprocessing(tmp_path) -> None:
    repository, notification = repository_with_notification(tmp_path)
    NotificationWorker(repository, PermanentlyFailingProvider()).run_once()

    failed = repository.list_failed_notifications(10)
    requeued = repository.requeue_notification(notification.notification_id)

    assert [item.notification_id for item in failed] == [notification.notification_id]
    assert requeued.status == NotificationStatus.QUEUED
    assert requeued.attempts == 0
    assert requeued.last_error is None
