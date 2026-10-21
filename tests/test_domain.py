import unittest

from market_api.domain import (
    Consent,
    Customer,
    CustomerStatus,
    OtpChallenge,
    Payment,
    PaymentStatus,
    Purchase,
    PurchaseItem,
    decide_access,
)
from market_api.repository import ConflictError, InMemoryRepository


class CustomerRulesTest(unittest.TestCase):
    def ready_customer(self) -> Customer:
        customer = Customer("Cliente Teste", "+5511999999999")
        customer.consents = [
            Consent("TERMS", "1"),
            Consent("PRIVACY", "1"),
            Consent("BIOMETRICS", "1"),
        ]
        customer.biometric_valid = True
        customer.payment_policy_ok = True
        customer.phone_verified = True
        customer.activate_if_ready()
        return customer

    def test_customer_only_activates_when_onboarding_is_complete(self) -> None:
        customer = Customer("Cliente Teste", "+5511999999999")
        customer.consents = [Consent("TERMS", "1"), Consent("PRIVACY", "1")]
        customer.biometric_valid = True

        customer.activate_if_ready()

        self.assertEqual(CustomerStatus.PENDING, customer.status)

    def test_unverified_phone_prevents_activation(self) -> None:
        customer = self.ready_customer()
        customer.status = CustomerStatus.PENDING
        customer.phone_verified = False

        customer.activate_if_ready()

        self.assertEqual(CustomerStatus.PENDING, customer.status)

    def test_ready_customer_is_authorized(self) -> None:
        decision = decide_access(self.ready_customer())

        self.assertTrue(decision.authorized)
        self.assertEqual("POLICY_OK", decision.reason)

    def test_payment_policy_denies_access(self) -> None:
        customer = self.ready_customer()
        customer.payment_policy_ok = False

        decision = decide_access(customer)

        self.assertFalse(decision.authorized)
        self.assertEqual("PAYMENT_POLICY_NOT_OK", decision.reason)

    def test_blocked_customer_is_denied(self) -> None:
        customer = self.ready_customer()
        customer.status = CustomerStatus.BLOCKED

        self.assertEqual("CUSTOMER_BLOCKED", decide_access(customer).reason)


class RepositoryTest(unittest.TestCase):
    def test_duplicate_phone_is_rejected(self) -> None:
        repository = InMemoryRepository()
        repository.add_customer(Customer("Um", "+5511999999999"))

        with self.assertRaises(ConflictError):
            repository.add_customer(Customer("Dois", "+5511999999999"))


class OtpTest(unittest.TestCase):
    def test_issued_code_can_only_be_used_once(self) -> None:
        challenge, code = OtpChallenge.issue("CUST-1")

        self.assertTrue(challenge.verify(code))
        self.assertFalse(challenge.verify(code))

    def test_wrong_code_counts_as_an_attempt(self) -> None:
        challenge, code = OtpChallenge.issue("CUST-1")
        wrong_code = "000001" if code == "000000" else "000000"

        self.assertFalse(challenge.verify(wrong_code))
        self.assertEqual(1, challenge.attempts)


class CommerceTest(unittest.TestCase):
    def test_purchase_total_is_calculated_in_cents(self) -> None:
        purchase = Purchase(
            customer_id="CUST-1",
            store_id="STORE-1",
            session_id="SES-1",
            items=[PurchaseItem("SKU-1", "Produto", 3, 499)],
            discounts_cents=97,
        )

        self.assertEqual(1497, purchase.subtotal_cents)
        self.assertEqual(1400, purchase.total_cents)

    def test_paid_payment_cannot_regress_to_declined(self) -> None:
        payment = Payment("PUR-1", "CUST-1", 1400, "token-safe")
        payment.request()
        payment.apply_provider_result(PaymentStatus.PAID, "provider-1")

        with self.assertRaises(ValueError):
            payment.apply_provider_result(PaymentStatus.DECLINED, "provider-2")

    def test_declined_payment_can_be_retried(self) -> None:
        payment = Payment("PUR-1", "CUST-1", 1400, "token-safe")
        payment.request()
        payment.apply_provider_result(PaymentStatus.DECLINED, "provider-1", "insufficient")

        payment.request(retry=True)

        self.assertEqual(PaymentStatus.RETRY, payment.status)
        self.assertEqual(2, payment.attempts)


if __name__ == "__main__":
    unittest.main()
