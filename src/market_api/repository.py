from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    desc,
    func,
    insert,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.engine import Engine

from .domain import (
    Consent,
    Customer,
    CustomerStatus,
    Notification,
    NotificationStatus,
    OnboardingChatSession,
    OtpChallenge,
    Payment,
    PaymentStatus,
    Purchase,
    PurchaseItem,
    PurchaseStatus,
    new_id,
    now_utc,
)
from .sensitive import DataCipher


class NotFoundError(LookupError):
    pass


class ConflictError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_type: str
    customer_id: str
    resource_id: str
    data: dict[str, object]
    event_id: str = field(default_factory=lambda: new_id("EVT"))
    occurred_at: datetime = field(default_factory=now_utc)


class Repository(Protocol):
    def add_customer(self, customer: Customer) -> Customer: ...
    def get_customer(self, customer_id: str) -> Customer: ...
    def save_customer(self, customer: Customer) -> None: ...
    def add_otp(self, challenge: OtpChallenge) -> None: ...
    def get_otp(self, challenge_id: str) -> OtpChallenge: ...
    def save_otp(self, challenge: OtpChallenge) -> None: ...
    def add_chat_session(self, session: OnboardingChatSession) -> OnboardingChatSession: ...
    def get_chat_session(self, session_id: str) -> OnboardingChatSession: ...
    def save_chat_session(self, session: OnboardingChatSession) -> None: ...
    def add_purchase(self, purchase: Purchase, idempotency_key: str) -> Purchase: ...
    def get_purchase(self, purchase_id: str) -> Purchase: ...
    def get_purchase_by_idempotency(self, idempotency_key: str) -> Purchase | None: ...
    def add_payment(self, payment: Payment, idempotency_key: str) -> Payment: ...
    def get_payment(self, payment_id: str) -> Payment: ...
    def get_payment_by_idempotency(self, idempotency_key: str) -> Payment | None: ...
    def save_payment(self, payment: Payment) -> None: ...
    def claim_webhook(self, event_id: str) -> bool: ...
    def add_notification(self, notification: Notification) -> Notification: ...
    def list_notifications(self, customer_id: str) -> list[Notification]: ...
    def list_open_debts(self, customer_id: str) -> list[Payment]: ...
    def claim_notifications(self, limit: int) -> list[Notification]: ...
    def save_notification(self, notification: Notification) -> None: ...
    def get_notification_by_provider_reference(self, reference: str) -> Notification: ...
    def list_failed_notifications(self, limit: int) -> list[Notification]: ...
    def requeue_notification(self, notification_id: str) -> Notification: ...
    def rotate_sensitive_data(self) -> dict[str, int]: ...

    def sensitive_data_inventory(self) -> dict[str, int]: ...
    def operator_overview(self, limit: int = 10) -> dict[str, object]: ...
    def anonymize_customer(self, customer_id: str) -> None: ...
    def purge_operational_data(self, before: datetime) -> dict[str, int]: ...
    def audit(
        self, event_type: str, customer_id: str, resource_id: str, **data: object
    ) -> AuditEvent: ...


class InMemoryRepository:
    def __init__(self) -> None:
        self.customers: dict[str, Customer] = {}
        self.audit_events: list[AuditEvent] = []
        self.otp_challenges: dict[str, OtpChallenge] = {}
        self.chat_sessions: dict[str, OnboardingChatSession] = {}

    def add_customer(self, customer: Customer) -> Customer:
        if any(item.phone == customer.phone for item in self.customers.values()):
            raise ConflictError("phone already registered")
        self.customers[customer.customer_id] = customer
        return customer

    def get_customer(self, customer_id: str) -> Customer:
        try:
            return self.customers[customer_id]
        except KeyError as exc:
            raise NotFoundError("customer not found") from exc

    def save_customer(self, customer: Customer) -> None:
        self.customers[customer.customer_id] = customer

    def add_otp(self, challenge: OtpChallenge) -> None:
        self.otp_challenges = {
            challenge_id: item
            for challenge_id, item in self.otp_challenges.items()
            if item.customer_id != challenge.customer_id
        }
        self.otp_challenges[challenge.challenge_id] = challenge

    def get_otp(self, challenge_id: str) -> OtpChallenge:
        try:
            return self.otp_challenges[challenge_id]
        except KeyError as exc:
            raise NotFoundError("OTP challenge not found") from exc

    def save_otp(self, challenge: OtpChallenge) -> None:
        self.otp_challenges[challenge.challenge_id] = challenge

    def add_chat_session(self, session: OnboardingChatSession) -> OnboardingChatSession:
        self.chat_sessions[session.session_id] = session
        return session

    def get_chat_session(self, session_id: str) -> OnboardingChatSession:
        try:
            return self.chat_sessions[session_id]
        except KeyError as exc:
            raise NotFoundError("onboarding chat session not found") from exc

    def save_chat_session(self, session: OnboardingChatSession) -> None:
        self.chat_sessions[session.session_id] = session

    def audit(
        self,
        event_type: str,
        customer_id: str,
        resource_id: str,
        **data: object,
    ) -> AuditEvent:
        event = AuditEvent(event_type, customer_id, resource_id, data)
        self.audit_events.append(event)
        return event


metadata = MetaData()
customers_table = Table(
    "customers",
    metadata,
    Column("customer_id", String(32), primary_key=True),
    Column("name", String(160), nullable=False),
    Column("phone", String(20), nullable=False, unique=True),
    Column("email", String(254)),
    Column("status", String(20), nullable=False),
    Column("biometric_ref", Text),
    Column("biometric_valid", Boolean, nullable=False),
    Column("payment_policy_ok", Boolean, nullable=False),
    Column("risk_blocked", Boolean, nullable=False),
    Column("phone_verified", Boolean, nullable=False),
    Column("consents", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
otp_table = Table(
    "otp_challenges",
    metadata,
    Column("challenge_id", String(32), primary_key=True),
    Column("customer_id", String(32), nullable=False, index=True),
    Column("code_hash", String(64), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("consumed_at", DateTime(timezone=True)),
)
chat_sessions_table = Table(
    "onboarding_chat_sessions",
    metadata,
    Column("session_id", String(32), primary_key=True),
    Column("customer_id", String(32), index=True),
    Column("step", String(40), nullable=False),
    Column("name", String(160)),
    Column("phone", String(20)),
    Column("email", String(254)),
    Column("challenge_id", String(32)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
)
audit_table = Table(
    "audit_events",
    metadata,
    Column("event_id", String(32), primary_key=True),
    Column("event_type", String(80), nullable=False, index=True),
    Column("customer_id", String(32), nullable=False, index=True),
    Column("resource_id", String(64), nullable=False),
    Column("data", JSON, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
)
purchases_table = Table(
    "purchases",
    metadata,
    Column("purchase_id", String(32), primary_key=True),
    Column("customer_id", String(32), nullable=False, index=True),
    Column("store_id", String(80), nullable=False),
    Column("session_id", String(80), nullable=False, index=True),
    Column("status", String(20), nullable=False),
    Column("items", JSON, nullable=False),
    Column("discounts_cents", Integer, nullable=False),
    Column("subtotal_cents", Integer, nullable=False),
    Column("total_cents", Integer, nullable=False),
    Column("idempotency_key", String(120), nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
payments_table = Table(
    "payments",
    metadata,
    Column("payment_id", String(32), primary_key=True),
    Column("purchase_id", String(32), nullable=False, unique=True),
    Column("customer_id", String(32), nullable=False, index=True),
    Column("amount_cents", Integer, nullable=False),
    Column("method_token", Text, nullable=False),
    Column("status", String(20), nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("provider_reference", String(160)),
    Column("decline_reason", String(240)),
    Column("idempotency_key", String(120), nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
webhook_events_table = Table(
    "webhook_events",
    metadata,
    Column("event_id", String(120), primary_key=True),
    Column("received_at", DateTime(timezone=True), nullable=False),
)
notifications_table = Table(
    "notifications",
    metadata,
    Column("notification_id", String(32), primary_key=True),
    Column("customer_id", String(32), nullable=False, index=True),
    Column("event_type", String(80), nullable=False),
    Column("channel", String(30), nullable=False),
    Column("template", String(100), nullable=False),
    Column("data", JSON, nullable=False),
    Column("deduplication_key", String(160), nullable=False, unique=True),
    Column("status", String(20), nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("next_attempt_at", DateTime(timezone=True), nullable=False),
    Column("sent_at", DateTime(timezone=True)),
    Column("provider_reference", String(160)),
    Column("last_error", String(500)),
)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class SqlRepository:
    def __init__(self, engine: Engine, cipher: DataCipher | None = None) -> None:
        self.engine = engine
        self.cipher = cipher or DataCipher()

    @classmethod
    def connect(
        cls,
        database_url: str,
        *,
        create_schema: bool = True,
        encryption_keys: dict[str, str] | None = None,
    ) -> SqlRepository:
        engine = create_engine(database_url, pool_pre_ping=True)
        if create_schema:
            metadata.create_all(engine)
        return cls(engine, DataCipher(encryption_keys))

    def ping(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def _customer_values(self, customer: Customer) -> dict[str, object]:
        return {
            "customer_id": customer.customer_id,
            "name": customer.name,
            "phone": customer.phone,
            "email": customer.email,
            "status": customer.status.value,
            "biometric_ref": self.cipher.encrypt(customer.biometric_ref),
            "biometric_valid": customer.biometric_valid,
            "payment_policy_ok": customer.payment_policy_ok,
            "risk_blocked": customer.risk_blocked,
            "phone_verified": customer.phone_verified,
            "consents": [
                {"kind": c.kind, "version": c.version, "accepted_at": c.accepted_at.isoformat()}
                for c in customer.consents
            ],
            "created_at": customer.created_at,
        }

    def add_customer(self, customer: Customer) -> Customer:
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    insert(customers_table).values(**self._customer_values(customer))
                )
        except Exception as exc:
            if "unique" in str(exc).lower():
                raise ConflictError("phone already registered") from exc
            raise
        return customer

    def get_customer(self, customer_id: str) -> Customer:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(customers_table).where(customers_table.c.customer_id == customer_id)
                )
                .mappings()
                .first()
            )
        if not row:
            raise NotFoundError("customer not found")
        return Customer(
            name=row["name"],
            phone=row["phone"],
            email=row["email"],
            customer_id=row["customer_id"],
            status=CustomerStatus(row["status"]),
            biometric_ref=self.cipher.decrypt(row["biometric_ref"]),
            biometric_valid=row["biometric_valid"],
            payment_policy_ok=row["payment_policy_ok"],
            risk_blocked=row["risk_blocked"],
            phone_verified=row["phone_verified"],
            consents=[
                Consent(c["kind"], c["version"], datetime.fromisoformat(c["accepted_at"]))
                for c in row["consents"]
            ],
            created_at=_aware(row["created_at"]),
        )

    def save_customer(self, customer: Customer) -> None:
        values = self._customer_values(customer)
        values.pop("customer_id")
        with self.engine.begin() as connection:
            connection.execute(
                update(customers_table)
                .where(customers_table.c.customer_id == customer.customer_id)
                .values(**values)
            )

    def add_otp(self, challenge: OtpChallenge) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                delete(otp_table).where(otp_table.c.customer_id == challenge.customer_id)
            )
            connection.execute(
                insert(otp_table).values(
                    challenge_id=challenge.challenge_id,
                    customer_id=challenge.customer_id,
                    code_hash=challenge.code_hash,
                    expires_at=challenge.expires_at,
                    attempts=challenge.attempts,
                    consumed_at=challenge.consumed_at,
                )
            )

    def get_otp(self, challenge_id: str) -> OtpChallenge:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(otp_table).where(otp_table.c.challenge_id == challenge_id)
                )
                .mappings()
                .first()
            )
        if not row:
            raise NotFoundError("OTP challenge not found")
        return OtpChallenge(
            customer_id=row["customer_id"],
            code_hash=row["code_hash"],
            expires_at=_aware(row["expires_at"]),
            challenge_id=row["challenge_id"],
            attempts=row["attempts"],
            consumed_at=_aware(row["consumed_at"]) if row["consumed_at"] else None,
        )

    def save_otp(self, challenge: OtpChallenge) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                update(otp_table)
                .where(otp_table.c.challenge_id == challenge.challenge_id)
                .values(attempts=challenge.attempts, consumed_at=challenge.consumed_at)
            )

    @staticmethod
    def _chat_session_from_row(row: object) -> OnboardingChatSession:
        return OnboardingChatSession(
            session_id=row["session_id"],
            customer_id=row["customer_id"],
            step=row["step"],
            name=row["name"],
            phone=row["phone"],
            email=row["email"],
            challenge_id=row["challenge_id"],
            created_at=_aware(row["created_at"]),
            updated_at=_aware(row["updated_at"]),
            expires_at=_aware(row["expires_at"]),
        )

    def add_chat_session(self, session: OnboardingChatSession) -> OnboardingChatSession:
        with self.engine.begin() as connection:
            connection.execute(
                insert(chat_sessions_table).values(
                    session_id=session.session_id,
                    customer_id=session.customer_id,
                    step=session.step,
                    name=session.name,
                    phone=session.phone,
                    email=session.email,
                    challenge_id=session.challenge_id,
                    created_at=session.created_at,
                    updated_at=session.updated_at,
                    expires_at=session.expires_at,
                )
            )
        return session

    def get_chat_session(self, session_id: str) -> OnboardingChatSession:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(chat_sessions_table).where(
                        chat_sessions_table.c.session_id == session_id
                    )
                )
                .mappings()
                .first()
            )
        if not row:
            raise NotFoundError("onboarding chat session not found")
        return self._chat_session_from_row(row)

    def save_chat_session(self, session: OnboardingChatSession) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                update(chat_sessions_table)
                .where(chat_sessions_table.c.session_id == session.session_id)
                .values(
                    customer_id=session.customer_id,
                    step=session.step,
                    name=session.name,
                    phone=session.phone,
                    email=session.email,
                    challenge_id=session.challenge_id,
                    updated_at=session.updated_at,
                    expires_at=session.expires_at,
                )
            )

    @staticmethod
    def _purchase_from_row(row: object) -> Purchase:
        return Purchase(
            customer_id=row["customer_id"],
            store_id=row["store_id"],
            session_id=row["session_id"],
            items=[PurchaseItem(**item) for item in row["items"]],
            discounts_cents=row["discounts_cents"],
            purchase_id=row["purchase_id"],
            status=PurchaseStatus(row["status"]),
            created_at=_aware(row["created_at"]),
        )

    def add_purchase(self, purchase: Purchase, idempotency_key: str) -> Purchase:
        items = [
            {
                "sku": item.sku,
                "description": item.description,
                "quantity": item.quantity,
                "unit_price_cents": item.unit_price_cents,
            }
            for item in purchase.items
        ]
        with self.engine.begin() as connection:
            connection.execute(
                insert(purchases_table).values(
                    purchase_id=purchase.purchase_id,
                    customer_id=purchase.customer_id,
                    store_id=purchase.store_id,
                    session_id=purchase.session_id,
                    status=purchase.status.value,
                    items=items,
                    discounts_cents=purchase.discounts_cents,
                    subtotal_cents=purchase.subtotal_cents,
                    total_cents=purchase.total_cents,
                    idempotency_key=idempotency_key,
                    created_at=purchase.created_at,
                )
            )
        return purchase

    def get_purchase(self, purchase_id: str) -> Purchase:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(purchases_table).where(purchases_table.c.purchase_id == purchase_id)
                )
                .mappings()
                .first()
            )
        if not row:
            raise NotFoundError("purchase not found")
        return self._purchase_from_row(row)

    def get_purchase_by_idempotency(self, idempotency_key: str) -> Purchase | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(purchases_table).where(
                        purchases_table.c.idempotency_key == idempotency_key
                    )
                )
                .mappings()
                .first()
            )
        return self._purchase_from_row(row) if row else None

    def _payment_from_row(self, row: object) -> Payment:
        return Payment(
            purchase_id=row["purchase_id"],
            customer_id=row["customer_id"],
            amount_cents=row["amount_cents"],
            method_token=self.cipher.decrypt(row["method_token"]),
            payment_id=row["payment_id"],
            status=PaymentStatus(row["status"]),
            attempts=row["attempts"],
            provider_reference=row["provider_reference"],
            decline_reason=row["decline_reason"],
            created_at=_aware(row["created_at"]),
            updated_at=_aware(row["updated_at"]),
        )

    def add_payment(self, payment: Payment, idempotency_key: str) -> Payment:
        with self.engine.begin() as connection:
            connection.execute(
                insert(payments_table).values(
                    payment_id=payment.payment_id,
                    purchase_id=payment.purchase_id,
                    customer_id=payment.customer_id,
                    amount_cents=payment.amount_cents,
                    method_token=self.cipher.encrypt(payment.method_token),
                    status=payment.status.value,
                    attempts=payment.attempts,
                    provider_reference=payment.provider_reference,
                    decline_reason=payment.decline_reason,
                    idempotency_key=idempotency_key,
                    created_at=payment.created_at,
                    updated_at=payment.updated_at,
                )
            )
        return payment

    def get_payment(self, payment_id: str) -> Payment:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(payments_table).where(payments_table.c.payment_id == payment_id)
                )
                .mappings()
                .first()
            )
        if not row:
            raise NotFoundError("payment not found")
        return self._payment_from_row(row)

    def get_payment_by_idempotency(self, idempotency_key: str) -> Payment | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(payments_table).where(
                        payments_table.c.idempotency_key == idempotency_key
                    )
                )
                .mappings()
                .first()
            )
        return self._payment_from_row(row) if row else None

    def save_payment(self, payment: Payment) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                update(payments_table)
                .where(payments_table.c.payment_id == payment.payment_id)
                .values(
                    status=payment.status.value,
                    attempts=payment.attempts,
                    provider_reference=payment.provider_reference,
                    decline_reason=payment.decline_reason,
                    method_token=self.cipher.encrypt(payment.method_token),
                    updated_at=payment.updated_at,
                )
            )

    def claim_webhook(self, event_id: str) -> bool:
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    insert(webhook_events_table).values(event_id=event_id, received_at=now_utc())
                )
            return True
        except Exception as exc:
            if "unique" in str(exc).lower():
                return False
            raise

    @staticmethod
    def _notification_from_row(row: object) -> Notification:
        return Notification(
            customer_id=row["customer_id"],
            event_type=row["event_type"],
            channel=row["channel"],
            template=row["template"],
            data=row["data"],
            deduplication_key=row["deduplication_key"],
            notification_id=row["notification_id"],
            status=NotificationStatus(row["status"]),
            attempts=row["attempts"],
            created_at=_aware(row["created_at"]),
            next_attempt_at=_aware(row["next_attempt_at"]),
            sent_at=_aware(row["sent_at"]) if row["sent_at"] else None,
            provider_reference=row["provider_reference"],
            last_error=row["last_error"],
        )

    def add_notification(self, notification: Notification) -> Notification:
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    insert(notifications_table).values(
                        notification_id=notification.notification_id,
                        customer_id=notification.customer_id,
                        event_type=notification.event_type,
                        channel=notification.channel,
                        template=notification.template,
                        data=notification.data,
                        deduplication_key=notification.deduplication_key,
                        status=notification.status.value,
                        attempts=notification.attempts,
                        created_at=notification.created_at,
                        next_attempt_at=notification.next_attempt_at,
                        sent_at=notification.sent_at,
                        provider_reference=notification.provider_reference,
                        last_error=notification.last_error,
                    )
                )
            return notification
        except Exception as exc:
            if "unique" not in str(exc).lower():
                raise
            with self.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(notifications_table).where(
                            notifications_table.c.deduplication_key
                            == notification.deduplication_key
                        )
                    )
                    .mappings()
                    .one()
                )
            return self._notification_from_row(row)

    def list_notifications(self, customer_id: str) -> list[Notification]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(notifications_table)
                    .where(notifications_table.c.customer_id == customer_id)
                    .order_by(notifications_table.c.created_at.desc())
                )
                .mappings()
                .all()
            )
        return [self._notification_from_row(row) for row in rows]

    def claim_notifications(self, limit: int) -> list[Notification]:
        now = now_utc()
        with self.engine.begin() as connection:
            statement = (
                select(notifications_table)
                .where(
                    or_(
                        (
                            (notifications_table.c.status == NotificationStatus.QUEUED.value)
                            & (notifications_table.c.next_attempt_at <= now)
                        ),
                        (
                            (notifications_table.c.status == NotificationStatus.PROCESSING.value)
                            & (notifications_table.c.next_attempt_at <= now)
                        ),
                    )
                )
                .order_by(notifications_table.c.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            rows = connection.execute(statement).mappings().all()
            ids = [row["notification_id"] for row in rows]
            if ids:
                connection.execute(
                    update(notifications_table)
                    .where(notifications_table.c.notification_id.in_(ids))
                    .values(
                        status=NotificationStatus.PROCESSING.value,
                        next_attempt_at=now + timedelta(minutes=5),
                    )
                )
        notifications = [self._notification_from_row(row) for row in rows]
        for notification in notifications:
            notification.status = NotificationStatus.PROCESSING
        return notifications

    def save_notification(self, notification: Notification) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                update(notifications_table)
                .where(notifications_table.c.notification_id == notification.notification_id)
                .values(
                    status=notification.status.value,
                    attempts=notification.attempts,
                    next_attempt_at=notification.next_attempt_at,
                    sent_at=notification.sent_at,
                    provider_reference=notification.provider_reference,
                    last_error=notification.last_error,
                )
            )

    def get_notification_by_provider_reference(self, reference: str) -> Notification:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(notifications_table).where(
                        notifications_table.c.provider_reference == reference
                    )
                )
                .mappings()
                .first()
            )
        if not row:
            raise NotFoundError("notification not found")
        return self._notification_from_row(row)

    def list_failed_notifications(self, limit: int) -> list[Notification]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(notifications_table)
                    .where(notifications_table.c.status == NotificationStatus.FAILED.value)
                    .order_by(notifications_table.c.created_at)
                    .limit(limit)
                )
                .mappings()
                .all()
            )
        return [self._notification_from_row(row) for row in rows]

    def requeue_notification(self, notification_id: str) -> Notification:
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    select(notifications_table).where(
                        notifications_table.c.notification_id == notification_id
                    )
                )
                .mappings()
                .first()
            )
            if not row:
                raise NotFoundError("notification not found")
            notification = self._notification_from_row(row)
            if notification.status != NotificationStatus.FAILED:
                raise ConflictError("notification is not in dead-letter state")
            connection.execute(
                update(notifications_table)
                .where(notifications_table.c.notification_id == notification_id)
                .values(
                    status=NotificationStatus.QUEUED.value,
                    attempts=0,
                    next_attempt_at=now_utc(),
                    last_error=None,
                )
            )
        notification.status = NotificationStatus.QUEUED
        notification.attempts = 0
        notification.next_attempt_at = now_utc()
        notification.last_error = None
        return notification

    def rotate_sensitive_data(self) -> dict[str, int]:
        if not self.cipher.enabled:
            raise ConflictError("data encryption is not configured")
        rotated = {"customers": 0, "payments": 0}
        with self.engine.begin() as connection:
            customers = connection.execute(
                select(customers_table.c.customer_id, customers_table.c.biometric_ref).where(
                    customers_table.c.biometric_ref.is_not(None)
                )
            ).mappings()
            for row in customers:
                if self.cipher.needs_rotation(row["biometric_ref"]):
                    connection.execute(
                        update(customers_table)
                        .where(customers_table.c.customer_id == row["customer_id"])
                        .values(biometric_ref=self.cipher.encrypt(row["biometric_ref"]))
                    )
                    rotated["customers"] += 1
            payments = connection.execute(
                select(payments_table.c.payment_id, payments_table.c.method_token)
            ).mappings()
            for row in payments:
                if self.cipher.needs_rotation(row["method_token"]):
                    connection.execute(
                        update(payments_table)
                        .where(payments_table.c.payment_id == row["payment_id"])
                        .values(method_token=self.cipher.encrypt(row["method_token"]))
                    )
                    rotated["payments"] += 1
        return rotated

    def sensitive_data_inventory(self) -> dict[str, int]:
        inventory: dict[str, int] = {}
        with self.engine.connect() as connection:
            values = connection.execute(
                select(customers_table.c.biometric_ref).where(
                    customers_table.c.biometric_ref.is_not(None)
                )
            ).scalars()
            for value in values:
                key_id = self.cipher.key_id(value)
                inventory[key_id] = inventory.get(key_id, 0) + 1
            values = connection.execute(select(payments_table.c.method_token)).scalars()
            for value in values:
                key_id = self.cipher.key_id(value)
                inventory[key_id] = inventory.get(key_id, 0) + 1
        return dict(sorted(inventory.items()))

    def operator_overview(self, limit: int = 10) -> dict[str, object]:
        bounded_limit = max(1, min(limit, 50))
        customer_status: dict[str, int] = {}
        payment_status: dict[str, int] = {}
        with self.engine.connect() as connection:
            for row in connection.execute(
                select(customers_table.c.status, func.count().label("total")).group_by(
                    customers_table.c.status
                )
            ).mappings():
                customer_status[row["status"]] = int(row["total"])
            for row in connection.execute(
                select(payments_table.c.status, func.count().label("total")).group_by(
                    payments_table.c.status
                )
            ).mappings():
                payment_status[row["status"]] = int(row["total"])
            debt_row = connection.execute(
                select(
                    func.count().label("total"),
                    func.coalesce(func.sum(payments_table.c.amount_cents), 0).label("amount_cents"),
                ).where(
                    payments_table.c.status.in_(
                        [
                            PaymentStatus.DECLINED.value,
                            PaymentStatus.PENDING.value,
                            PaymentStatus.RETRY.value,
                            PaymentStatus.UNPAID.value,
                        ]
                    )
                )
            ).one()
            failed_notifications = connection.execute(
                select(func.count())
                .select_from(notifications_table)
                .where(notifications_table.c.status == NotificationStatus.FAILED.value)
            ).scalar_one()
            recent_rows = connection.execute(
                select(
                    audit_table.c.event_id,
                    audit_table.c.event_type,
                    audit_table.c.resource_id,
                    audit_table.c.occurred_at,
                )
                .order_by(desc(audit_table.c.occurred_at))
                .limit(bounded_limit)
            ).mappings().all()
        return {
            "customers_by_status": dict(sorted(customer_status.items())),
            "payments_by_status": dict(sorted(payment_status.items())),
            "open_debts": {
                "count": int(debt_row.total),
                "amount_cents": int(debt_row.amount_cents),
            },
            "failed_notifications": int(failed_notifications),
            "recent_events": [dict(row) for row in recent_rows],
            "generated_at": now_utc(),
        }

    def anonymize_customer(self, customer_id: str) -> None:
        self.get_customer(customer_id)
        if self.list_open_debts(customer_id):
            raise ConflictError("customer with unsettled payments cannot be anonymized")
        phone_suffix = (
            int.from_bytes(hashlib.sha256(customer_id.encode()).digest()[:6], "big") % 10**12
        )
        anonymous_phone = f"+999{phone_suffix:012d}"
        with self.engine.begin() as connection:
            connection.execute(
                update(customers_table)
                .where(customers_table.c.customer_id == customer_id)
                .values(
                    name="ANONYMIZED",
                    phone=anonymous_phone,
                    email=None,
                    status=CustomerStatus.BLOCKED.value,
                    biometric_ref=None,
                    biometric_valid=False,
                    payment_policy_ok=False,
                    risk_blocked=True,
                )
            )
            connection.execute(delete(otp_table).where(otp_table.c.customer_id == customer_id))
            connection.execute(
                update(payments_table)
                .where(payments_table.c.customer_id == customer_id)
                .values(method_token=self.cipher.encrypt("REDACTED"))
            )
            connection.execute(
                update(notifications_table)
                .where(notifications_table.c.customer_id == customer_id)
                .values(data={}, last_error=None)
            )

    def purge_operational_data(self, before: datetime) -> dict[str, int]:
        with self.engine.begin() as connection:
            otp_result = connection.execute(
                delete(otp_table).where(otp_table.c.expires_at < before)
            )
            webhook_result = connection.execute(
                delete(webhook_events_table).where(webhook_events_table.c.received_at < before)
            )
        return {
            "otp_challenges": otp_result.rowcount or 0,
            "webhook_events": webhook_result.rowcount or 0,
        }

    def list_open_debts(self, customer_id: str) -> list[Payment]:
        open_statuses = [
            PaymentStatus.CREATED.value,
            PaymentStatus.PROCESSING.value,
            PaymentStatus.DECLINED.value,
            PaymentStatus.PENDING.value,
            PaymentStatus.RETRY.value,
            PaymentStatus.UNPAID.value,
        ]
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(payments_table).where(
                        payments_table.c.customer_id == customer_id,
                        payments_table.c.status.in_(open_statuses),
                    )
                )
                .mappings()
                .all()
            )
        return [self._payment_from_row(row) for row in rows]

    def audit(
        self, event_type: str, customer_id: str, resource_id: str, **data: object
    ) -> AuditEvent:
        event = AuditEvent(event_type, customer_id, resource_id, data)
        with self.engine.begin() as connection:
            connection.execute(
                insert(audit_table).values(
                    event_id=event.event_id,
                    event_type=event.event_type,
                    customer_id=event.customer_id,
                    resource_id=event.resource_id,
                    data=event.data,
                    occurred_at=event.occurred_at,
                )
            )
        return event
