from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

import jwt
from fastapi import Request
from jwt import InvalidTokenError
from jwt.jwks_client import PyJWKClient, PyJWKClientError


class ActorRole(StrEnum):
    ONBOARDING = "ONBOARDING"
    CUSTOMER = "CUSTOMER"
    OPERATOR = "OPERATOR"
    DEVICE = "DEVICE"
    INTEGRATOR = "INTEGRATOR"
    SYSTEM = "SYSTEM"


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    role: ActorRole


class AuthenticationError(ValueError):
    pass


class AuthProvider(Protocol):
    def authenticate(self, token: str) -> Principal: ...


class DevelopmentTokenProvider:
    """Tokens opacos locais; somente hashes permanecem em memoria."""

    def __init__(self, tokens: dict[str, str]) -> None:
        self._principals = {
            hashlib.sha256(token.encode()).digest(): self._parse_principal(value)
            for token, value in tokens.items()
        }

    @staticmethod
    def _parse_principal(value: str) -> Principal:
        try:
            subject, raw_role = value.rsplit(":", 1)
            return Principal(subject, ActorRole(raw_role.upper()))
        except (ValueError, KeyError) as exc:
            raise ValueError("auth token values must use SUBJECT:ROLE") from exc

    def authenticate(self, token: str) -> Principal:
        candidate = hashlib.sha256(token.encode()).digest()
        for expected, principal in self._principals.items():
            if hmac.compare_digest(candidate, expected):
                return principal
        raise AuthenticationError("invalid bearer token")


class CompositeAuthProvider:
    def __init__(self, *providers: AuthProvider) -> None:
        self.providers = providers

    def authenticate(self, token: str) -> Principal:
        for provider in self.providers:
            try:
                return provider.authenticate(token)
            except AuthenticationError:
                continue
        raise AuthenticationError("invalid bearer token")


class SupabaseJwtProvider:
    """Valida access tokens do Supabase Auth usando a chave pública JWKS."""

    def __init__(
        self,
        *,
        project_url: str,
        audience: str = "authenticated",
        role_claim: str = "app_metadata.market_role",
    ) -> None:
        base_url = project_url.rstrip("/")
        self._issuer = f"{base_url}/auth/v1"
        self._audience = audience
        self._role_claim = role_claim
        self._jwks = PyJWKClient(f"{self._issuer}/.well-known/jwks.json")

    def authenticate(self, token: str) -> Principal:
        try:
            signing_key = self._jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256", "RS256"],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["sub", "exp", "iat"]},
            )
        except (InvalidTokenError, PyJWKClientError, ValueError) as exc:
            raise AuthenticationError("invalid Supabase bearer token") from exc

        role_value: object = claims
        for part in self._role_claim.split("."):
            if not isinstance(role_value, dict) or part not in role_value:
                raise AuthenticationError("Supabase token does not contain an operator role")
            role_value = role_value[part]
        try:
            role = ActorRole(str(role_value).upper())
        except ValueError as exc:
            raise AuthenticationError("Supabase token contains an unsupported actor role") from exc
        return Principal(str(claims["sub"]), role)


@dataclass(frozen=True, slots=True)
class RoutePolicy:
    method: str
    pattern: re.Pattern[str]
    roles: frozenset[ActorRole]
    customer_scope_group: str | None = None


def policy(
    method: str,
    path: str,
    *roles: ActorRole,
    customer_scope_group: str | None = None,
) -> RoutePolicy:
    return RoutePolicy(method, re.compile(path), frozenset(roles), customer_scope_group)


ROUTE_POLICIES = (
    policy("GET", r"^/operator/overview$", ActorRole.OPERATOR, ActorRole.SYSTEM),
    policy("GET", r"^/metrics$", ActorRole.SYSTEM, ActorRole.OPERATOR),
    policy("GET", r"^/operations/dead-letters$", ActorRole.SYSTEM, ActorRole.OPERATOR),
    policy(
        "POST",
        r"^/operations/dead-letters/[^/]+/requeue$",
        ActorRole.SYSTEM,
        ActorRole.OPERATOR,
    ),
    policy("POST", r"^/operations/encryption/rotate$", ActorRole.SYSTEM, ActorRole.OPERATOR),
    policy(
        "POST",
        r"^/operations/customers/[^/]+/anonymize$",
        ActorRole.SYSTEM,
        ActorRole.OPERATOR,
    ),
    policy("POST", r"^/operations/retention/run$", ActorRole.SYSTEM, ActorRole.OPERATOR),
    policy(
        "POST",
        r"^/customers/(?P<customer_id>[^/]+)/(consents|biometrics)$",
        ActorRole.ONBOARDING,
        ActorRole.OPERATOR,
        customer_scope_group="customer_id",
    ),
    policy(
        "POST",
        r"^/simulations/customers/(?P<customer_id>[^/]+)/biometrics$",
        ActorRole.ONBOARDING,
        ActorRole.OPERATOR,
        customer_scope_group="customer_id",
    ),
    policy(
        "GET",
        r"^/customers/(?P<customer_id>[^/]+)$",
        ActorRole.CUSTOMER,
        ActorRole.OPERATOR,
        customer_scope_group="customer_id",
    ),
    policy("PATCH", r"^/customers/[^/]+/payment-policy$", ActorRole.OPERATOR),
    policy("POST", r"^/customers/[^/]+/(block|unblock)$", ActorRole.OPERATOR),
    policy("POST", r"^/access/authorize$", ActorRole.DEVICE, ActorRole.OPERATOR),
    policy("POST", r"^/purchases$", ActorRole.INTEGRATOR, ActorRole.OPERATOR),
    policy(
        "GET", r"^/purchases/[^/]+$", ActorRole.CUSTOMER, ActorRole.INTEGRATOR, ActorRole.OPERATOR
    ),
    policy("POST", r"^/payments$", ActorRole.INTEGRATOR, ActorRole.OPERATOR),
    policy(
        "GET", r"^/payments/[^/]+$", ActorRole.CUSTOMER, ActorRole.INTEGRATOR, ActorRole.OPERATOR
    ),
    policy(
        "GET",
        r"^/customers/(?P<customer_id>[^/]+)/(debts|notifications)$",
        ActorRole.CUSTOMER,
        ActorRole.OPERATOR,
        customer_scope_group="customer_id",
    ),
    policy("POST", r"^/debts/[^/]+/regularize$", ActorRole.CUSTOMER, ActorRole.OPERATOR),
    policy("POST", r"^/payments/[^/]+/retry$", ActorRole.OPERATOR, ActorRole.SYSTEM),
    policy("POST", r"^/simulations(?:/|$)", ActorRole.OPERATOR),
)


def route_policy(method: str, path: str) -> tuple[RoutePolicy, re.Match[str]] | None:
    for item in ROUTE_POLICIES:
        match = item.pattern.match(path)
        if item.method == method and match:
            return item, match
    return None


def bearer_token(request: Request) -> str:
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthenticationError("bearer token required")
    return token
