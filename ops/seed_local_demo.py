from __future__ import annotations

import argparse
import os
import sys
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from market_api.config import get_settings
from market_api.domain import (
    Customer,
    CustomerStatus,
    Notification,
    NotificationStatus,
    Payment,
    PaymentStatus,
    Purchase,
    PurchaseItem,
    now_utc,
)
from market_api.repository import (
    SqlRepository,
    audit_table,
    customers_table,
    notifications_table,
    payments_table,
    purchases_table,
)


def main() -> None:
    settings = get_settings()
    if settings.environment.lower() != "development":
        raise SystemExit("Demo data can only be added when MARKET_ENVIRONMENT=development.")

    parser = argparse.ArgumentParser(description="Seed synthetic data into a local SQLite database.")
    parser.add_argument(
        "--database-url",
        default=os.getenv("MARKET_DATABASE_URL", "sqlite:///../work/market-local.sqlite3"),
        help="Development SQLite URL. Defaults to the local POC database.",
    )
    args = parser.parse_args()
    if not args.database_url.startswith("sqlite:///"):
        raise SystemExit("Demo data can only be added to SQLite.")

    repo = SqlRepository.connect(
        args.database_url,
        create_schema=True,
        encryption_keys=settings.data_encryption_keys,
    )
    tables = {
        "customers": customers_table,
        "purchases": purchases_table,
        "payments": payments_table,
        "notifications": notifications_table,
        "audit_events": audit_table,
    }
    with repo.engine.connect() as connection:
        existing_counts = {
            name: int(connection.execute(select(func.count()).select_from(table)).scalar_one())
            for name, table in tables.items()
        }
    if any(existing_counts.values()):
        if existing_counts["customers"]:
            with repo.engine.connect() as connection:
                demo_count = int(
                    connection.execute(
                        select(func.count())
                        .select_from(customers_table)
                        .where(customers_table.c.customer_id.like("DEMO-CUST-%"))
                    ).scalar_one()
                )
            if demo_count:
                print("Demo records already exist; no changes made.")
                return
        raise SystemExit(
            "The local database is not empty; refusing to mix demo and existing records: "
            + ", ".join(f"{name}={count}" for name, count in existing_counts.items())
        )

    now = now_utc()
    examples = [
        (PaymentStatus.PAID, 7_850, 1, 0.5),
        (PaymentStatus.PAID, 15_200, 1, 1.0),
        (PaymentStatus.DECLINED, 18_990, 1, 2.0),
        (PaymentStatus.PENDING, 7_450, 1, 1.0),
        (PaymentStatus.RETRY, 12_990, 2, 4.0),
        (PaymentStatus.UNPAID, 3_999, 0, 6.0),
    ]

    for index, (payment_status, amount_cents, attempts, age_days) in enumerate(examples, 1):
        customer_id = f"DEMO-CUST-{index:03d}"
        purchase_id = f"DEMO-PUR-{index:03d}"
        payment_id = f"DEMO-PAY-{index:03d}"
        created_at = now - timedelta(days=age_days)
        updated_at = created_at + timedelta(minutes=15)
        repo.add_customer(
            Customer(
                name=f"Cliente de demonstração {index:02d}",
                phone=f"+1999000000{index:02d}",
                customer_id=customer_id,
                status=CustomerStatus.ACTIVE,
                biometric_ref=f"DEMO-REF-{index:03d}",
                biometric_valid=True,
                payment_policy_ok=True,
                phone_verified=True,
                created_at=created_at,
            )
        )
        repo.add_purchase(
            Purchase(
                customer_id=customer_id,
                store_id="DEMO-STORE",
                session_id=f"DEMO-SESSION-{index:03d}",
                items=[
                    PurchaseItem(
                        sku=f"DEMO-ITEM-{index:03d}",
                        description="Compra sintética para demonstração",
                        quantity=1,
                        unit_price_cents=amount_cents,
                    )
                ],
                purchase_id=purchase_id,
                created_at=created_at,
            ),
            idempotency_key=f"demo-purchase-{index:03d}",
        )
        repo.add_payment(
            Payment(
                purchase_id=purchase_id,
                customer_id=customer_id,
                amount_cents=amount_cents,
                method_token="DEMO-NO-REAL-PAYMENT-CREDENTIAL",
                payment_id=payment_id,
                status=payment_status,
                attempts=attempts,
                provider_reference=f"DEMO-PSP-{index:03d}",
                created_at=created_at,
                updated_at=updated_at,
            ),
            idempotency_key=f"demo-payment-{index:03d}",
        )
        event_type = (
            "PaymentApproved" if payment_status == PaymentStatus.PAID else "DebtRegistered"
        )
        repo.audit(event_type, customer_id, payment_id, simulated=True)

    repo.audit("AccessAuthorized", "DEMO-CUST-001", "DEMO-ACC-001", simulated=True)
    repo.audit("AccessDenied", "DEMO-CUST-006", "DEMO-ACC-002", simulated=True)
    repo.add_notification(
        Notification(
            customer_id="DEMO-CUST-003",
            event_type="DebtRegistered",
            channel="console",
            template="demo_payment_declined",
            data={"payment_id": "DEMO-PAY-003"},
            deduplication_key="demo-notification-001",
            notification_id="DEMO-NTF-001",
            status=NotificationStatus.FAILED,
            attempts=5,
            created_at=now - timedelta(minutes=18),
            next_attempt_at=now,
            last_error="Falha simulada de entrega",
        )
    )
    repo.audit("NotificationFailed", "DEMO-CUST-003", "DEMO-NTF-001", simulated=True)
    print("Added 6 synthetic customers, 6 payments, 4 open debts, 1 failed notification, and sample events.")


if __name__ == "__main__":
    main()
