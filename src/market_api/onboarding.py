from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Protocol

from .auth import ActorRole, AuthenticationError, Principal
from .domain import Customer


class RateLimitExceeded(RuntimeError):
    def __init__(self, retry_after: int) -> None:
        super().__init__("rate limit exceeded")
        self.retry_after = retry_after


class SlidingWindowRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window_seconds: int) -> None:
        now = time.monotonic()
        events = self._events[key]
        cutoff = now - window_seconds
        while events and events[0] <= cutoff:
            events.popleft()
        if len(events) >= limit:
            retry_after = max(1, int(window_seconds - (now - events[0])) + 1)
            raise RateLimitExceeded(retry_after)
        events.append(now)


@dataclass(frozen=True, slots=True)
class OtpDeliveryResult:
    provider_reference: str
    development_code: str | None = None


class OtpDeliveryProvider(Protocol):
    def send(self, customer: Customer, code: str) -> OtpDeliveryResult: ...


class DevelopmentOtpProvider:
    """Expõe o codigo apenas para testes locais e nunca registra o valor."""

    def send(self, customer: Customer, code: str) -> OtpDeliveryResult:
        return OtpDeliveryResult(
            provider_reference=f"otp-local-{secrets.token_hex(8)}", development_code=code
        )


class OnboardingTokenService:
    def __init__(self, secret: str, ttl_seconds: int = 900) -> None:
        if len(secret) < 32:
            raise ValueError("onboarding token secret must have at least 32 characters")
        self.secret = secret.encode()
        self.ttl_seconds = ttl_seconds

    @staticmethod
    def _encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

    def issue(self, customer_id: str) -> tuple[str, int]:
        expires_at = int(time.time()) + self.ttl_seconds
        payload = self._encode(
            json.dumps(
                {"sub": customer_id, "role": "ONBOARDING", "exp": expires_at},
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        )
        signature = self._encode(hmac.new(self.secret, payload.encode(), hashlib.sha256).digest())
        return f"onb.{payload}.{signature}", expires_at

    def authenticate(self, token: str) -> Principal:
        try:
            prefix, payload, signature = token.split(".")
            if prefix != "onb":
                raise ValueError
            expected = self._encode(
                hmac.new(self.secret, payload.encode(), hashlib.sha256).digest()
            )
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            padding = "=" * (-len(payload) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload + padding))
            if claims.get("role") != ActorRole.ONBOARDING or int(claims["exp"]) <= time.time():
                raise ValueError
            return Principal(str(claims["sub"]), ActorRole.ONBOARDING)
        except (
            binascii.Error,
            KeyError,
            TypeError,
            UnicodeDecodeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise AuthenticationError("invalid or expired onboarding token") from exc
