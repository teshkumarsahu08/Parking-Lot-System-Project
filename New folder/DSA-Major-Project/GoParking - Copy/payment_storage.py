"""Non-destructive SQLite schema updates shared by the app and payment API."""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


PAYMENT_COLUMNS = {
    "event_id": "INTEGER REFERENCES parking_events(id)",
    "amount_paise": "INTEGER",
    "currency": "TEXT NOT NULL DEFAULT 'INR'",
    "payment_status": "TEXT NOT NULL DEFAULT 'RECORDED'",
    "razorpay_order_id": "TEXT",
    "razorpay_payment_id": "TEXT",
    "razorpay_mode": "TEXT",
    "razorpay_key_id": "TEXT",
    "created_at": "TEXT",
    "updated_at": "TEXT"
}


@contextmanager
def payment_db_connection(database_path=None, timeout=5):
    connection = sqlite3.connect(
        database_path or os.environ.get(
            "GOPARKING_DB_PATH", Path(__file__).resolve().parent / "goparking.db"
        ),
        timeout=timeout
    )
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def ensure_payment_schema(connection):
    """Add gateway fields while retaining all existing fee records."""
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(payments)")
    }
    if not columns:
        raise RuntimeError(
            "The payments table is missing. Start the GoParking app once "
            "to initialize its database before starting the payment API."
        )

    for column, declaration in PAYMENT_COLUMNS.items():
        if column not in columns:
            connection.execute(
                f"ALTER TABLE payments ADD COLUMN {column} {declaration}"
            )

    connection.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_event_id
        ON payments(event_id)
    """)
    connection.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_razorpay_order
        ON payments(razorpay_order_id)
    """)
    connection.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_razorpay_payment
        ON payments(razorpay_payment_id)
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS razorpay_payment_capabilities (
            token_hash TEXT PRIMARY KEY,
            payment_id INTEGER NOT NULL REFERENCES payments(id),
            expires_at TEXT NOT NULL
        )
    """)
    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_payment_capabilities_expiry
        ON razorpay_payment_capabilities(payment_id, expires_at)
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS razorpay_webhook_events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            received_at TEXT NOT NULL
        )
    """)
