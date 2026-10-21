from dataclasses import dataclass
from typing import Protocol

from .domain import Notification


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    provider_reference: str


class DeliveryError(RuntimeError):
    """Falha transitoria ou definitiva informada por um adaptador de entrega."""


class TransientDeliveryError(DeliveryError):
    """Falha que pode ser tentada novamente com backoff."""


class PermanentDeliveryError(DeliveryError):
    """Falha que deve seguir diretamente para a dead-letter queue."""


class NotificationProvider(Protocol):
    def send(self, notification: Notification, destination: str) -> DeliveryResult: ...
