import hashlib
import hmac
import http.client
import json
import os
import tempfile
import unittest
from pathlib import Path
from threading import Thread
from unittest.mock import patch

import payment_api
from payment_storage import ensure_payment_schema


class PaymentStorageMigrationTests(unittest.TestCase):
    def test_migration_preserves_existing_fee_rows_and_is_repeatable(self):
        with payment_api.payment_db_connection(":memory:") as connection:
            connection.execute("""
                CREATE TABLE parking_events (id INTEGER PRIMARY KEY)
            """)
            connection.execute("""
                CREATE TABLE payments (
                    id INTEGER PRIMARY KEY,
                    registration TEXT NOT NULL,
                    amount REAL NOT NULL,
                    paid_at TEXT NOT NULL
                )
            """)
            connection.execute("""
                INSERT INTO payments (registration, amount, paid_at)
                VALUES ('ABC123', 25.0, '2025-01-01T10:00:00')
            """)

            ensure_payment_schema(connection)
            ensure_payment_schema(connection)

            row = connection.execute("""
                SELECT registration, amount, payment_status, currency
                FROM payments WHERE id = 1
            """).fetchone()
            self.assertEqual(row, ("ABC123", 25.0, "RECORDED", "INR"))
            indexes = {
                result[1]
                for result in connection.execute("PRAGMA index_list(payments)")
            }
            self.assertIn("idx_payments_event_id", indexes)
            self.assertIn("idx_payments_razorpay_payment", indexes)


class RazorpayPaymentFlowTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "payments.db"
        self.db_path_patch = patch.object(payment_api, "DB_PATH", self.database_path)
        self.db_path_patch.start()
        self.previous_key_id = os.environ.get("RAZORPAY_KEY_ID")
        self.previous_key_secret = os.environ.get("RAZORPAY_KEY_SECRET")
        self.previous_mode = os.environ.get("GOPARKING_RAZORPAY_MODE")
        os.environ["RAZORPAY_KEY_ID"] = "rzp_test_unit_test"
        os.environ["RAZORPAY_KEY_SECRET"] = "unit_test_secret"
        os.environ["GOPARKING_RAZORPAY_MODE"] = "test"

        with payment_api.payment_db_connection(self.database_path) as connection:
            connection.execute("""
                CREATE TABLE parking_events (id INTEGER PRIMARY KEY)
            """)
            connection.execute("""
                CREATE TABLE payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    registration TEXT NOT NULL,
                    amount REAL NOT NULL,
                    paid_at TEXT NOT NULL,
                    owner_user_id INTEGER
                )
            """)
            ensure_payment_schema(connection)
            token = "a" * 43
            digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
            connection.execute("""
                INSERT INTO payments (
                    registration, amount, paid_at, owner_user_id, event_id,
                    amount_paise, currency, payment_status, created_at,
                    updated_at
                )
                VALUES (
                    'ABC123', 25.0, '2025-01-01T10:00:00', 8, 1,
                    2500, 'INR', 'CREATED', '2025-01-01T10:00:00',
                    '2025-01-01T10:00:00'
                )
            """)
            connection.execute("""
                INSERT INTO payments (
                    registration, amount, paid_at, owner_user_id, event_id,
                    amount_paise, currency, payment_status, created_at,
                    updated_at
                )
                VALUES (
                    'XYZ789', 10.0, '2025-01-01T10:00:00', 9, 2,
                    1000, 'INR', 'CREATED', '2025-01-01T10:00:00',
                    '2025-01-01T10:00:00'
                )
            """)
            connection.executemany("""
                INSERT INTO razorpay_payment_capabilities
                    (token_hash, payment_id, expires_at)
                VALUES (?, ?, '2999-01-01T00:00:00')
            """, (
                (digest, 1),
                (hashlib.sha256(("b" * 43).encode("utf-8")).hexdigest(), 2)
            ))
        self.token = token

    def tearDown(self):
        self.db_path_patch.stop()
        if self.previous_key_id is None:
            os.environ.pop("RAZORPAY_KEY_ID", None)
        else:
            os.environ["RAZORPAY_KEY_ID"] = self.previous_key_id
        if self.previous_key_secret is None:
            os.environ.pop("RAZORPAY_KEY_SECRET", None)
        else:
            os.environ["RAZORPAY_KEY_SECRET"] = self.previous_key_secret
        if self.previous_mode is None:
            os.environ.pop("GOPARKING_RAZORPAY_MODE", None)
        else:
            os.environ["GOPARKING_RAZORPAY_MODE"] = self.previous_mode
        self.temporary_directory.cleanup()

    def test_capability_resolves_only_its_payment(self):
        payment = payment_api.find_payment(self.token)
        self.assertEqual(payment["id"], 1)
        self.assertEqual(payment["amount_paise"], 2500)
        other_payment = payment_api.find_payment("b" * 43)
        self.assertEqual(other_payment["id"], 2)
        self.assertNotEqual(payment["id"], other_payment["id"])
        with self.assertRaises(payment_api.PaymentError) as error:
            payment_api.find_payment("c" * 43)
        self.assertEqual(error.exception.status, 401)

    def test_order_amount_is_from_database_and_order_is_reused(self):
        class OrderResource:
            calls = 0

            def create(self, options):
                self.calls += 1
                self.asserted_options = options
                return {
                    "id": "order_test123",
                    "amount": 2500,
                    "currency": "INR"
                }

        client = type("Client", (), {})()
        client.order = OrderResource()
        with patch.object(payment_api, "payment_client", return_value=client):
            first = payment_api.create_order(payment_api.find_payment(self.token))
            second = payment_api.create_order(payment_api.find_payment(self.token))

        self.assertEqual(first["amount"], 2500)
        self.assertEqual(first["status"], "PENDING")
        self.assertEqual(second["order_id"], "order_test123")
        self.assertEqual(client.order.calls, 1)
        self.assertEqual(client.order.asserted_options["amount"], 2500)
        self.assertEqual(client.order.asserted_options["currency"], "INR")

    def test_created_order_stays_pending_when_payment_is_authorized(self):
        class Utility:
            def verify_payment_signature(self, details):
                return None

        class PaymentResource:
            def fetch(self, payment_id):
                return {
                    "id": payment_id,
                    "order_id": "order_test123",
                    "amount": 2500,
                    "currency": "INR",
                    "status": "authorized"
                }

        client = type("Client", (), {})()
        client.utility = Utility()
        client.payment = PaymentResource()
        payment = payment_api.find_payment(self.token)
        payment["razorpay_order_id"] = "order_test123"
        with payment_api.payment_db_connection(self.database_path) as connection:
            connection.execute(
                "UPDATE payments SET razorpay_order_id = ? WHERE id = 1",
                ("order_test123",)
            )
        with patch.object(payment_api, "payment_client", return_value=client):
            result = payment_api.verify_checkout_payment(payment, {
                "razorpay_order_id": "order_test123",
                "razorpay_payment_id": "pay_test123",
                "razorpay_signature": "f" * 64
            })
        self.assertEqual(result["status"], "PENDING")
        with payment_api.payment_db_connection(self.database_path) as connection:
            status = connection.execute(
                "SELECT payment_status FROM payments WHERE id = 1"
            ).fetchone()[0]
        self.assertEqual(status, "PENDING")

    def test_confirmed_failed_payment_is_not_marked_paid(self):
        class PaymentResource:
            def fetch(self, payment_id):
                return {
                    "id": payment_id,
                    "order_id": "order_test123",
                    "amount": 2500,
                    "currency": "INR",
                    "status": "failed"
                }

        client = type("Client", (), {})()
        client.payment = PaymentResource()
        payment = payment_api.find_payment(self.token)
        payment["razorpay_order_id"] = "order_test123"
        with payment_api.payment_db_connection(self.database_path) as connection:
            connection.execute(
                "UPDATE payments SET razorpay_order_id = ? WHERE id = 1",
                ("order_test123",)
            )
        with patch.object(payment_api, "payment_client", return_value=client):
            result = payment_api.confirm_failed_payment(payment, {
                "razorpay_order_id": "order_test123",
                "razorpay_payment_id": "pay_test123"
            })
        self.assertEqual(result["status"], "FAILED")

    def test_provider_network_error_is_returned_as_a_retryable_failure(self):
        class OrderResource:
            def create(self, options):
                raise OSError("simulated network failure")

        client = type("Client", (), {})()
        client.order = OrderResource()
        with patch.object(payment_api, "payment_client", return_value=client):
            with self.assertRaises(payment_api.PaymentError) as error:
                payment_api.create_order(payment_api.find_payment(self.token))
        self.assertEqual(error.exception.status, 502)
        self.assertIn("try again", error.exception.message)

    def test_http_status_requires_a_payment_capability_and_ignores_foreign_id(self):
        server = payment_api.PaymentHTTPServer(("127.0.0.1", 0),
                                               payment_api.PaymentRequestHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_address[1], timeout=5
            )
            connection.request("GET", "/api/status")
            unauthorized = connection.getresponse()
            unauthorized_body = json.loads(unauthorized.read())
            self.assertEqual(unauthorized.status, 401)
            self.assertIn("token", unauthorized_body["error"])

            connection.request(
                "GET", "/api/status?payment_id=2",
                headers={"Authorization": f"Bearer {self.token}"}
            )
            scoped_response = connection.getresponse()
            scoped_body = json.loads(scoped_response.read())
            self.assertEqual(scoped_response.status, 200)
            self.assertEqual(scoped_body["payment_id"], 1)
            connection.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

    def test_invalid_signature_does_not_mark_payment_paid(self):
        class SignatureVerificationError(Exception):
            pass

        class Utility:
            def verify_payment_signature(self, details):
                raise SignatureVerificationError()

        client = type("Client", (), {})()
        client.utility = Utility()
        payment = payment_api.find_payment(self.token)
        payment["razorpay_order_id"] = "order_test123"
        with payment_api.payment_db_connection(self.database_path) as connection:
            connection.execute(
                "UPDATE payments SET razorpay_order_id = ? WHERE id = 1",
                ("order_test123",)
            )

        with patch.object(payment_api, "payment_client", return_value=client):
            with self.assertRaises(payment_api.PaymentError) as error:
                payment_api.verify_checkout_payment(payment, {
                    "razorpay_order_id": "order_test123",
                    "razorpay_payment_id": "pay_test123",
                    "razorpay_signature": "f" * 64
                })

        self.assertEqual(error.exception.status, 400)
        with payment_api.payment_db_connection(self.database_path) as connection:
            status = connection.execute(
                "SELECT payment_status FROM payments WHERE id = 1"
            ).fetchone()[0]
        self.assertEqual(status, "CREATED")

    def test_amount_mismatch_does_not_mark_payment_paid(self):
        class Utility:
            def verify_payment_signature(self, details):
                return None

        class PaymentResource:
            def fetch(self, payment_id):
                return {
                    "id": payment_id,
                    "order_id": "order_test123",
                    "amount": 2499,
                    "currency": "INR",
                    "status": "captured"
                }

        client = type("Client", (), {})()
        client.utility = Utility()
        client.payment = PaymentResource()
        payment = payment_api.find_payment(self.token)
        payment["razorpay_order_id"] = "order_test123"
        with payment_api.payment_db_connection(self.database_path) as connection:
            connection.execute(
                "UPDATE payments SET razorpay_order_id = ? WHERE id = 1",
                ("order_test123",)
            )

        with patch.object(payment_api, "payment_client", return_value=client):
            with self.assertRaises(payment_api.PaymentError) as error:
                payment_api.verify_checkout_payment(payment, {
                    "razorpay_order_id": "order_test123",
                    "razorpay_payment_id": "pay_test123",
                    "razorpay_signature": "f" * 64
                })
        self.assertEqual(error.exception.status, 400)

    def test_verified_capture_is_idempotent_and_failure_cannot_downgrade_it(self):
        class Utility:
            def verify_payment_signature(self, details):
                return None

        class PaymentResource:
            fetch_calls = 0

            def fetch(self, payment_id):
                self.fetch_calls += 1
                return {
                    "id": payment_id,
                    "order_id": "order_test123",
                    "amount": 2500,
                    "currency": "INR",
                    "status": "captured"
                }

        client = type("Client", (), {})()
        client.utility = Utility()
        client.payment = PaymentResource()
        with payment_api.payment_db_connection(self.database_path) as connection:
            connection.execute("""
                UPDATE payments
                SET razorpay_order_id = 'order_test123', payment_status = 'PENDING'
                WHERE id = 1
            """)

        request = {
            "razorpay_order_id": "order_test123",
            "razorpay_payment_id": "pay_test123",
            "razorpay_signature": "f" * 64
        }
        with patch.object(payment_api, "payment_client", return_value=client):
            first = payment_api.verify_checkout_payment(
                payment_api.find_payment(self.token), request
            )
            second = payment_api.verify_checkout_payment(
                payment_api.find_payment(self.token), request
            )

        self.assertEqual(first["status"], "PAID")
        self.assertEqual(second["status"], "PAID")
        self.assertEqual(client.payment.fetch_calls, 1)
        with self.assertRaises(payment_api.PaymentError):
            payment_api.store_payment_result(
                payment_api.find_payment(self.token), "pay_oldfail", "FAILED"
            )
        with payment_api.payment_db_connection(self.database_path) as connection:
            stored = connection.execute("""
                SELECT payment_status, razorpay_payment_id
                FROM payments WHERE id = 1
            """).fetchone()
        self.assertEqual(stored, ("PAID", "pay_test123"))

    def test_webhook_signature_and_duplicate_event_handling(self):
        raw_body = json.dumps({
            "event": "payment.captured",
            "payload": {"payment": {"entity": {
                "id": "pay_test123",
                "order_id": "order_test123",
                "amount": 2500,
                "currency": "INR"
            }}}
        }).encode("utf-8")
        secret = "webhook_test_secret"
        signature = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        self.assertTrue(payment_api.webhook_signature_is_valid(
            raw_body, signature, secret
        ))
        self.assertFalse(payment_api.webhook_signature_is_valid(
            raw_body, "0" * 64, secret
        ))

        with payment_api.payment_db_connection(self.database_path) as connection:
            connection.execute("""
                UPDATE payments
                SET razorpay_order_id = 'order_test123', payment_status = 'PENDING'
                WHERE id = 1
            """)
        payload = json.loads(raw_body)
        first = payment_api.process_webhook(raw_body, "event_test1", payload)
        duplicate = payment_api.process_webhook(raw_body, "event_test1", payload)
        self.assertEqual(first, {"duplicate": False, "processed": True})
        self.assertEqual(duplicate, {"duplicate": True, "processed": False})
        with payment_api.payment_db_connection(self.database_path) as connection:
            status = connection.execute(
                "SELECT payment_status FROM payments WHERE id = 1"
            ).fetchone()[0]
        self.assertEqual(status, "PAID")

    def test_webhook_wrong_amount_does_not_update_payment(self):
        payload = {
            "event": "payment.captured",
            "payload": {"payment": {"entity": {
                "id": "pay_test123",
                "order_id": "order_test123",
                "amount": 2499,
                "currency": "INR"
            }}}
        }
        with payment_api.payment_db_connection(self.database_path) as connection:
            connection.execute("""
                UPDATE payments
                SET razorpay_order_id = 'order_test123', payment_status = 'PENDING'
                WHERE id = 1
            """)
        result = payment_api.process_webhook(
            json.dumps(payload).encode("utf-8"), "event_test2", payload
        )
        self.assertEqual(result, {"duplicate": False, "processed": False})
        with payment_api.payment_db_connection(self.database_path) as connection:
            status = connection.execute(
                "SELECT payment_status FROM payments WHERE id = 1"
            ).fetchone()[0]
        self.assertEqual(status, "PENDING")


if __name__ == "__main__":
    unittest.main()
