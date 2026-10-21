from fastapi.testclient import TestClient

from market_api.config import get_settings
from market_api.main import app


def configure(tmp_path, monkeypatch, *, otp_limit: int = 3) -> None:
    monkeypatch.setenv("MARKET_DATABASE_URL", f"sqlite:///{tmp_path / 'onboarding.db'}")
    monkeypatch.setenv("MARKET_ENVIRONMENT", "development")
    monkeypatch.setenv("MARKET_AUTH_MODE", "development")
    monkeypatch.setenv("MARKET_DEVELOPMENT_AUTH_TOKENS", '{"operator":"op:OPERATOR"}')
    monkeypatch.setenv(
        "MARKET_ONBOARDING_TOKEN_SECRET", "test-onboarding-secret-with-32-characters"
    )
    monkeypatch.setenv("MARKET_OTP_RATE_LIMIT_PER_MINUTE", str(otp_limit))
    get_settings.cache_clear()


def test_verified_otp_issues_scoped_onboarding_token(tmp_path, monkeypatch) -> None:
    configure(tmp_path, monkeypatch)

    with TestClient(app) as client:
        customer = client.post(
            "/customers", json={"name": "Cliente Onboarding", "phone": "+5511888888888"}
        ).json()
        customer_id = customer["customer_id"]
        otp = client.post(f"/customers/{customer_id}/otp").json()
        verified = client.post(
            f"/customers/{customer_id}/otp/verify",
            json={"challenge_id": otp["challenge_id"], "code": otp["development_code"]},
        )
        token = verified.headers["X-Onboarding-Token"]
        consent = client.post(
            f"/customers/{customer_id}/consents",
            headers={"Authorization": f"Bearer {token}"},
            json={"kind": "TERMS", "version": "1.0"},
        )

    assert verified.status_code == 200
    assert consent.status_code == 200


def test_onboarding_token_cannot_modify_another_customer(tmp_path, monkeypatch) -> None:
    configure(tmp_path, monkeypatch)

    with TestClient(app) as client:
        first = client.post(
            "/customers", json={"name": "Cliente Primeiro", "phone": "+5511877777777"}
        ).json()
        second = client.post(
            "/customers", json={"name": "Cliente Segundo", "phone": "+5511866666666"}
        ).json()
        otp = client.post(f"/customers/{first['customer_id']}/otp").json()
        verified = client.post(
            f"/customers/{first['customer_id']}/otp/verify",
            json={"challenge_id": otp["challenge_id"], "code": otp["development_code"]},
        )
        response = client.post(
            f"/customers/{second['customer_id']}/consents",
            headers={"Authorization": f"Bearer {verified.headers['X-Onboarding-Token']}"},
            json={"kind": "TERMS", "version": "1.0"},
        )

    assert response.status_code == 403


def test_new_otp_invalidates_previous_challenge(tmp_path, monkeypatch) -> None:
    configure(tmp_path, monkeypatch)

    with TestClient(app) as client:
        customer = client.post(
            "/customers", json={"name": "Cliente OTP", "phone": "+5511855555555"}
        ).json()
        first = client.post(f"/customers/{customer['customer_id']}/otp").json()
        client.post(f"/customers/{customer['customer_id']}/otp")
        response = client.post(
            f"/customers/{customer['customer_id']}/otp/verify",
            json={"challenge_id": first["challenge_id"], "code": first["development_code"]},
        )

    assert response.status_code == 404


def test_otp_rate_limit_returns_retry_after(tmp_path, monkeypatch) -> None:
    configure(tmp_path, monkeypatch, otp_limit=1)

    with TestClient(app) as client:
        customer = client.post(
            "/customers", json={"name": "Cliente Limite", "phone": "+5511844444444"}
        ).json()
        first = client.post(f"/customers/{customer['customer_id']}/otp")
        limited = client.post(f"/customers/{customer['customer_id']}/otp")

    assert first.status_code == 200
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1


def test_malformed_onboarding_token_is_rejected(tmp_path, monkeypatch) -> None:
    configure(tmp_path, monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/customers/CUST-ANY/consents",
            headers={"Authorization": "Bearer onb.not-base64.invalid"},
            json={"kind": "TERMS", "version": "1.0"},
        )

    assert response.status_code == 401
