import hashlib
import hmac
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from market_api.config import get_settings
from market_api.delivery import PermanentDeliveryError, TransientDeliveryError
from market_api.domain import Customer, Notification, NotificationStatus
from market_api.main import app
from market_api.whatsapp import WhatsAppProvider


def notification_fixture() -> Notification:
    return Notification(
        customer_id="CUST-1",
        event_type="PaymentDeclined",
        channel="WHATSAPP",
        template="payment_declined_v1",
        data={"payment_id": "PAY-1", "purchase_id": "PUR-1", "amount_cents": 7240},
        deduplication_key="declined:PAY-1",
    )


def whatsapp_provider_returning(response: httpx.Response) -> WhatsAppProvider:
    return WhatsAppProvider(
        graph_version="v25.0",
        phone_number_id="phone-1",
        access_token="secret-token",
        template_name="payment_declined_v1",
        template_language="pt_BR",
        client=httpx.Client(transport=httpx.MockTransport(lambda request: response)),
    )


def test_whatsapp_provider_sends_approved_template() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"messages": [{"id": "wamid.message-1"}]})

    provider = WhatsAppProvider(
        graph_version="v25.0",
        phone_number_id="phone-1",
        access_token="secret-token",
        template_name="payment_declined_v1",
        template_language="pt_BR",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    notification = Notification(
        customer_id="CUST-1",
        event_type="PaymentDeclined",
        channel="WHATSAPP",
        template="payment_declined_v1",
        data={"payment_id": "PAY-1", "purchase_id": "PUR-1", "amount_cents": 7240},
        deduplication_key="declined:PAY-1",
    )

    result = provider.send(notification, "+5511999999999")

    assert result.provider_reference == "wamid.message-1"
    assert captured["url"] == "https://graph.facebook.com/v25.0/phone-1/messages"
    assert captured["authorization"] == "Bearer secret-token"
    body = captured["body"]
    assert body["to"] == "5511999999999"
    assert body["template"]["components"][0]["parameters"][1]["text"] == "R$ 72,40"


@pytest.mark.parametrize("status_code", [408, 429, 500, 503])
def test_whatsapp_classifies_temporary_responses(status_code: int) -> None:
    provider = whatsapp_provider_returning(httpx.Response(status_code))

    with pytest.raises(TransientDeliveryError):
        provider.send(notification_fixture(), "+5511999999999")


def test_whatsapp_classifies_rejected_message_as_permanent() -> None:
    provider = whatsapp_provider_returning(httpx.Response(400))

    with pytest.raises(PermanentDeliveryError):
        provider.send(notification_fixture(), "+5511999999999")


def test_whatsapp_classifies_timeout_as_transient() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    provider = WhatsAppProvider(
        graph_version="v25.0",
        phone_number_id="phone-1",
        access_token="secret-token",
        template_name="payment_declined_v1",
        template_language="pt_BR",
        client=httpx.Client(transport=httpx.MockTransport(timeout)),
    )

    with pytest.raises(TransientDeliveryError):
        provider.send(notification_fixture(), "+5511999999999")


def test_whatsapp_webhook_verification_and_delivery_status(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MARKET_DATABASE_URL", f"sqlite:///{tmp_path / 'whatsapp.db'}")
    monkeypatch.setenv("MARKET_WHATSAPP_VERIFY_TOKEN", "verify-me")
    monkeypatch.setenv("MARKET_WHATSAPP_APP_SECRET", "app-secret")
    get_settings.cache_clear()

    with TestClient(app) as client:
        verification = client.get(
            "/webhooks/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.challenge": "challenge-123",
                "hub.verify_token": "verify-me",
            },
        )
        assert verification.status_code == 200
        assert verification.text == "challenge-123"

        repository = client.app.state.repository
        customer = repository.add_customer(Customer("WhatsApp Test", "+5511944444444"))
        notification = Notification(
            customer_id=customer.customer_id,
            event_type="PaymentDeclined",
            channel="WHATSAPP",
            template="payment_declined_v1",
            data={},
            deduplication_key="whatsapp-status-test",
            status=NotificationStatus.SENT,
            provider_reference="wamid.message-1",
        )
        repository.add_notification(notification)
        payload = {
            "entry": [
                {
                    "changes": [
                        {"value": {"statuses": [{"id": "wamid.message-1", "status": "delivered"}]}}
                    ]
                }
            ]
        }
        body = json.dumps(payload, separators=(",", ":")).encode()
        signature = "sha256=" + hmac.new(b"app-secret", body, hashlib.sha256).hexdigest()

        response = client.post(
            "/webhooks/whatsapp",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature},
        )

        assert response.status_code == 200
        saved = repository.list_notifications(customer.customer_id)[0]
        assert saved.status == NotificationStatus.DELIVERED
