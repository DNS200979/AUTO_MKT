from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .domain import Payment, PaymentStatus, new_id


class IntegrationError(RuntimeError):
    """Falha normalizada de uma integracao externa."""


@dataclass(frozen=True, slots=True)
class BiometricEnrollmentResult:
    biometric_ref: str
    liveness_passed: bool


@dataclass(frozen=True, slots=True)
class BiometricVerificationResult:
    matched: bool
    liveness_passed: bool
    confidence: float


class BiometricProvider(Protocol):
    def enroll(self, sample_reference: str) -> BiometricEnrollmentResult: ...

    def verify(self, biometric_ref: str, sample_reference: str) -> BiometricVerificationResult: ...


@dataclass(frozen=True, slots=True)
class DoorOpenResult:
    opened: bool
    provider_reference: str


class DoorController(Protocol):
    def open(self, store_id: str, door_id: str, device_id: str) -> DoorOpenResult: ...


@dataclass(frozen=True, slots=True)
class PaymentResult:
    status: PaymentStatus
    provider_reference: str
    reason: str | None = None


class PaymentProvider(Protocol):
    def charge(self, payment: Payment) -> PaymentResult: ...


class SimulatedBiometricProvider:
    """Simulador deterministico que nunca armazena uma imagem biometrica."""

    def enroll(self, sample_reference: str) -> BiometricEnrollmentResult:
        if sample_reference.startswith("liveness-fail"):
            return BiometricEnrollmentResult("", False)
        return BiometricEnrollmentResult(new_id("BIO"), True)

    def verify(self, biometric_ref: str, sample_reference: str) -> BiometricVerificationResult:
        if sample_reference.startswith("liveness-fail"):
            return BiometricVerificationResult(False, False, 0.0)
        if sample_reference.startswith("no-match"):
            return BiometricVerificationResult(False, True, 0.20)
        confidence = 0.99 if biometric_ref.startswith("BIO-") else 0.90
        return BiometricVerificationResult(True, True, confidence)


class SimulatedDoorController:
    def open(self, store_id: str, door_id: str, device_id: str) -> DoorOpenResult:
        if door_id.startswith("offline") or device_id.startswith("offline"):
            raise IntegrationError("door controller unavailable")
        return DoorOpenResult(True, new_id("DOOR"))


class SimulatedPaymentProvider:
    """O prefixo do token controla o resultado para cenarios de homologacao."""

    def charge(self, payment: Payment) -> PaymentResult:
        if payment.method_token.startswith("sim_declined"):
            return PaymentResult(
                PaymentStatus.DECLINED, new_id("PSP"), "simulated_insufficient_funds"
            )
        if payment.method_token.startswith("sim_pending"):
            return PaymentResult(PaymentStatus.PENDING, new_id("PSP"))
        if payment.method_token.startswith("sim_error"):
            raise IntegrationError("payment provider unavailable")
        return PaymentResult(PaymentStatus.PAID, new_id("PSP"))
