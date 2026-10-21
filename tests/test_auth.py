from time import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

import market_api.auth as auth_module
from market_api.auth import AuthenticationError, SupabaseJwtProvider
from market_api.config import get_settings
from market_api.main import app


@pytest.fixture(autouse=True)
def clear_settings_after_test():
    yield
    get_settings.cache_clear()


def configure_auth(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARKET_DATABASE_URL", f"sqlite:///{tmp_path / 'auth.db'}")
    monkeypatch.setenv("MARKET_AUTH_MODE", "development")
    monkeypatch.setenv(
        "MARKET_ONBOARDING_TOKEN_SECRET", "test-onboarding-secret-with-32-characters"
    )
    monkeypatch.setenv(
        "MARKET_DEVELOPMENT_AUTH_TOKENS",
        '{"operator-token":"operator-1:OPERATOR",'
        '"device-token":"door-1:DEVICE",'
        '"customer-token":"CUST-EXPECTED:CUSTOMER"}',
    )
    get_settings.cache_clear()


def test_protected_route_requires_bearer_token(tmp_path, monkeypatch) -> None:
    configure_auth(tmp_path, monkeypatch)

    with TestClient(app) as client:
        response = client.get("/customers/CUST-EXPECTED")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_operator_can_use_protected_customer_route(tmp_path, monkeypatch) -> None:
    configure_auth(tmp_path, monkeypatch)

    with TestClient(app) as client:
        customer = client.post(
            "/customers", json={"name": "Cliente Auth", "phone": "+5511900000001"}
        ).json()
        response = client.get(
            f"/customers/{customer['customer_id']}",
            headers={"Authorization": "Bearer operator-token"},
        )

    assert response.status_code == 200


def test_role_and_customer_scope_are_enforced(tmp_path, monkeypatch) -> None:
    configure_auth(tmp_path, monkeypatch)

    with TestClient(app) as client:
        wrong_role = client.get(
            "/customers/CUST-EXPECTED", headers={"Authorization": "Bearer device-token"}
        )
        wrong_customer = client.get(
            "/customers/CUST-OTHER", headers={"Authorization": "Bearer customer-token"}
        )

    assert wrong_role.status_code == 403
    assert wrong_customer.status_code == 403


def test_development_authentication_is_forbidden_in_production(tmp_path, monkeypatch) -> None:
    configure_auth(tmp_path, monkeypatch)
    monkeypatch.setenv("MARKET_ENVIRONMENT", "production")
    get_settings.cache_clear()

    with pytest.raises(RuntimeError, match="unsafe production configuration"), TestClient(app):
        pass


def test_supabase_jwt_provider_validates_role_claim(monkeypatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    issued_at = int(time())
    token = jwt.encode(
        {
            "sub": "supabase-user-1",
            "iss": "https://project.supabase.co/auth/v1",
            "aud": "authenticated",
            "iat": issued_at,
            "exp": issued_at + 3_600,
            "app_metadata": {"market_role": "operator"},
        },
        private_key,
        algorithm="RS256",
    )

    class FakeSigningKey:
        key = private_key.public_key()

    class FakeJwkClient:
        def __init__(self, url: str) -> None:
            assert url == "https://project.supabase.co/auth/v1/.well-known/jwks.json"

        def get_signing_key_from_jwt(self, candidate: str) -> FakeSigningKey:
            assert candidate == token
            return FakeSigningKey()

    monkeypatch.setattr(auth_module, "PyJWKClient", FakeJwkClient)
    provider = SupabaseJwtProvider(project_url="https://project.supabase.co")

    principal = provider.authenticate(token)

    assert principal.subject == "supabase-user-1"
    assert principal.role.value == "OPERATOR"


def test_supabase_jwt_provider_rejects_missing_role(monkeypatch) -> None:
    class FakeJwkClient:
        def __init__(self, url: str) -> None:
            pass

        def get_signing_key_from_jwt(self, candidate: str):
            raise auth_module.PyJWKClientError("unknown key")

    monkeypatch.setattr(auth_module, "PyJWKClient", FakeJwkClient)
    provider = SupabaseJwtProvider(project_url="https://project.supabase.co")

    with pytest.raises(AuthenticationError, match="invalid Supabase bearer token"):
        provider.authenticate("not-a-jwt")
