from __future__ import annotations

import httpx

from .delivery import DeliveryResult, PermanentDeliveryError, TransientDeliveryError
from .domain import Notification


class WhatsAppProvider:
    def __init__(
        self,
        *,
        graph_version: str,
        phone_number_id: str,
        access_token: str,
        template_name: str,
        template_language: str,
        timeout_seconds: float = 15,
        client: httpx.Client | None = None,
    ) -> None:
        self.url = f"https://graph.facebook.com/{graph_version}/{phone_number_id}/messages"
        self.access_token = access_token
        self.template_name = template_name
        self.template_language = template_language
        self.client = client or httpx.Client(timeout=timeout_seconds)

    @staticmethod
    def _money(cents: object) -> str:
        value = int(cents)
        return f"R$ {value // 100},{value % 100:02d}"

    def send(self, notification: Notification, destination: str) -> DeliveryResult:
        payment_id = str(notification.data["payment_id"])
        purchase_id = str(notification.data["purchase_id"])
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": destination.removeprefix("+"),
            "type": "template",
            "template": {
                "name": self.template_name,
                "language": {"code": self.template_language},
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": purchase_id},
                            {
                                "type": "text",
                                "text": self._money(notification.data["amount_cents"]),
                            },
                        ],
                    },
                    {
                        "type": "button",
                        "sub_type": "url",
                        "index": "0",
                        "parameters": [{"type": "text", "text": payment_id}],
                    },
                ],
            },
        }
        try:
            response = self.client.post(
                self.url,
                headers={"Authorization": f"Bearer {self.access_token}"},
                json=payload,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TransientDeliveryError("WhatsApp transport unavailable") from exc
        if response.status_code in {408, 429} or response.status_code >= 500:
            raise TransientDeliveryError(
                f"WhatsApp temporary response: HTTP {response.status_code}"
            )
        if response.status_code >= 400:
            raise PermanentDeliveryError(
                f"WhatsApp rejected the message: HTTP {response.status_code}"
            )
        try:
            reference = response.json()["messages"][0]["id"]
        except (KeyError, IndexError, ValueError) as exc:
            raise PermanentDeliveryError("WhatsApp returned an invalid success payload") from exc
        return DeliveryResult(provider_reference=reference)
