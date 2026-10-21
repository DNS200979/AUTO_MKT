import hashlib
import hmac

from fastapi.testclient import TestClient

from market_api.config import get_settings
from market_api.main import app


def webhook_signature(event_id: str, payment_id: str, payment_status: str) -> str:
    message = f"{event_id}:{payment_id}:{payment_status}".encode()
    return hmac.new(b"test-secret", message, hashlib.sha256).hexdigest()


def test_decline_notification_regularization_and_access_policy(tmp_path, monkeypatch) -> None:
    database_url = f"sqlite:///{tmp_path / 'debt-flow.db'}"
    monkeypatch.setenv("MARKET_DATABASE_URL", database_url)
    monkeypatch.setenv("MARKET_WEBHOOK_SECRET", "test-secret")
    get_settings.cache_clear()

    with TestClient(app) as client:
        customer = client.post(
            "/customers", json={"name": "Cliente Divida", "phone": "+5511966666666"}
        ).json()
        customer_id = customer["customer_id"]
        client.patch(f"/customers/{customer_id}/payment-policy", json={"payment_policy_ok": True})
        purchase_payload = {
            "customer_id": customer_id,
            "store_id": "STORE-1",
            "session_id": "SES-1",
            "items": [
                {
                    "sku": "SKU-1",
                    "description": "Produto",
                    "quantity": 2,
                    "unit_price_cents": 900,
                }
            ],
        }
        purchase = client.post(
            "/purchases",
            json=purchase_payload,
            headers={"Idempotency-Key": "purchase-debt-flow"},
        ).json()
        payment = client.post(
            "/payments",
            json={"purchase_id": purchase["purchase_id"], "method_token": "tok_original"},
            headers={"Idempotency-Key": "payment-debt-flow"},
        ).json()
        payment_id = payment["payment_id"]

        declined_event = {
            "event_id": "evt-declined-1",
            "payment_id": payment_id,
            "status": "DECLINED",
            "provider_reference": "provider-declined-1",
            "reason": "insufficient_funds",
        }
        signature = webhook_signature("evt-declined-1", payment_id, "DECLINED")
        first = client.post(
            "/webhooks/payment",
            json=declined_event,
            headers={"X-Webhook-Signature": signature},
        )
        duplicate = client.post(
            "/webhooks/payment",
            json=declined_event,
            headers={"X-Webhook-Signature": signature},
        )

        assert first.status_code == 200
        assert duplicate.status_code == 200
        assert client.get(f"/customers/{customer_id}").json()["payment_policy_ok"] is False
        assert len(client.get(f"/customers/{customer_id}/debts").json()) == 1
        assert len(client.get(f"/customers/{customer_id}/notifications").json()) == 1

        regularized = client.post(
            f"/debts/{payment_id}/regularize", json={"method_token": "tok_replacement"}
        )
        assert regularized.json()["status"] == "RETRY"
        assert client.get(f"/customers/{customer_id}").json()["payment_policy_ok"] is False

        paid_event = {
            "event_id": "evt-paid-1",
            "payment_id": payment_id,
            "status": "PAID",
            "provider_reference": "provider-paid-1",
        }
        paid = client.post(
            "/webhooks/payment",
            json=paid_event,
            headers={"X-Webhook-Signature": webhook_signature("evt-paid-1", payment_id, "PAID")},
        )

        assert paid.json()["status"] == "PAID"
        assert client.get(f"/customers/{customer_id}/debts").json() == []
        assert client.get(f"/customers/{customer_id}").json()["payment_policy_ok"] is True
