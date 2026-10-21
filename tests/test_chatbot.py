from fastapi.testclient import TestClient

from market_api.config import get_settings
from market_api.main import app


def configure(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARKET_DATABASE_URL", f"sqlite:///{tmp_path / 'chat.db'}")
    monkeypatch.setenv("MARKET_ENVIRONMENT", "development")
    monkeypatch.setenv("MARKET_AUTH_MODE", "disabled")
    monkeypatch.setenv("MARKET_CHAT_RATE_LIMIT_PER_MINUTE", "100")
    get_settings.cache_clear()


def send(client: TestClient, session_id: str, message: str) -> dict:
    response = client.post(
        "/chat/onboarding", json={"session_id": session_id, "message": message}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_onboarding_chat_completes_until_biometric_handoff(tmp_path, monkeypatch) -> None:
    configure(tmp_path, monkeypatch)

    with TestClient(app) as client:
        start = client.post("/chat/onboarding", json={"message": "oi"})
        assert start.status_code == 200
        session_id = start.json()["session_id"]
        assert start.json()["step"] == "NAME"

        assert send(client, session_id, "Meu nome é Ana Souza")["step"] == "PHONE"
        assert send(client, session_id, "(11) 99999-1234")["step"] == "EMAIL"
        otp = send(client, session_id, "pular")
        assert otp["step"] == "OTP"
        assert otp["development_code"]
        verified = send(client, session_id, otp["development_code"])
        assert verified["step"] == "TERMS"
        assert send(client, session_id, "sim")["step"] == "PRIVACY"
        assert send(client, session_id, "concordo")["step"] == "BIOMETRICS"
        final = send(client, session_id, "sim")

        assert final["step"] == "BIOMETRIC_HANDOFF"
        assert final["next_action"] == "BIOMETRIC_ENROLLMENT"
        assert final["customer_id"].startswith("CUST-")
        customer = client.get(f"/customers/{final['customer_id']}").json()
        assert customer["phone_verified"] is True
        stored_customer = app.state.repository.get_customer(final["customer_id"])
        assert {item.kind for item in stored_customer.consents} == {
            "TERMS",
            "PRIVACY",
            "BIOMETRICS",
        }


def test_onboarding_chat_rejects_invalid_otp_without_consuming_session(tmp_path, monkeypatch) -> None:
    configure(tmp_path, monkeypatch)

    with TestClient(app) as client:
        session = client.post("/chat/onboarding", json={"message": "oi"}).json()["session_id"]
        send(client, session, "João da Silva")
        send(client, session, "+5511999998888")
        otp = send(client, session, "sem email")
        invalid = send(client, session, "000000")
        assert invalid["step"] == "OTP"
        assert "inválido" in invalid["messages"][0]
        valid = send(client, session, otp["development_code"])
        assert valid["step"] == "TERMS"


def test_onboarding_chat_can_resend_otp(tmp_path, monkeypatch) -> None:
    configure(tmp_path, monkeypatch)

    with TestClient(app) as client:
        session = client.post("/chat/onboarding", json={"message": "oi"}).json()["session_id"]
        send(client, session, "Ana Souza")
        send(client, session, "11999997777")
        first = send(client, session, "pular")
        second = send(client, session, "reenviar código")

        assert second["step"] == "OTP"
        assert second["development_code"] != first["development_code"]
        assert send(client, session, second["development_code"])["step"] == "TERMS"
