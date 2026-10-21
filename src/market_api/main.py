import hashlib
import hmac
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.middleware.cors import CORSMiddleware

from .auth import (
    ActorRole,
    AuthenticationError,
    CompositeAuthProvider,
    DevelopmentTokenProvider,
    SupabaseJwtProvider,
    bearer_token,
    route_policy,
)
from .chat import advance_onboarding_chat, is_greeting
from .config import get_settings, validate_runtime_settings
from .domain import (
    Consent,
    Customer,
    CustomerStatus,
    Notification,
    NotificationStatus,
    OtpChallenge,
    Payment,
    PaymentStatus,
    Purchase,
    PurchaseItem,
    decide_access,
    new_id,
    now_utc,
)
from .integrations import (
    IntegrationError,
    PaymentResult,
    SimulatedBiometricProvider,
    SimulatedDoorController,
    SimulatedPaymentProvider,
)
from .observability import (
    configure_logging,
    correlation_id_context,
    metrics_payload,
    new_correlation_id,
    observe_http,
    record_business_event,
)
from .onboarding import (
    DevelopmentOtpProvider,
    OnboardingTokenService,
    RateLimitExceeded,
    SlidingWindowRateLimiter,
)
from .operations import readiness
from .repository import ConflictError, NotFoundError, Repository, SqlRepository
from .schemas import (
    AccessRequest,
    AccessResponse,
    BiometricEnrollment,
    ConsentCreate,
    CustomerCreate,
    CustomerView,
    DebtRegularize,
    DebtView,
    NotificationView,
    OnboardingChatRequest,
    OnboardingChatResponse,
    OperatorOverview,
    OtpRequested,
    OtpVerify,
    PaymentCreate,
    PaymentPolicyUpdate,
    PaymentView,
    PaymentWebhook,
    PurchaseCreate,
    PurchaseItemView,
    PurchaseView,
    SimulatedAccessRequest,
    SimulatedAccessResponse,
    SimulatedBiometricEnrollment,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    validate_runtime_settings(settings)
    app.state.repository = SqlRepository.connect(
        settings.database_url,
        create_schema=settings.auto_create_schema,
        encryption_keys=settings.data_encryption_keys,
    )
    app.state.rate_limiter = SlidingWindowRateLimiter()
    app.state.otp_provider = DevelopmentOtpProvider()
    if (
        settings.environment.lower() == "production"
        and settings.onboarding_token_secret == "development-only-onboarding-secret-change-me"
    ):
        raise RuntimeError("onboarding token secret must be changed in production")
    app.state.onboarding_tokens = OnboardingTokenService(
        settings.onboarding_token_secret, settings.onboarding_token_ttl_seconds
    )
    auth_mode = settings.auth_mode.lower()
    if auth_mode == "development":
        if settings.environment.lower() == "production":
            raise RuntimeError("development authentication is forbidden in production")
        if not settings.development_auth_tokens:
            raise RuntimeError("development authentication requires at least one token")
        app.state.auth_provider = CompositeAuthProvider(
            DevelopmentTokenProvider(settings.development_auth_tokens),
            app.state.onboarding_tokens,
        )
    elif auth_mode == "disabled":
        app.state.auth_provider = None
    elif auth_mode == "supabase":
        if not settings.supabase_url:
            raise RuntimeError("Supabase authentication requires MARKET_SUPABASE_URL")
        app.state.auth_provider = SupabaseJwtProvider(
            project_url=settings.supabase_url,
            audience=settings.supabase_jwt_audience,
            role_claim=settings.supabase_role_claim,
        )
    else:
        raise RuntimeError(f"unsupported authentication mode: {settings.auth_mode}")
    yield


app = FastAPI(
    title="Autonomous Market API",
    version="0.1.0",
    description="Nucleo deterministico do MVP para mercados autonomos.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Correlation-ID"],
)

logger = logging.getLogger("market_api.http")


def error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {"code": code, "message": message},
            "correlation_id": correlation_id_context.get(),
        },
        headers=headers,
    )


@app.middleware("http")
async def authenticate_and_authorize(request: Request, call_next):
    matched = route_policy(request.method, request.url.path)
    provider = getattr(request.app.state, "auth_provider", None)
    if not matched or provider is None:
        return await call_next(request)
    route, path_match = matched
    try:
        principal = provider.authenticate(bearer_token(request))
    except AuthenticationError as exc:
        return error_response(
            status.HTTP_401_UNAUTHORIZED,
            "AUTHENTICATION_REQUIRED",
            str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )
    if principal.role not in route.roles:
        return error_response(
            status.HTTP_403_FORBIDDEN,
            "FORBIDDEN",
            "actor role is not allowed for this route",
        )
    if route.customer_scope_group and principal.role in {
        ActorRole.CUSTOMER,
        ActorRole.ONBOARDING,
    }:
        customer_id = path_match.group(route.customer_scope_group)
        if not hmac.compare_digest(principal.subject, customer_id):
            return error_response(
                status.HTTP_403_FORBIDDEN,
                "CUSTOMER_SCOPE_VIOLATION",
                "customer cannot access another customer resource",
            )
    request.state.principal = principal
    return await call_next(request)


@app.middleware("http")
async def observe_request(request: Request, call_next):
    correlation_id = new_correlation_id(request.headers.get("X-Correlation-ID"))
    context_token = correlation_id_context.set(correlation_id)
    started_at = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Correlation-ID"] = correlation_id
        return response
    finally:
        route_object = request.scope.get("route")
        route = getattr(route_object, "path", request.url.path)
        duration = observe_http(request.method, route, status_code, started_at)
        logger.info(
            "http_request",
            extra={
                "event": "http_request",
                "result": str(status_code),
                "duration_ms": round(duration * 1000, 3),
            },
        )
        correlation_id_context.reset(context_token)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    code = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        422: "UNPROCESSABLE_ENTITY",
        429: "RATE_LIMITED",
        503: "SERVICE_UNAVAILABLE",
    }.get(exc.status_code, "HTTP_ERROR")
    return error_response(exc.status_code, code, str(exc.detail), headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return error_response(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "VALIDATION_ERROR",
        "request validation failed",
    )


@app.exception_handler(Exception)
async def unexpected_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_exception", extra={"event": "unhandled_exception"})
    return error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "INTERNAL_ERROR",
        "unexpected internal error",
    )


def repository(request: Request) -> Repository:
    return request.app.state.repository


@app.get("/operator/overview", response_model=OperatorOverview)
def operator_overview(
    limit: int = Query(default=10, ge=1, le=50), repo: Repository = Depends(repository)
) -> OperatorOverview:
    return OperatorOverview.model_validate(repo.operator_overview(limit))


def check_rate_limit(request: Request, key: str, limit: int) -> None:
    try:
        request.app.state.rate_limiter.check(key, limit, 60)
    except RateLimitExceeded as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "rate limit exceeded",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc


def customer_or_404(repo: Repository, customer_id: str) -> Customer:
    try:
        return repo.get_customer(customer_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


def require_customer_ownership(request: Request, customer_id: str) -> None:
    principal = getattr(request.state, "principal", None)
    if (
        principal
        and principal.role == ActorRole.CUSTOMER
        and not hmac.compare_digest(principal.subject, customer_id)
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "customer cannot access another customer resource"
        )


def purchase_view(purchase: Purchase) -> PurchaseView:
    return PurchaseView(
        purchase_id=purchase.purchase_id,
        customer_id=purchase.customer_id,
        store_id=purchase.store_id,
        session_id=purchase.session_id,
        status=purchase.status,
        items=[
            PurchaseItemView(
                sku=item.sku,
                description=item.description,
                quantity=item.quantity,
                unit_price_cents=item.unit_price_cents,
                total_cents=item.total_cents,
            )
            for item in purchase.items
        ],
        subtotal_cents=purchase.subtotal_cents,
        discounts_cents=purchase.discounts_cents,
        total_cents=purchase.total_cents,
        created_at=purchase.created_at,
    )


def require_simulation() -> None:
    if not get_settings().simulation_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "simulation endpoints disabled")


def apply_payment_result(repo: Repository, payment: Payment, result: PaymentResult) -> Payment:
    payment.apply_provider_result(result.status, result.provider_reference, result.reason)
    repo.save_payment(payment)
    event = {
        PaymentStatus.PAID: "PaymentApproved",
        PaymentStatus.DECLINED: "PaymentDeclined",
        PaymentStatus.PENDING: "PaymentPending",
    }[payment.status]
    repo.audit(event, payment.customer_id, payment.payment_id, reason=payment.decline_reason)
    record_business_event("payment", payment.status.value)
    customer = customer_or_404(repo, payment.customer_id)
    if payment.status == PaymentStatus.DECLINED:
        customer.payment_policy_ok = False
        repo.save_customer(customer)
        notification = repo.add_notification(
            Notification(
                customer_id=payment.customer_id,
                event_type="PaymentDeclined",
                channel="WHATSAPP",
                template="payment_declined_v1",
                data={
                    "payment_id": payment.payment_id,
                    "purchase_id": payment.purchase_id,
                    "amount_cents": payment.amount_cents,
                    "regularization_path": f"/debts/{payment.payment_id}/regularize",
                },
                deduplication_key=f"payment-declined:{payment.payment_id}",
            )
        )
        repo.audit(
            "NotificationQueued",
            payment.customer_id,
            notification.notification_id,
            channel=notification.channel,
        )
        repo.audit(
            "AccessPolicyUpdated",
            payment.customer_id,
            payment.customer_id,
            payment_policy_ok=False,
            reason="OUTSTANDING_DEBT",
        )
    elif payment.status == PaymentStatus.PAID and not repo.list_open_debts(payment.customer_id):
        was_blocked = not customer.payment_policy_ok
        customer.payment_policy_ok = True
        repo.save_customer(customer)
        if was_blocked:
            repo.audit("DebtResolved", payment.customer_id, payment.payment_id)
            repo.audit(
                "AccessPolicyUpdated",
                payment.customer_id,
                payment.customer_id,
                payment_policy_ok=True,
                reason="ALL_DEBTS_RESOLVED",
            )
    return payment


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    if not get_settings().metrics_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "metrics endpoint disabled")
    payload, content_type = metrics_payload()
    return Response(content=payload, headers={"Content-Type": content_type})


@app.get("/operations/dead-letters", response_model=list[NotificationView])
def list_dead_letters(
    limit: int = Query(default=100, ge=1, le=500),
    repo: Repository = Depends(repository),
) -> list[Notification]:
    return repo.list_failed_notifications(limit)


@app.post("/operations/dead-letters/{notification_id}/requeue", response_model=NotificationView)
def requeue_dead_letter(
    notification_id: str, repo: Repository = Depends(repository)
) -> Notification:
    try:
        notification = repo.requeue_notification(notification_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    repo.audit(
        "NotificationRequeued",
        notification.customer_id,
        notification.notification_id,
        source="DEAD_LETTER",
    )
    record_business_event("notification", "REQUEUED")
    return notification


@app.post("/operations/encryption/rotate")
def rotate_encryption(
    dry_run: bool = False, repo: Repository = Depends(repository)
) -> dict[str, object]:
    before = repo.sensitive_data_inventory()
    if dry_run:
        return {"status": "dry_run", "active_key_id": repo.cipher.active_key_id, "before": before}
    try:
        rotated = repo.rotate_sensitive_data()
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    repo.audit("SensitiveDataRotated", "SYSTEM", "DATA-ENCRYPTION", **rotated)
    return {
        "status": "completed",
        "active_key_id": repo.cipher.active_key_id,
        "before": before,
        "after": repo.sensitive_data_inventory(),
        "rotated": rotated,
    }


@app.post("/operations/customers/{customer_id}/anonymize")
def anonymize_customer(customer_id: str, repo: Repository = Depends(repository)) -> dict[str, str]:
    if repo.list_open_debts(customer_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "customer with open debts cannot be anonymized"
        )
    try:
        repo.anonymize_customer(customer_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    repo.audit("CustomerAnonymized", customer_id, customer_id)
    record_business_event("privacy", "CUSTOMER_ANONYMIZED")
    return {"status": "anonymized", "customer_id": customer_id}


@app.post("/operations/retention/run")
def run_retention(repo: Repository = Depends(repository)) -> dict[str, object]:
    before = now_utc() - timedelta(days=get_settings().operational_retention_days)
    deleted = repo.purge_operational_data(before)
    repo.audit("OperationalDataPurged", "SYSTEM", "DATA-RETENTION", **deleted)
    return {"status": "completed", "before": before.isoformat(), "deleted": deleted}


@app.get("/ready")
def ready(repo: SqlRepository = Depends(repository)):
    try:
        details = readiness(repo, enforce_migration_head=get_settings().enforce_migration_head)
    except Exception as exc:  # noqa: BLE001 - readiness must degrade instead of crashing
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready", "detail": str(exc)},
        )
    return {"status": "ready", **details}


@app.post("/customers", response_model=CustomerView, status_code=status.HTTP_201_CREATED)
def create_customer(
    payload: CustomerCreate, request: Request, repo: Repository = Depends(repository)
) -> Customer:
    settings = get_settings()
    client_host = request.client.host if request.client else "unknown"
    check_rate_limit(
        request,
        f"registration:ip:{client_host}",
        settings.registration_rate_limit_per_minute,
    )
    customer = Customer(name=payload.name, phone=payload.phone, email=payload.email)
    try:
        repo.add_customer(customer)
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    repo.audit("CustomerRegistered", customer.customer_id, customer.customer_id)
    return customer


@app.post("/chat/onboarding", response_model=OnboardingChatResponse)
def onboarding_chat(
    payload: OnboardingChatRequest,
    request: Request,
    repo: Repository = Depends(repository),
) -> OnboardingChatResponse:
    settings = get_settings()
    if settings.environment.lower() == "production" and isinstance(
        request.app.state.otp_provider, DevelopmentOtpProvider
    ):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "production OTP delivery provider is not configured",
        )
    client_host = request.client.host if request.client else "unknown"
    check_rate_limit(request, f"chat:ip:{client_host}", settings.chat_rate_limit_per_minute)
    if payload.session_id:
        try:
            session = repo.get_chat_session(payload.session_id)
        except NotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    else:
        from .domain import OnboardingChatSession

        session = repo.add_chat_session(OnboardingChatSession())
        if not payload.message.strip() or is_greeting(payload.message):
            return OnboardingChatResponse.model_validate(
                {
                    "session_id": session.session_id,
                    "step": session.step,
                    "messages": [
                        "Olá! Vou ajudar você a se cadastrar no Mercadinho Central.",
                        "Vou pedir apenas os dados necessários e confirmar cada etapa.",
                        "Para começar, qual é o seu nome?",
                    ],
                    "expires_at": session.expires_at,
                }
            )
    result = advance_onboarding_chat(
        repo,
        session,
        payload.message,
        otp_provider=request.app.state.otp_provider,
        otp_ttl_minutes=settings.otp_ttl_minutes,
        check_otp_rate_limit=lambda customer_id: (
            check_rate_limit(request, f"otp:ip:{client_host}", settings.otp_rate_limit_per_minute),
            check_rate_limit(
                request,
                f"otp:customer:{customer_id}",
                settings.otp_rate_limit_per_minute,
            ),
        ),
    )
    return OnboardingChatResponse.model_validate(result)


@app.get("/customers/{customer_id}", response_model=CustomerView)
def get_customer(customer_id: str, repo: Repository = Depends(repository)) -> Customer:
    return customer_or_404(repo, customer_id)


@app.post("/customers/{customer_id}/otp", response_model=OtpRequested)
def request_otp(
    customer_id: str, request: Request, repo: Repository = Depends(repository)
) -> OtpRequested:
    customer = customer_or_404(repo, customer_id)
    settings = get_settings()
    if settings.environment.lower() == "production" and isinstance(
        request.app.state.otp_provider, DevelopmentOtpProvider
    ):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "production OTP delivery provider is not configured",
        )
    client_host = request.client.host if request.client else "unknown"
    check_rate_limit(request, f"otp:ip:{client_host}", settings.otp_rate_limit_per_minute)
    check_rate_limit(request, f"otp:customer:{customer_id}", settings.otp_rate_limit_per_minute)
    challenge, code = OtpChallenge.issue(customer_id, settings.otp_ttl_minutes)
    repo.add_otp(challenge)
    delivery = request.app.state.otp_provider.send(customer, code)
    repo.audit(
        "OtpRequested",
        customer_id,
        challenge.challenge_id,
        delivery_reference=delivery.provider_reference,
    )
    return OtpRequested(
        challenge_id=challenge.challenge_id,
        expires_at=challenge.expires_at,
        development_code=(
            delivery.development_code if settings.environment.lower() == "development" else None
        ),
        delivery_reference=delivery.provider_reference,
    )


@app.post("/customers/{customer_id}/otp/verify", response_model=CustomerView)
def verify_otp(
    customer_id: str,
    payload: OtpVerify,
    request: Request,
    response: Response,
    repo: Repository = Depends(repository),
) -> Customer:
    customer = customer_or_404(repo, customer_id)
    try:
        challenge = repo.get_otp(payload.challenge_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    if challenge.customer_id != customer_id or not challenge.verify(payload.code):
        repo.save_otp(challenge)
        repo.audit("OtpVerificationFailed", customer_id, payload.challenge_id)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid or expired OTP")
    repo.save_otp(challenge)
    customer.phone_verified = True
    customer.activate_if_ready()
    repo.save_customer(customer)
    repo.audit("PhoneVerified", customer_id, payload.challenge_id)
    token, expires_at = request.app.state.onboarding_tokens.issue(customer_id)
    response.headers["X-Onboarding-Token"] = token
    response.headers["X-Onboarding-Token-Expires-At"] = str(expires_at)
    return customer


@app.post("/customers/{customer_id}/consents", response_model=CustomerView)
def add_consent(
    customer_id: str,
    payload: ConsentCreate,
    repo: Repository = Depends(repository),
) -> Customer:
    customer = customer_or_404(repo, customer_id)
    customer.consents = [item for item in customer.consents if item.kind != payload.kind]
    customer.consents.append(Consent(kind=payload.kind, version=payload.version))
    customer.activate_if_ready()
    repo.save_customer(customer)
    repo.audit(
        "ConsentAccepted", customer_id, customer_id, kind=payload.kind, version=payload.version
    )
    return customer


@app.post("/customers/{customer_id}/biometrics", response_model=CustomerView)
def enroll_biometric(
    customer_id: str,
    payload: BiometricEnrollment,
    repo: Repository = Depends(repository),
) -> Customer:
    customer = customer_or_404(repo, customer_id)
    if not payload.liveness_passed:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "liveness check failed")
    customer.biometric_ref = payload.biometric_ref
    customer.biometric_valid = True
    customer.activate_if_ready()
    repo.save_customer(customer)
    repo.audit("FaceEnrolled", customer_id, customer_id, liveness="PASS")
    return customer


@app.post("/simulations/customers/{customer_id}/biometrics", response_model=CustomerView)
def simulate_biometric_enrollment(
    customer_id: str,
    payload: SimulatedBiometricEnrollment,
    repo: Repository = Depends(repository),
) -> Customer:
    require_simulation()
    customer = customer_or_404(repo, customer_id)
    result = SimulatedBiometricProvider().enroll(payload.sample_reference)
    if not result.liveness_passed:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "liveness check failed")
    customer.biometric_ref = result.biometric_ref
    customer.biometric_valid = True
    customer.activate_if_ready()
    repo.save_customer(customer)
    repo.audit("FaceEnrolled", customer_id, customer_id, provider="SIMULATED")
    return customer


@app.patch("/customers/{customer_id}/payment-policy", response_model=CustomerView)
def update_payment_policy(
    customer_id: str,
    payload: PaymentPolicyUpdate,
    repo: Repository = Depends(repository),
) -> Customer:
    customer = customer_or_404(repo, customer_id)
    customer.payment_policy_ok = payload.payment_policy_ok
    repo.save_customer(customer)
    repo.audit("PaymentPolicyUpdated", customer_id, customer_id, allowed=payload.payment_policy_ok)
    return customer


@app.post("/customers/{customer_id}/block", response_model=CustomerView)
def block_customer(customer_id: str, repo: Repository = Depends(repository)) -> Customer:
    customer = customer_or_404(repo, customer_id)
    customer.status = CustomerStatus.BLOCKED
    repo.save_customer(customer)
    repo.audit("CustomerBlocked", customer_id, customer_id)
    return customer


@app.post("/customers/{customer_id}/unblock", response_model=CustomerView)
def unblock_customer(customer_id: str, repo: Repository = Depends(repository)) -> Customer:
    customer = customer_or_404(repo, customer_id)
    customer.status = CustomerStatus.PENDING
    customer.activate_if_ready()
    repo.save_customer(customer)
    repo.audit("CustomerUnblocked", customer_id, customer_id)
    return customer


@app.post("/access/authorize", response_model=AccessResponse)
def authorize_access(
    payload: AccessRequest, repo: Repository = Depends(repository)
) -> AccessResponse:
    customer = customer_or_404(repo, payload.customer_id)
    access_id = new_id("ACC")
    if not payload.liveness_passed:
        decision_authorized, decision_reason = False, "LIVENESS_FAILED"
    elif payload.recognition_confidence < 0.85:
        decision_authorized, decision_reason = False, "LOW_RECOGNITION_CONFIDENCE"
    else:
        decision = decide_access(customer)
        decision_authorized, decision_reason = decision.authorized, decision.reason
    session_id = new_id("SES") if decision_authorized else None
    repo.audit(
        "AccessAuthorized" if decision_authorized else "AccessDenied",
        customer.customer_id,
        access_id,
        session_id=session_id,
        store_id=payload.store_id,
        door_id=payload.door_id,
        device_id=payload.device_id,
        recognition_confidence=payload.recognition_confidence,
        reason=decision_reason,
    )
    record_business_event("access", "AUTHORIZED" if decision_authorized else decision_reason)
    return AccessResponse(
        access_id=access_id,
        session_id=session_id,
        authorized=decision_authorized,
        reason=decision_reason,
        decided_at=now_utc(),
    )


@app.post("/simulations/access", response_model=SimulatedAccessResponse)
def simulate_access(
    payload: SimulatedAccessRequest, repo: Repository = Depends(repository)
) -> SimulatedAccessResponse:
    require_simulation()
    customer = customer_or_404(repo, payload.customer_id)
    if not customer.biometric_ref:
        raise HTTPException(status.HTTP_409_CONFLICT, "customer has no biometric enrollment")
    verification = SimulatedBiometricProvider().verify(
        customer.biometric_ref, payload.sample_reference
    )
    access_id = new_id("ACC")
    if not verification.liveness_passed:
        authorized, reason = False, "LIVENESS_FAILED"
    elif not verification.matched or verification.confidence < 0.85:
        authorized, reason = False, "LOW_RECOGNITION_CONFIDENCE"
    else:
        decision = decide_access(customer)
        authorized, reason = decision.authorized, decision.reason
    session_id = new_id("SES") if authorized else None
    door_opened = False
    door_reference = None
    if authorized:
        try:
            door = SimulatedDoorController().open(
                payload.store_id, payload.door_id, payload.device_id
            )
        except IntegrationError as exc:
            authorized, reason, session_id = False, "DOOR_UNAVAILABLE", None
            repo.audit("DoorOpenFailed", customer.customer_id, access_id, error=str(exc))
        else:
            door_opened = door.opened
            door_reference = door.provider_reference
            repo.audit(
                "DoorOpened",
                customer.customer_id,
                access_id,
                provider_reference=door_reference,
            )
    repo.audit(
        "AccessAuthorized" if authorized else "AccessDenied",
        customer.customer_id,
        access_id,
        session_id=session_id,
        store_id=payload.store_id,
        door_id=payload.door_id,
        device_id=payload.device_id,
        recognition_confidence=verification.confidence,
        reason=reason,
        provider="SIMULATED",
    )
    record_business_event("access", "AUTHORIZED" if authorized else reason)
    return SimulatedAccessResponse(
        access_id=access_id,
        session_id=session_id,
        authorized=authorized,
        reason=reason,
        decided_at=now_utc(),
        door_opened=door_opened,
        door_reference=door_reference,
    )


@app.post("/purchases", response_model=PurchaseView, status_code=status.HTTP_201_CREATED)
def create_purchase(
    payload: PurchaseCreate,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=120),
    repo: Repository = Depends(repository),
) -> PurchaseView:
    existing = repo.get_purchase_by_idempotency(idempotency_key)
    if existing:
        return purchase_view(existing)
    customer_or_404(repo, payload.customer_id)
    purchase = Purchase(
        customer_id=payload.customer_id,
        store_id=payload.store_id,
        session_id=payload.session_id,
        items=[PurchaseItem(**item.model_dump()) for item in payload.items],
        discounts_cents=payload.discounts_cents,
    )
    if purchase.total_cents < 0:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "discount cannot exceed subtotal"
        )
    repo.add_purchase(purchase, idempotency_key)
    repo.audit(
        "PurchaseCompleted",
        purchase.customer_id,
        purchase.purchase_id,
        session_id=purchase.session_id,
        total_cents=purchase.total_cents,
    )
    return purchase_view(purchase)


@app.get("/purchases/{purchase_id}", response_model=PurchaseView)
def get_purchase(
    purchase_id: str, request: Request, repo: Repository = Depends(repository)
) -> PurchaseView:
    try:
        purchase = repo.get_purchase(purchase_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    require_customer_ownership(request, purchase.customer_id)
    return purchase_view(purchase)


@app.post("/payments", response_model=PaymentView, status_code=status.HTTP_201_CREATED)
def create_payment(
    payload: PaymentCreate,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=120),
    repo: Repository = Depends(repository),
) -> Payment:
    existing = repo.get_payment_by_idempotency(idempotency_key)
    if existing:
        return existing
    try:
        purchase = repo.get_purchase(payload.purchase_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    payment = Payment(
        purchase_id=purchase.purchase_id,
        customer_id=purchase.customer_id,
        amount_cents=purchase.total_cents,
        method_token=payload.method_token,
    )
    payment.request()
    try:
        repo.add_payment(payment, idempotency_key)
    except Exception as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "purchase already has a payment") from exc
    repo.audit(
        "PaymentRequested",
        payment.customer_id,
        payment.payment_id,
        amount_cents=payment.amount_cents,
    )
    return payment


@app.get("/payments/{payment_id}", response_model=PaymentView)
def get_payment(
    payment_id: str, request: Request, repo: Repository = Depends(repository)
) -> Payment:
    try:
        payment = repo.get_payment(payment_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    require_customer_ownership(request, payment.customer_id)
    return payment


@app.post("/simulations/payments/{payment_id}/settle", response_model=PaymentView)
def simulate_payment_settlement(payment_id: str, repo: Repository = Depends(repository)) -> Payment:
    require_simulation()
    try:
        payment = repo.get_payment(payment_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    try:
        result = SimulatedPaymentProvider().charge(payment)
        return apply_payment_result(repo, payment, result)
    except IntegrationError as exc:
        repo.audit("PaymentProviderFailed", payment.customer_id, payment.payment_id, error=str(exc))
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@app.get("/customers/{customer_id}/debts", response_model=list[DebtView])
def list_customer_debts(customer_id: str, repo: Repository = Depends(repository)) -> list[DebtView]:
    customer_or_404(repo, customer_id)
    return [
        DebtView(
            payment_id=payment.payment_id,
            purchase_id=payment.purchase_id,
            amount_cents=payment.amount_cents,
            status=payment.status,
            decline_reason=payment.decline_reason,
            updated_at=payment.updated_at,
        )
        for payment in repo.list_open_debts(customer_id)
    ]


@app.get("/customers/{customer_id}/notifications", response_model=list[NotificationView])
def list_customer_notifications(
    customer_id: str, repo: Repository = Depends(repository)
) -> list[Notification]:
    customer_or_404(repo, customer_id)
    return repo.list_notifications(customer_id)


@app.post("/debts/{payment_id}/regularize", response_model=PaymentView)
def regularize_debt(
    payment_id: str,
    payload: DebtRegularize,
    request: Request,
    repo: Repository = Depends(repository),
) -> Payment:
    try:
        payment = repo.get_payment(payment_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    require_customer_ownership(request, payment.customer_id)
    if payment.status not in {
        PaymentStatus.DECLINED,
        PaymentStatus.PENDING,
        PaymentStatus.UNPAID,
    }:
        raise HTTPException(status.HTTP_409_CONFLICT, "debt is not eligible for regularization")
    payment.method_token = payload.method_token
    payment.request(retry=True)
    repo.save_payment(payment)
    repo.audit(
        "DebtRegularizationRequested",
        payment.customer_id,
        payment.payment_id,
        attempt=payment.attempts,
    )
    return payment


@app.post("/payments/{payment_id}/retry", response_model=PaymentView)
def retry_payment(payment_id: str, repo: Repository = Depends(repository)) -> Payment:
    try:
        payment = repo.get_payment(payment_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    if payment.status not in {PaymentStatus.DECLINED, PaymentStatus.PENDING}:
        raise HTTPException(status.HTTP_409_CONFLICT, "payment is not eligible for retry")
    payment.request(retry=True)
    repo.save_payment(payment)
    repo.audit("PaymentRequested", payment.customer_id, payment.payment_id, retry=True)
    return payment


@app.post("/webhooks/payment", response_model=PaymentView)
def payment_webhook(
    payload: PaymentWebhook,
    signature: str = Header(alias="X-Webhook-Signature"),
    repo: Repository = Depends(repository),
) -> Payment:
    signed = f"{payload.event_id}:{payload.payment_id}:{payload.status.value}".encode()
    expected = hmac.new(get_settings().webhook_secret.encode(), signed, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid webhook signature")
    try:
        payment = repo.get_payment(payload.payment_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    if not repo.claim_webhook(payload.event_id):
        return payment
    try:
        return apply_payment_result(
            repo,
            payment,
            PaymentResult(payload.status, payload.provider_reference, payload.reason),
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@app.get("/webhooks/whatsapp")
def verify_whatsapp_webhook(
    mode: str = Query(alias="hub.mode"),
    challenge: str = Query(alias="hub.challenge"),
    verify_token: str = Query(alias="hub.verify_token"),
):
    expected = get_settings().whatsapp_verify_token
    if mode != "subscribe" or not expected or not hmac.compare_digest(verify_token, expected):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "webhook verification failed")
    return PlainTextResponse(challenge)


@app.post("/webhooks/whatsapp")
async def whatsapp_delivery_webhook(
    request: Request,
    signature: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    repo: Repository = Depends(repository),
) -> dict[str, bool]:
    settings = get_settings()
    if not settings.whatsapp_app_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "WhatsApp webhook not configured")
    body = await request.body()
    expected = (
        "sha256="
        + hmac.new(settings.whatsapp_app_secret.encode(), body, hashlib.sha256).hexdigest()
    )
    if not signature or not hmac.compare_digest(signature, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid WhatsApp signature")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid JSON") from exc
    mapping = {
        "sent": NotificationStatus.SENT,
        "delivered": NotificationStatus.DELIVERED,
        "read": NotificationStatus.READ,
        "failed": NotificationStatus.FAILED,
    }
    rank = {
        NotificationStatus.SENT: 1,
        NotificationStatus.DELIVERED: 2,
        NotificationStatus.READ: 3,
    }
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for delivery in change.get("value", {}).get("statuses", []):
                target = mapping.get(delivery.get("status"))
                if not target:
                    continue
                try:
                    notification = repo.get_notification_by_provider_reference(delivery["id"])
                except (KeyError, NotFoundError):
                    continue
                if target != NotificationStatus.FAILED and rank.get(target, 0) <= rank.get(
                    notification.status, 0
                ):
                    continue
                notification.status = target
                if target == NotificationStatus.FAILED:
                    errors = delivery.get("errors") or []
                    notification.last_error = (
                        str(errors[0].get("title", "delivery failed"))[:500]
                        if errors
                        else "delivery failed"
                    )
                repo.save_notification(notification)
                repo.audit(
                    f"Notification{target.value.title()}",
                    notification.customer_id,
                    notification.notification_id,
                    provider_reference=notification.provider_reference,
                )
    return {"received": True}
