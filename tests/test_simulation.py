from fastapi.testclient import TestClient

from market_api.config import get_settings
from market_api.main import app


def onboard_customer(client: TestClient, phone: str) -> str:
    customer = client.post("/customers", json={"name": "Cliente Piloto", "phone": phone}).json()
    customer_id = customer["customer_id"]
    otp = client.post(f"/customers/{customer_id}/otp").json()
    verified = client.post(
        f"/customers/{customer_id}/otp/verify",
        json={"challenge_id": otp["challenge_id"], "code": otp["development_code"]},
    )
    assert verified.status_code == 200
    for kind in ("TERMS", "PRIVACY", "BIOMETRICS"):
        response = client.post(
            f"/customers/{customer_id}/consents", json={"kind": kind, "version": "1.0"}
        )
        assert response.status_code == 200
    enrolled = client.post(
        f"/simulations/customers/{customer_id}/biometrics",
        json={"sample_reference": "sample-ok"},
    )
    assert enrolled.status_code == 200
    policy = client.patch(
        f"/customers/{customer_id}/payment-policy", json={"payment_policy_ok": True}
    )
    assert policy.json()["status"] == "ACTIVE"
    return customer_id


def create_simulated_payment(
    client: TestClient, customer_id: str, session_id: str, method_token: str
) -> dict:
    purchase = client.post(
        "/purchases",
        headers={"Idempotency-Key": f"purchase-{customer_id}"},
        json={
            "customer_id": customer_id,
            "store_id": "STORE-PILOT",
            "session_id": session_id,
            "items": [
                {
                    "sku": "SKU-CAFE",
                    "description": "Cafe",
                    "quantity": 2,
                    "unit_price_cents": 650,
                }
            ],
        },
    ).json()
    return client.post(
        "/payments",
        headers={"Idempotency-Key": f"payment-{customer_id}"},
        json={"purchase_id": purchase["purchase_id"], "method_token": method_token},
    ).json()


def test_complete_local_homologation_journey(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARKET_DATABASE_URL", f"sqlite:///{tmp_path / 'journey.db'}")
    monkeypatch.setenv("MARKET_ENVIRONMENT", "development")
    monkeypatch.setenv("MARKET_SIMULATION_ENABLED", "true")
    get_settings.cache_clear()

    with TestClient(app) as client:
        customer_id = onboard_customer(client, "+5511933333333")
        access = client.post(
            "/simulations/access",
            json={
                "customer_id": customer_id,
                "store_id": "STORE-PILOT",
                "door_id": "DOOR-1",
                "device_id": "DEVICE-1",
                "sample_reference": "sample-ok",
            },
        )
        assert access.status_code == 200
        assert access.json()["authorized"] is True
        assert access.json()["door_opened"] is True

        payment = create_simulated_payment(
            client, customer_id, access.json()["session_id"], "sim_approved_card"
        )
        settled = client.post(f"/simulations/payments/{payment['payment_id']}/settle")

        assert settled.status_code == 200
        assert settled.json()["status"] == "PAID"
        assert client.get(f"/customers/{customer_id}/debts").json() == []


def test_simulated_decline_blocks_access_and_queues_notification(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARKET_DATABASE_URL", f"sqlite:///{tmp_path / 'decline.db'}")
    monkeypatch.setenv("MARKET_ENVIRONMENT", "development")
    monkeypatch.setenv("MARKET_SIMULATION_ENABLED", "true")
    get_settings.cache_clear()

    with TestClient(app) as client:
        customer_id = onboard_customer(client, "+5511922222222")
        payment = create_simulated_payment(client, customer_id, "SES-SIM", "sim_declined_card")

        settled = client.post(f"/simulations/payments/{payment['payment_id']}/settle")

        assert settled.json()["status"] == "DECLINED"
        assert client.get(f"/customers/{customer_id}").json()["payment_policy_ok"] is False
        assert len(client.get(f"/customers/{customer_id}/debts").json()) == 1
        assert len(client.get(f"/customers/{customer_id}/notifications").json()) == 1


def test_simulated_offline_door_fails_closed(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARKET_DATABASE_URL", f"sqlite:///{tmp_path / 'door.db'}")
    monkeypatch.setenv("MARKET_ENVIRONMENT", "development")
    monkeypatch.setenv("MARKET_SIMULATION_ENABLED", "true")
    get_settings.cache_clear()

    with TestClient(app) as client:
        customer_id = onboard_customer(client, "+5511911111111")
        access = client.post(
            "/simulations/access",
            json={
                "customer_id": customer_id,
                "store_id": "STORE-PILOT",
                "door_id": "offline-door",
                "device_id": "DEVICE-1",
                "sample_reference": "sample-ok",
            },
        )

        assert access.status_code == 200
        assert access.json()["authorized"] is False
        assert access.json()["door_opened"] is False
        assert access.json()["reason"] == "DOOR_UNAVAILABLE"
        assert access.json()["session_id"] is None
