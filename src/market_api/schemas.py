from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from .domain import CustomerStatus, NotificationStatus, PaymentStatus, PurchaseStatus


class CustomerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    phone: str = Field(pattern=r"^\+[1-9]\d{7,14}$")
    email: EmailStr | None = None


class ConsentCreate(BaseModel):
    kind: str = Field(pattern=r"^(TERMS|PRIVACY|BIOMETRICS)$")
    version: str = Field(min_length=1, max_length=30)


class BiometricEnrollment(BaseModel):
    biometric_ref: str = Field(min_length=5, max_length=200)
    liveness_passed: bool


class SimulatedBiometricEnrollment(BaseModel):
    sample_reference: str = Field(min_length=3, max_length=200)


class SimulatedBiometricVerification(BaseModel):
    sample_reference: str = Field(min_length=3, max_length=200)


class SimulatedAccessRequest(BaseModel):
    customer_id: str
    store_id: str = Field(min_length=1, max_length=80)
    door_id: str = Field(min_length=1, max_length=80)
    device_id: str = Field(min_length=1, max_length=80)
    sample_reference: str = Field(min_length=3, max_length=200)


class PaymentPolicyUpdate(BaseModel):
    payment_policy_ok: bool


class CustomerView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    customer_id: str
    name: str
    phone: str
    email: EmailStr | None
    status: CustomerStatus
    biometric_valid: bool
    payment_policy_ok: bool
    phone_verified: bool
    created_at: datetime


class OtpRequested(BaseModel):
    challenge_id: str
    expires_at: datetime
    development_code: str | None = None
    delivery_reference: str | None = None


class OtpVerify(BaseModel):
    challenge_id: str
    code: str = Field(pattern=r"^\d{6}$")


class OnboardingChatRequest(BaseModel):
    session_id: str | None = Field(default=None, min_length=4, max_length=32)
    message: str = Field(default="", max_length=500)


class OnboardingChatResponse(BaseModel):
    session_id: str
    step: str
    customer_id: str | None = None
    messages: list[str]
    completed: bool = False
    next_action: str | None = None
    expires_at: datetime
    development_code: str | None = None


class AccessRequest(BaseModel):
    customer_id: str
    store_id: str = Field(min_length=1, max_length=80)
    door_id: str = Field(min_length=1, max_length=80)
    device_id: str = Field(min_length=1, max_length=80)
    recognition_confidence: float = Field(ge=0, le=1)
    liveness_passed: bool


class AccessResponse(BaseModel):
    access_id: str
    session_id: str | None
    authorized: bool
    reason: str
    decided_at: datetime


class SimulatedAccessResponse(AccessResponse):
    door_opened: bool
    door_reference: str | None = None


class PurchaseItemCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=240)
    quantity: int = Field(gt=0, le=1000)
    unit_price_cents: int = Field(ge=0)


class PurchaseCreate(BaseModel):
    customer_id: str
    store_id: str = Field(min_length=1, max_length=80)
    session_id: str = Field(min_length=1, max_length=80)
    items: list[PurchaseItemCreate] = Field(min_length=1, max_length=500)
    discounts_cents: int = Field(default=0, ge=0)


class PurchaseItemView(PurchaseItemCreate):
    total_cents: int


class PurchaseView(BaseModel):
    purchase_id: str
    customer_id: str
    store_id: str
    session_id: str
    status: PurchaseStatus
    items: list[PurchaseItemView]
    subtotal_cents: int
    discounts_cents: int
    total_cents: int
    created_at: datetime


class PaymentCreate(BaseModel):
    purchase_id: str
    method_token: str = Field(min_length=5, max_length=240)


class PaymentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    payment_id: str
    purchase_id: str
    customer_id: str
    amount_cents: int
    status: PaymentStatus
    attempts: int
    provider_reference: str | None
    decline_reason: str | None
    created_at: datetime
    updated_at: datetime


class PaymentWebhook(BaseModel):
    event_id: str = Field(min_length=1, max_length=120)
    payment_id: str
    status: PaymentStatus
    provider_reference: str = Field(min_length=1, max_length=160)
    reason: str | None = Field(default=None, max_length=240)


class DebtRegularize(BaseModel):
    method_token: str = Field(min_length=5, max_length=240)


class DebtView(BaseModel):
    payment_id: str
    purchase_id: str
    amount_cents: int
    status: PaymentStatus
    decline_reason: str | None
    updated_at: datetime


class NotificationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    notification_id: str
    customer_id: str
    event_type: str
    channel: str
    template: str
    data: dict[str, object]
    status: NotificationStatus
    attempts: int
    created_at: datetime
    next_attempt_at: datetime
    sent_at: datetime | None
    provider_reference: str | None
    last_error: str | None


class OperatorOverview(BaseModel):
    customers_by_status: dict[str, int]
    payments_by_status: dict[str, int]
    open_debts: dict[str, int]
    failed_notifications: int
    recent_events: list[dict[str, object]]
    generated_at: datetime


class OperatorPaymentItem(BaseModel):
    payment_id: str
    purchase_id: str
    amount_cents: int
    status: PaymentStatus
    attempts: int
    created_at: datetime
    updated_at: datetime


class OperatorPaymentsPage(BaseModel):
    items: list[OperatorPaymentItem]
    total: int
    limit: int
    offset: int
    generated_at: datetime


class OperatorDebtItem(BaseModel):
    payment_id: str
    purchase_id: str
    amount_cents: int
    status: PaymentStatus
    attempts: int
    created_at: datetime
    updated_at: datetime


class OperatorDebtsPage(BaseModel):
    items: list[OperatorDebtItem]
    total: int
    total_amount_cents: int
    limit: int
    offset: int
    generated_at: datetime
