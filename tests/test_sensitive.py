from datetime import timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import insert, select

from market_api.config import get_settings
from market_api.domain import (
    Customer,
    Notification,
    Payment,
    PaymentStatus,
    Purchase,
    PurchaseItem,
    now_utc,
)
from market_api.repository import (
    SqlRepository,
    customers_table,
    payments_table,
    webhook_events_table,
)
from market_api.secrets import SecretProviderError
from market_api.sensitive import DataCipher, SensitiveDataError


def repository_with_payment(
    database_url: str, keys: dict[str, str]
) -> tuple[SqlRepository, str, str]:
    repository = SqlRepository.connect(database_url, encryption_keys=keys)
    customer = repository.add_customer(Customer("Cliente Seguro", "+5511833333333"))
    customer.biometric_ref = "biometric-provider-reference"
    repository.save_customer(customer)
    purchase = repository.add_purchase(
        Purchase(
            customer_id=customer.customer_id,
            store_id="STORE-1",
            session_id="SES-1",
            items=[PurchaseItem("SKU-1", "Produto", 1, 1000)],
        ),
        "sensitive-purchase",
    )
    payment = repository.add_payment(
        Payment(purchase.purchase_id, customer.customer_id, 1000, "payment-token-secret"),
        "sensitive-payment",
    )
    return repository, customer.customer_id, payment.payment_id


def test_sensitive_fields_are_encrypted_at_rest_and_decrypted_on_read(tmp_path) -> None:
    key = Fernet.generate_key().decode()
    repository, customer_id, payment_id = repository_with_payment(
        f"sqlite:///{tmp_path / 'encrypted.db'}", {"key-2026": key}
    )

    with repository.engine.connect() as connection:
        raw_biometric = connection.execute(
            select(customers_table.c.biometric_ref).where(
                customers_table.c.customer_id == customer_id
            )
        ).scalar_one()
        raw_token = connection.execute(
            select(payments_table.c.method_token).where(payments_table.c.payment_id == payment_id)
        ).scalar_one()

    assert raw_biometric.startswith("enc:v1:key-2026:")
    assert raw_token.startswith("enc:v1:key-2026:")
    assert "biometric-provider-reference" not in raw_biometric
    assert "payment-token-secret" not in raw_token
    assert repository.get_customer(customer_id).biometric_ref == "biometric-provider-reference"
    assert repository.get_payment(payment_id).method_token == "payment-token-secret"


def test_key_rotation_reencrypts_legacy_and_old_key_data(tmp_path) -> None:
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    database_url = f"sqlite:///{tmp_path / 'rotation.db'}"
    _, customer_id, payment_id = repository_with_payment(database_url, {"old": old_key})
    rotating = SqlRepository.connect(database_url, encryption_keys={"new": new_key, "old": old_key})

    assert rotating.sensitive_data_inventory() == {"old": 2}

    result = rotating.rotate_sensitive_data()

    assert result == {"customers": 1, "payments": 1}
    with rotating.engine.connect() as connection:
        raw_biometric = connection.execute(
            select(customers_table.c.biometric_ref).where(
                customers_table.c.customer_id == customer_id
            )
        ).scalar_one()
        raw_token = connection.execute(
            select(payments_table.c.method_token).where(payments_table.c.payment_id == payment_id)
        ).scalar_one()
    assert raw_biometric.startswith("enc:v1:new:")
    assert raw_token.startswith("enc:v1:new:")
    assert rotating.get_payment(payment_id).method_token == "payment-token-secret"
    assert rotating.sensitive_data_inventory() == {"new": 2}


def test_settings_load_allowlisted_secrets_from_mounted_json(tmp_path, monkeypatch) -> None:
    key = Fernet.generate_key().decode()
    secret_file = tmp_path / "market-secrets.json"
    secret_file.write_text(
        '{"data_encryption_keys":{"mounted":"' + key + '"},'
        '"webhook_secret":"mounted-webhook"}',
        encoding="utf-8",
    )
    monkeypatch.setenv("MARKET_SECRETS_FILE", str(secret_file))
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.data_encryption_keys == {"mounted": key}
    assert settings.webhook_secret == "mounted-webhook"
    get_settings.cache_clear()


def test_settings_reject_unknown_secret_fields(tmp_path, monkeypatch) -> None:
    secret_file = tmp_path / "market-secrets.json"
    secret_file.write_text('{"database_url":"sqlite:///unexpected.db"}', encoding="utf-8")
    monkeypatch.setenv("MARKET_SECRETS_FILE", str(secret_file))
    get_settings.cache_clear()

    with pytest.raises(SecretProviderError, match="unsupported secrets"):
        get_settings()
    get_settings.cache_clear()


def test_unknown_or_tampered_envelope_is_rejected() -> None:
    cipher = DataCipher({"active": Fernet.generate_key().decode()})

    with pytest.raises(SensitiveDataError):
        cipher.decrypt("enc:v1:unknown:not-a-valid-token")


def test_retention_removes_only_expired_operational_records(tmp_path) -> None:
    repository = SqlRepository.connect(f"sqlite:///{tmp_path / 'retention.db'}")
    customer = repository.add_customer(Customer("Cliente Retencao", "+5511822222222"))
    old = now_utc() - timedelta(days=100)
    with repository.engine.begin() as connection:
        connection.execute(
            insert(webhook_events_table).values(event_id="old-event", received_at=old)
        )

    deleted = repository.purge_operational_data(now_utc() - timedelta(days=90))

    assert deleted["webhook_events"] == 1
    assert repository.get_customer(customer.customer_id).name == "Cliente Retencao"


def test_anonymization_scrubs_contact_biometric_payment_and_notification_data(tmp_path) -> None:
    key = Fernet.generate_key().decode()
    repository, customer_id, payment_id = repository_with_payment(
        f"sqlite:///{tmp_path / 'anonymize.db'}", {"active": key}
    )
    repository.add_notification(
        Notification(
            customer_id=customer_id,
            event_type="PaymentDeclined",
            channel="WHATSAPP",
            template="payment_declined_v1",
            data={"payment_id": payment_id, "amount_cents": 1000},
            deduplication_key="anonymize-notification",
        )
    )
    payment = repository.get_payment(payment_id)
    payment.status = PaymentStatus.PAID
    repository.save_payment(payment)

    repository.anonymize_customer(customer_id)

    customer = repository.get_customer(customer_id)
    assert customer.name == "ANONYMIZED"
    assert customer.phone.startswith("+999")
    assert customer.email is None
    assert customer.biometric_ref is None
    assert repository.get_payment(payment_id).method_token == "REDACTED"
    assert repository.list_notifications(customer_id)[0].data == {}
