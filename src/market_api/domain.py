from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import uuid4


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12].upper()}"


def now_utc() -> datetime:
    return datetime.now(UTC)


class CustomerStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"


class PurchaseStatus(StrEnum):
    COMPLETED = "COMPLETED"


class PaymentStatus(StrEnum):
    CREATED = "CREATED"
    PROCESSING = "PROCESSING"
    PAID = "PAID"
    DECLINED = "DECLINED"
    PENDING = "PENDING"
    RETRY = "RETRY"
    UNPAID = "UNPAID"
    REFUNDED = "REFUNDED"
    DISPUTED = "DISPUTED"


class NotificationStatus(StrEnum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    READ = "READ"
    FAILED = "FAILED"


@dataclass(slots=True)
class Consent:
    kind: str
    version: str
    accepted_at: datetime = field(default_factory=now_utc)


@dataclass(slots=True)
class Customer:
    name: str
    phone: str
    email: str | None = None
    customer_id: str = field(default_factory=lambda: new_id("CUST"))
    status: CustomerStatus = CustomerStatus.PENDING
    biometric_ref: str | None = None
    biometric_valid: bool = False
    payment_policy_ok: bool = False
    risk_blocked: bool = False
    phone_verified: bool = False
    consents: list[Consent] = field(default_factory=list)
    created_at: datetime = field(default_factory=now_utc)

    def activate_if_ready(self) -> None:
        required = {"TERMS", "PRIVACY", "BIOMETRICS"}
        accepted = {consent.kind for consent in self.consents}
        if required <= accepted and self.biometric_valid and self.phone_verified:
            self.status = CustomerStatus.ACTIVE


@dataclass(slots=True)
class OtpChallenge:
    customer_id: str
    code_hash: str
    expires_at: datetime
    challenge_id: str = field(default_factory=lambda: new_id("OTP"))
    attempts: int = 0
    consumed_at: datetime | None = None

    @classmethod
    def issue(cls, customer_id: str, ttl_minutes: int = 5) -> tuple[OtpChallenge, str]:
        code = f"{secrets.randbelow(1_000_000):06d}"
        return cls(
            customer_id=customer_id,
            code_hash=hashlib.sha256(code.encode()).hexdigest(),
            expires_at=now_utc() + timedelta(minutes=ttl_minutes),
        ), code

    def verify(self, code: str, max_attempts: int = 5) -> bool:
        if self.consumed_at or self.expires_at <= now_utc() or self.attempts >= max_attempts:
            return False

        self.attempts += 1
        candidate = hashlib.sha256(code.encode()).hexdigest()
        if not hmac.compare_digest(self.code_hash, candidate):
            return False
        self.consumed_at = now_utc()
        return True


@dataclass(slots=True)
class OnboardingChatSession:
    """Estado mínimo e recuperável de uma conversa de onboarding."""

    step: str = "NAME"
    customer_id: str | None = None
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    challenge_id: str | None = None
    session_id: str = field(default_factory=lambda: new_id("CHAT"))
    created_at: datetime = field(default_factory=now_utc)
    updated_at: datetime = field(default_factory=now_utc)
    expires_at: datetime = field(default_factory=lambda: now_utc() + timedelta(minutes=30))

    def touch(self) -> None:
        self.updated_at = now_utc()


@dataclass(frozen=True, slots=True)
class PurchaseItem:
    sku: str
    description: str
    quantity: int
    unit_price_cents: int

    @property
    def total_cents(self) -> int:
        return self.quantity * self.unit_price_cents


@dataclass(slots=True)
class Purchase:
    customer_id: str
    store_id: str
    session_id: str
    items: list[PurchaseItem]
    discounts_cents: int = 0
    purchase_id: str = field(default_factory=lambda: new_id("PUR"))
    status: PurchaseStatus = PurchaseStatus.COMPLETED
    created_at: datetime = field(default_factory=now_utc)

    @property
    def subtotal_cents(self) -> int:
        return sum(item.total_cents for item in self.items)

    @property
    def total_cents(self) -> int:
        return self.subtotal_cents - self.discounts_cents


@dataclass(slots=True)
class Payment:
    purchase_id: str
    customer_id: str
    amount_cents: int
    method_token: str
    payment_id: str = field(default_factory=lambda: new_id("PAY"))
    status: PaymentStatus = PaymentStatus.CREATED
    attempts: int = 0
    provider_reference: str | None = None
    decline_reason: str | None = None
    created_at: datetime = field(default_factory=now_utc)
    updated_at: datetime = field(default_factory=now_utc)

    def request(self, retry: bool = False) -> None:
        if self.status in {PaymentStatus.PAID, PaymentStatus.REFUNDED, PaymentStatus.DISPUTED}:
            raise ValueError(f"payment in terminal state: {self.status}")
        self.attempts += 1
        self.status = PaymentStatus.RETRY if retry else PaymentStatus.PROCESSING
        self.updated_at = now_utc()

    def apply_provider_result(
        self, result: PaymentStatus, provider_reference: str, reason: str | None = None
    ) -> None:
        allowed = {PaymentStatus.PAID, PaymentStatus.DECLINED, PaymentStatus.PENDING}
        if result not in allowed:
            raise ValueError("invalid provider result")
        if self.status == PaymentStatus.PAID and result != PaymentStatus.PAID:
            raise ValueError("paid payment cannot regress")
        self.status = result
        self.provider_reference = provider_reference
        self.decline_reason = reason if result == PaymentStatus.DECLINED else None
        self.updated_at = now_utc()


@dataclass(slots=True)
class Notification:
    customer_id: str
    event_type: str
    channel: str
    template: str
    data: dict[str, object]
    deduplication_key: str
    notification_id: str = field(default_factory=lambda: new_id("NTF"))
    status: NotificationStatus = NotificationStatus.QUEUED
    attempts: int = 0
    created_at: datetime = field(default_factory=now_utc)
    next_attempt_at: datetime = field(default_factory=now_utc)
    sent_at: datetime | None = None
    provider_reference: str | None = None
    last_error: str | None = None


@dataclass(frozen=True, slots=True)
class AccessDecision:
    authorized: bool
    reason: str


def decide_access(customer: Customer) -> AccessDecision:
    if customer.status == CustomerStatus.BLOCKED:
        return AccessDecision(False, "CUSTOMER_BLOCKED")
    if customer.status != CustomerStatus.ACTIVE:
        return AccessDecision(False, "CUSTOMER_NOT_ACTIVE")
    if not customer.biometric_valid:
        return AccessDecision(False, "BIOMETRIC_INVALID")
    if customer.risk_blocked:
        return AccessDecision(False, "RISK_BLOCKED")
    if not customer.payment_policy_ok:
        return AccessDecision(False, "PAYMENT_POLICY_NOT_OK")
    return AccessDecision(True, "POLICY_OK")
