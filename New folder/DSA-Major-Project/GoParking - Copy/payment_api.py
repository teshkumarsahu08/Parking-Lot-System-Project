"""Razorpay Checkout and webhook API for the GoParking Streamlit application."""

import hashlib
import hmac
import html
import json
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from payment_storage import ensure_payment_schema, payment_db_connection


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("GOPARKING_DB_PATH", BASE_DIR / "goparking.db"))
API_URL = os.environ.get(
    "GOPARKING_PAYMENT_API_URL", "http://127.0.0.1:8765"
).rstrip("/")
APP_URL = os.environ.get("GOPARKING_APP_URL", "http://localhost:8501")
MAX_BODY_BYTES = 16_384
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
SIGNATURE_PATTERN = re.compile(r"^[a-fA-F0-9]{64}$")
LOGGER = logging.getLogger("goparking.payment_api")
_RATE_LOCK = threading.Lock()
_RATE_BUCKETS = defaultdict(deque)
_ORDER_LOCKS = {}
_ORDER_LOCKS_GUARD = threading.Lock()


class PaymentError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def initialize_database():
    with payment_db_connection(DB_PATH, timeout=5) as connection:
        ensure_payment_schema(connection)


def razorpay_credentials():
    key_id = os.environ.get("RAZORPAY_KEY_ID", "").strip()
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "").strip()
    mode = os.environ.get("GOPARKING_RAZORPAY_MODE", "test").strip().lower()
    if not key_id or not key_secret:
        raise PaymentError(
            503,
            "Razorpay API credentials are not configured on the server."
        )
    if mode not in {"test", "live"}:
        raise PaymentError(503, "GOPARKING_RAZORPAY_MODE must be test or live.")
    expected_prefix = "rzp_test_" if mode == "test" else "rzp_live_"
    if not key_id.startswith(expected_prefix):
        raise PaymentError(
            503, f"The configured Razorpay key does not match {mode} mode."
        )
    return key_id, key_secret, mode


def payment_client():
    key_id, key_secret, _ = razorpay_credentials()
    try:
        import requests
        import razorpay
    except ImportError as exc:
        raise PaymentError(
            503, "Install the project dependencies before starting payments."
        ) from exc

    class RequestTimeoutSession(requests.Session):
        def request(self, method, url, **kwargs):
            kwargs.setdefault("timeout", (3.05, 15))
            return super().request(method, url, **kwargs)

    return razorpay.Client(
        session=RequestTimeoutSession(), auth=(key_id, key_secret)
    )


@contextmanager
def payment_client_context():
    client = payment_client()
    try:
        yield client
    finally:
        session = getattr(client, "session", None)
        close_session = getattr(session, "close", None)
        if callable(close_session):
            close_session()


def token_digest(token):
    if not isinstance(token, str) or not TOKEN_PATTERN.fullmatch(token):
        raise PaymentError(401, "This payment link is invalid or has expired.")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def find_payment(token):
    digest = token_digest(token)
    with payment_db_connection(DB_PATH, timeout=5) as connection:
        connection.row_factory = sqlite3.Row
        payment = connection.execute("""
            SELECT p.id, p.event_id, p.owner_user_id, p.amount_paise, p.currency,
                   p.payment_status, p.razorpay_order_id, p.razorpay_payment_id,
                   p.razorpay_mode, p.razorpay_key_id
            FROM payments p
            JOIN razorpay_payment_capabilities c ON c.payment_id = p.id
            WHERE c.token_hash = ? AND c.expires_at > ?
        """, (digest, datetime.now().isoformat(timespec="seconds"))).fetchone()
    if payment is None:
        raise PaymentError(401, "This payment link is invalid or has expired.")
    if payment["event_id"] is None or payment["amount_paise"] is None:
        raise PaymentError(409, "This fee is not available for online payment.")
    return dict(payment)


def get_order_lock(payment_id):
    with _ORDER_LOCKS_GUARD:
        return _ORDER_LOCKS.setdefault(payment_id, threading.Lock())


def validate_payment_entity(payment, entity):
    if not isinstance(entity, dict):
        raise PaymentError(400, "Razorpay returned an invalid payment.")
    if entity.get("order_id") != payment["razorpay_order_id"]:
        raise PaymentError(400, "The payment does not belong to this order.")
    if type(entity.get("amount")) is not int:
        raise PaymentError(400, "Razorpay returned an invalid payment amount.")
    if entity["amount"] != payment["amount_paise"]:
        raise PaymentError(400, "The payment amount does not match this fee.")
    if entity.get("currency") != payment["currency"]:
        raise PaymentError(400, "The payment currency does not match this fee.")


def create_order(payment):
    lock = get_order_lock(payment["id"])
    with lock:
        payment = find_payment_by_id(payment["id"])
        if payment["payment_status"] == "PAID":
            raise PaymentError(409, "This fee has already been paid.")
        if payment["razorpay_order_id"]:
            key_id, _, mode = razorpay_credentials()
            if (
                payment["razorpay_mode"] != mode
                or payment["razorpay_key_id"] != key_id
            ):
                raise PaymentError(
                    409,
                    "This order belongs to different Razorpay credentials. "
                    "Contact the parking administrator."
                )
            with payment_db_connection(DB_PATH, timeout=5) as connection:
                connection.execute("""
                    UPDATE payments
                    SET payment_status = 'PENDING', updated_at = ?
                    WHERE id = ? AND payment_status = 'FAILED'
                """, (utc_now(), payment["id"]))
            payment["payment_status"] = "PENDING"
            return order_response(payment)

        with payment_client_context() as client:
            try:
                order = client.order.create({
                    "amount": payment["amount_paise"],
                    "currency": payment["currency"],
                    "receipt": f"goparking_{payment['id']}",
                    "notes": {"goparking_payment_id": str(payment["id"])}
                })
            except Exception as exc:
                LOGGER.warning(
                    "Razorpay order creation failed (%s)", type(exc).__name__
                )
                raise PaymentError(
                    502, "Razorpay could not create the order. Please try again."
                ) from exc

        order_id = order.get("id") if isinstance(order, dict) else None
        if (
            not isinstance(order_id, str)
            or not IDENTIFIER_PATTERN.fullmatch(order_id)
            or order.get("amount") != payment["amount_paise"]
            or order.get("currency") != payment["currency"]
        ):
            LOGGER.error("Razorpay returned an incomplete or mismatched order.")
            raise PaymentError(502, "Razorpay returned an invalid order.")

        with payment_db_connection(DB_PATH, timeout=5) as connection:
            connection.execute("""
                UPDATE payments
                SET razorpay_order_id = ?, razorpay_mode = ?, razorpay_key_id = ?,
                    payment_status = 'PENDING', updated_at = ?
                WHERE id = ? AND payment_status != 'PAID'
            """, (
                order_id,
                os.environ.get("GOPARKING_RAZORPAY_MODE", "test").strip().lower(),
                os.environ["RAZORPAY_KEY_ID"].strip(),
                utc_now(),
                payment["id"]
            ))
        payment["razorpay_order_id"] = order_id
        payment["razorpay_mode"] = os.environ.get(
            "GOPARKING_RAZORPAY_MODE", "test"
        ).strip().lower()
        payment["razorpay_key_id"] = os.environ["RAZORPAY_KEY_ID"].strip()
        payment["payment_status"] = "PENDING"
        return order_response(payment)


def find_payment_by_id(payment_id):
    with payment_db_connection(DB_PATH, timeout=5) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("""
            SELECT id, event_id, owner_user_id, amount_paise, currency,
                   payment_status, razorpay_order_id, razorpay_payment_id,
                   razorpay_mode, razorpay_key_id
            FROM payments WHERE id = ?
        """, (payment_id,)).fetchone()
    if row is None:
        raise PaymentError(404, "Payment record was not found.")
    return dict(row)


def order_response(payment):
    return {
        "payment_id": payment["id"],
        "order_id": payment["razorpay_order_id"],
        "amount": payment["amount_paise"],
        "currency": payment["currency"],
        "key_id": payment["razorpay_key_id"],
        "status": payment["payment_status"]
    }


def verify_checkout_payment(payment, body):
    order_id = body.get("razorpay_order_id")
    payment_id = body.get("razorpay_payment_id")
    signature = body.get("razorpay_signature")
    if (
        not isinstance(order_id, str)
        or not IDENTIFIER_PATTERN.fullmatch(order_id)
        or not isinstance(payment_id, str)
        or not IDENTIFIER_PATTERN.fullmatch(payment_id)
        or not isinstance(signature, str)
        or not SIGNATURE_PATTERN.fullmatch(signature)
    ):
        raise PaymentError(400, "The payment verification details are invalid.")
    if order_id != payment["razorpay_order_id"]:
        raise PaymentError(400, "The payment does not belong to this order.")
    with payment_client_context() as client:
        try:
            client.utility.verify_payment_signature({
                "razorpay_order_id": order_id,
                "razorpay_payment_id": payment_id,
                "razorpay_signature": signature
            })
        except Exception as exc:
            if type(exc).__name__ == "SignatureVerificationError":
                raise PaymentError(400, "The payment signature is invalid.") from exc
            LOGGER.warning(
                "Razorpay payment verification failed (%s)", type(exc).__name__
            )
            raise PaymentError(
                502,
                "Razorpay could not confirm the payment. Please retry verification."
            ) from exc

        if payment["payment_status"] == "PAID":
            if payment_id == payment["razorpay_payment_id"]:
                return {"status": "PAID", "message": "Payment verified."}
            raise PaymentError(409, "This fee has already been paid.")

        try:
            entity = client.payment.fetch(payment_id)
        except Exception as exc:
            LOGGER.warning(
                "Razorpay payment lookup failed (%s)", type(exc).__name__
            )
            raise PaymentError(
                502,
                "Razorpay could not confirm the payment. Please retry verification."
            ) from exc
    if not isinstance(entity, dict) or entity.get("id") != payment_id:
        raise PaymentError(400, "Razorpay returned a different payment.")
    validate_payment_entity(payment, entity)
    provider_status = entity.get("status")
    if provider_status == "captured":
        status = "PAID"
        message = "Payment verified successfully."
    elif provider_status == "failed":
        status = "FAILED"
        message = "Razorpay confirmed that the payment failed."
    else:
        status = "PENDING"
        message = "Payment is authorized and awaiting capture confirmation."

    store_payment_result(payment, payment_id, status)
    return {"status": status, "message": message}


def confirm_failed_payment(payment, body):
    payment_id = body.get("razorpay_payment_id")
    order_id = body.get("razorpay_order_id")
    if (
        not isinstance(payment_id, str)
        or not IDENTIFIER_PATTERN.fullmatch(payment_id)
        or order_id != payment["razorpay_order_id"]
    ):
        raise PaymentError(400, "The payment details are invalid.")
    with payment_client_context() as client:
        try:
            entity = client.payment.fetch(payment_id)
        except Exception as exc:
            LOGGER.warning(
                "Razorpay failure lookup failed (%s)", type(exc).__name__
            )
            raise PaymentError(
                502, "Razorpay could not confirm the payment status."
            ) from exc
    if not isinstance(entity, dict) or entity.get("id") != payment_id:
        raise PaymentError(400, "Razorpay returned a different payment.")
    validate_payment_entity(payment, entity)
    if entity.get("status") != "failed":
        return {"status": payment["payment_status"], "message": "Payment status checked."}
    store_payment_result(payment, payment_id, "FAILED")
    return {"status": "FAILED", "message": "Payment failed. You can retry."}


def store_payment_result(payment, payment_id, status):
    with payment_db_connection(DB_PATH, timeout=5) as connection:
        connection.execute("BEGIN IMMEDIATE")
        current = connection.execute(
            "SELECT payment_status, razorpay_payment_id FROM payments WHERE id = ?",
            (payment["id"],)
        ).fetchone()
        if current is None:
            raise PaymentError(404, "Payment record was not found.")
        if current[0] == "PAID" and current[1] != payment_id:
            raise PaymentError(409, "This fee has already been paid.")
        if current[0] != "PAID" or status == "PAID":
            connection.execute("""
                UPDATE payments
                SET payment_status = ?, razorpay_payment_id = ?, updated_at = ?
                WHERE id = ?
            """, (status, payment_id, utc_now(), payment["id"]))


def webhook_signature_is_valid(raw_body, signature, secret):
    if not isinstance(signature, str) or not SIGNATURE_PATTERN.fullmatch(signature):
        return False
    expected = hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature.lower())


def process_webhook(raw_body, event_id, payload):
    event_type = payload.get("event")
    if not isinstance(event_id, str) or not IDENTIFIER_PATTERN.fullmatch(event_id):
        raise PaymentError(400, "A valid Razorpay webhook event ID is required.")
    if not isinstance(event_type, str):
        raise PaymentError(400, "The Razorpay webhook event is invalid.")

    event_payload = payload.get("payload")
    payment_payload = (
        event_payload.get("payment")
        if isinstance(event_payload, dict) else None
    )
    payment_entity = (
        payment_payload.get("entity")
        if isinstance(payment_payload, dict) else None
    )
    if event_type not in {"payment.captured", "payment.failed"}:
        payment_entity = None
    with payment_db_connection(DB_PATH, timeout=5) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute("""
                INSERT INTO razorpay_webhook_events (event_id, event_type, received_at)
                VALUES (?, ?, ?)
            """, (event_id, event_type, utc_now()))
        except sqlite3.IntegrityError:
            return {"duplicate": True, "processed": False}

        processed = False
        if isinstance(payment_entity, dict):
            order_id = payment_entity.get("order_id")
            row = connection.execute("""
                SELECT id, amount_paise, currency, payment_status,
                       razorpay_payment_id
                FROM payments WHERE razorpay_order_id = ?
            """, (order_id,)).fetchone()
            payment_provider_id = payment_entity.get("id")
            if (
                row is not None
                and isinstance(payment_provider_id, str)
                and IDENTIFIER_PATTERN.fullmatch(payment_provider_id)
                and type(payment_entity.get("amount")) is int
                and payment_entity["amount"] == row["amount_paise"]
                and payment_entity.get("currency") == row["currency"]
            ):
                status = (
                    "PAID" if event_type == "payment.captured" else "FAILED"
                )
                conflicting_capture = (
                    row["payment_status"] == "PAID"
                    and status == "PAID"
                    and row["razorpay_payment_id"] != payment_provider_id
                )
                if not conflicting_capture and (
                    row["payment_status"] != "PAID" or status == "PAID"
                ):
                    connection.execute("""
                        UPDATE payments
                        SET payment_status = ?, razorpay_payment_id = ?, updated_at = ?
                        WHERE id = ?
                    """, (
                        status, payment_provider_id, utc_now(), row["id"]
                    ))
                processed = not conflicting_capture
    return {"duplicate": False, "processed": processed}


CHECKOUT_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="referrer" content="no-referrer">
  <title>GoParking payment</title>
  <script src="https://checkout.razorpay.com/v1/checkout.js"></script>
  <style>
    :root { color-scheme: light; font-family: system-ui, sans-serif; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center;
      background: #eef4f8; color: #18324a; }
    main { width: min(92vw, 480px); box-sizing: border-box; padding: 32px;
      border-radius: 20px; background: white; box-shadow: 0 16px 50px #16324a20; }
    h1 { margin: 0 0 8px; font-size: 1.6rem; }
    p { line-height: 1.5; color: #536579; }
    #amount { margin: 22px 0; font-size: 2rem; font-weight: 700; color: #102c46; }
    button, a { display: inline-block; border: 0; border-radius: 10px;
      padding: 13px 18px; font: inherit; text-decoration: none; cursor: pointer; }
    button { background: #0876bd; color: white; font-weight: 650; }
    button:disabled { opacity: .55; cursor: wait; }
    a { margin-left: 8px; color: #0876bd; }
    #message { min-height: 3em; }
    .error { color: #a32626; }
    .success { color: #176b3a; }
  </style>
</head>
<body>
  <main>
    <h1>GoParking payment</h1>
    <p id="message" role="status" aria-live="polite">Preparing your secure checkout…</p>
    <div id="amount"></div>
    <button id="pay" disabled>Open Razorpay Checkout</button>
    <button id="retry-order" hidden>Retry connection</button>
    <button id="retry-verify" hidden>Retry verification</button>
    <button id="refresh" hidden>Refresh payment status</button>
    <p><a id="return" href="APP_URL_HTML">Return to GoParking</a></p>
  </main>
  <script>
    const token = window.location.hash.slice(1);
    history.replaceState(null, "", window.location.pathname);
    const message = document.getElementById("message");
    const payButton = document.getElementById("pay");
    const retryOrderButton = document.getElementById("retry-order");
    const retryButton = document.getElementById("retry-verify");
    const refreshButton = document.getElementById("refresh");
    let order = null;
    let pendingVerification = null;

    document.getElementById("return").href = APP_URL_JS;
    function show(text, kind) {
      message.textContent = text;
      message.className = kind || "";
    }
    async function request(path, data) {
      const response = await fetch(path, {
        method: data === undefined ? "GET" : "POST",
        headers: { "Authorization": "Bearer " + token,
          ...(data === undefined ? {} : {"Content-Type": "application/json"}) },
        ...(data === undefined ? {} : {body: JSON.stringify(data)})
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "The payment service returned an error.");
      return result;
    }
    function currency(amount, code) {
      return new Intl.NumberFormat("en-IN", {style: "currency", currency: code})
        .format(amount / 100);
    }
    async function prepare() {
      if (!token) throw new Error("This payment link is missing its access token.");
      order = await request("/api/orders", {});
      retryOrderButton.hidden = true;
      document.getElementById("amount").textContent =
        currency(order.amount, order.currency);
      if (order.status === "PAID") {
        show("This fee has already been paid and verified.", "success");
        refreshButton.hidden = false;
        return;
      }
      payButton.disabled = false;
      show("Your fee is ready. Continue to Razorpay's secure checkout.");
    }
    async function verify(details) {
      pendingVerification = details;
      show("Payment submitted. Verifying it securely with the server…");
      retryButton.hidden = true;
      try {
        const result = await request("/api/verify", details);
        if (result.status === "PAID") {
          show("Payment verified successfully. Thank you!", "success");
        } else if (result.status === "FAILED") {
          show("Razorpay confirmed that this payment failed. You can retry.", "error");
          payButton.disabled = false;
        } else {
          show("Payment is still pending confirmation. Refresh status shortly.");
          refreshButton.hidden = false;
        }
        pendingVerification = null;
      } catch (error) {
        show(error.message + " Do not pay again until you refresh the status.", "error");
        retryButton.hidden = false;
      }
      refreshButton.hidden = false;
    }
    payButton.addEventListener("click", () => {
      if (!order) return;
      if (typeof Razorpay !== "function") {
        show("Razorpay Checkout did not load. Check your connection and retry.", "error");
        return;
      }
      payButton.disabled = true;
      show("Opening Razorpay Checkout…");
      try {
        const checkout = new Razorpay({
          key: order.key_id,
          amount: order.amount,
          currency: order.currency,
          order_id: order.order_id,
          name: "GoParking",
          description: "Parking fee",
          handler: response => verify({
            razorpay_order_id: response.razorpay_order_id,
            razorpay_payment_id: response.razorpay_payment_id,
            razorpay_signature: response.razorpay_signature
          }),
          modal: { ondismiss: () => {
            show("Checkout was closed. No successful payment has been recorded.");
            payButton.disabled = false;
          }},
          theme: {color: "#0876bd"}
        });
        checkout.on("payment.failed", response => {
          show("Razorpay reported a failed attempt. Checking its status…", "error");
          const error = response.error || {};
          request("/api/failed", {
            razorpay_order_id: error.metadata && error.metadata.order_id,
            razorpay_payment_id: error.metadata && error.metadata.payment_id
          }).then(result => {
            show(result.status === "FAILED"
              ? "Payment failed. You can try again."
              : "The payment is not confirmed as failed or successful yet.",
              result.status === "FAILED" ? "error" : "");
            payButton.disabled = false;
            refreshButton.hidden = false;
          }).catch(() => {
            show("The failure status could not be checked. Refresh status before retrying.", "error");
            refreshButton.hidden = false;
          });
        });
        checkout.open();
      } catch (error) {
        show("Razorpay Checkout could not open. Check your connection and retry.", "error");
        payButton.disabled = false;
      }
    });
    retryButton.addEventListener("click", () => {
      if (pendingVerification) verify(pendingVerification);
    });
    retryOrderButton.addEventListener("click", () => {
      retryOrderButton.disabled = true;
      prepare().catch(error => show(error.message, "error")).finally(() => {
        retryOrderButton.disabled = false;
      });
    });
    refreshButton.addEventListener("click", async () => {
      try {
        const result = await request("/api/status");
        if (result.status === "PAID") {
          show("Current payment status: PAID. The payment is verified.", "success");
          payButton.disabled = true;
        } else if (result.status === "FAILED") {
          show("The last payment attempt failed. You can try again.", "error");
          payButton.disabled = false;
        } else {
          show("Current payment status: " + result.status +
            ". Check again before retrying.");
        }
      } catch (error) {
        show(error.message, "error");
      }
    });
    prepare().catch(error => {
      show(error.message, "error");
      retryOrderButton.hidden = false;
    });
  </script>
</body>
</html>"""


class PaymentRequestHandler(BaseHTTPRequestHandler):
    server_version = "GoParkingPayments"

    def log_message(self, format_string, *args):
        LOGGER.info("Payment API request: %s", args[0] if args else "")

    def send_bytes(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status, result):
        self.send_bytes(
            status,
            json.dumps(result, separators=(",", ":")).encode("utf-8"),
            "application/json; charset=utf-8"
        )

    def check_rate_limit(self, limit=30):
        key = (self.client_address[0], urlsplit(self.path).path)
        now = time.monotonic()
        with _RATE_LOCK:
            requests = _RATE_BUCKETS[key]
            while requests and requests[0] <= now - 60:
                requests.popleft()
            if len(requests) >= limit:
                raise PaymentError(429, "Too many requests. Please wait and retry.")
            requests.append(now)

    def check_origin(self):
        origin = self.headers.get("Origin")
        if origin and origin.rstrip("/") != API_URL:
            raise PaymentError(403, "The request origin is not allowed.")

    def read_json(self):
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip()
        if content_type != "application/json":
            raise PaymentError(415, "A JSON request body is required.")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise PaymentError(400, "The request length is invalid.") from exc
        if length < 0 or length > MAX_BODY_BYTES:
            raise PaymentError(413, "The request body is too large.")
        try:
            payload = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise PaymentError(400, "The request body is invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise PaymentError(400, "A JSON object is required.")
        return payload

    def get_token(self):
        authorization = self.headers.get("Authorization", "")
        scheme, separator, token = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer":
            raise PaymentError(401, "A valid payment access token is required.")
        return token

    def handle_request(self, callback):
        try:
            self.check_rate_limit(120 if self.path == "/api/webhooks/razorpay" else 30)
            callback()
        except PaymentError as exc:
            self.send_json(exc.status, {"error": exc.message})
        except sqlite3.Error as exc:
            LOGGER.error("SQLite failure in payment API (%s)", type(exc).__name__)
            self.send_json(503, {"error": "Payment records are temporarily unavailable."})
        except Exception as exc:
            LOGGER.error("Unexpected payment API failure (%s)", type(exc).__name__)
            self.send_json(500, {"error": "The payment request could not be completed."})

    def do_GET(self):
        def route():
            path = urlsplit(self.path).path
            if path == "/health":
                configured = bool(
                    os.environ.get("RAZORPAY_KEY_ID")
                    and os.environ.get("RAZORPAY_KEY_SECRET")
                )
                self.send_json(200, {
                    "status": "ok",
                    "payments_configured": configured
                })
                return
            if path == "/checkout":
                app_url_json = json.dumps(APP_URL).replace("</", "<\\/")
                page = (
                    CHECKOUT_HTML
                    .replace("APP_URL_HTML", html.escape(APP_URL, quote=True))
                    .replace("APP_URL_JS", app_url_json)
                    .encode("utf-8")
                )
                self.send_bytes(200, page, "text/html; charset=utf-8")
                return
            if path == "/api/status":
                self.check_origin()
                payment = find_payment(self.get_token())
                self.send_json(200, {
                    "payment_id": payment["id"],
                    "status": payment["payment_status"],
                    "amount": payment["amount_paise"],
                    "currency": payment["currency"]
                })
                return
            raise PaymentError(404, "Payment API route not found.")
        self.handle_request(route)

    def do_POST(self):
        def route():
            path = urlsplit(self.path).path
            if path == "/api/webhooks/razorpay":
                self.handle_webhook()
                return
            self.check_origin()
            payload = self.read_json()
            payment = find_payment(self.get_token())
            if path == "/api/orders":
                self.send_json(200, create_order(payment))
            elif path == "/api/verify":
                result = verify_checkout_payment(payment, payload)
                self.send_json(200, result)
            elif path == "/api/failed":
                self.send_json(200, confirm_failed_payment(payment, payload))
            else:
                raise PaymentError(404, "Payment API route not found.")
        self.handle_request(route)

    def handle_webhook(self):
        secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "").strip()
        if not secret:
            raise PaymentError(503, "Razorpay webhook verification is not configured.")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise PaymentError(400, "The webhook request length is invalid.") from exc
        if length < 1 or length > 1_000_000:
            raise PaymentError(413, "The webhook request body has an invalid size.")
        raw_body = self.rfile.read(length)
        signature = self.headers.get("X-Razorpay-Signature", "")
        if not webhook_signature_is_valid(raw_body, signature, secret):
            raise PaymentError(400, "The Razorpay webhook signature is invalid.")
        try:
            payload = json.loads(raw_body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise PaymentError(400, "The Razorpay webhook payload is invalid.") from exc
        if not isinstance(payload, dict):
            raise PaymentError(400, "The Razorpay webhook payload is invalid.")
        event_id = self.headers.get("X-Razorpay-Event-Id", "")
        self.send_json(
            200,
            process_webhook(raw_body, event_id, payload)
        )


class PaymentHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32


def main():
    initialize_database()
    host = os.environ.get("GOPARKING_PAYMENT_API_HOST", "127.0.0.1")
    port_text = os.environ.get("GOPARKING_PAYMENT_API_PORT", "8765")
    try:
        port = int(port_text)
    except ValueError as exc:
        raise SystemExit("GOPARKING_PAYMENT_API_PORT must be an integer.") from exc
    if not 1 <= port <= 65535:
        raise SystemExit("GOPARKING_PAYMENT_API_PORT must be from 1 to 65535.")
    server = PaymentHTTPServer((host, port), PaymentRequestHandler)
    LOGGER.info("GoParking payment API listening on %s:%s", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("Stopping GoParking payment API.")
    finally:
        server.server_close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
