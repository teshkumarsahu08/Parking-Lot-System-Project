
import socket
import sqlite3
import html
import hashlib
import os
import secrets
from datetime import datetime
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP

import pandas as pd
import streamlit as st
from auth_security import hash_password, is_valid_email, verify_password
from payment_storage import ensure_payment_schema, payment_db_connection

# ---------------- CONFIGURATION ----------------

st.set_page_config(
    page_title="GoParking",
    page_icon="🅿️",
    layout="wide"
)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("GOPARKING_DB_PATH", BASE_DIR / "goparking.db"))
PAYMENT_API_URL = os.environ.get(
    "GOPARKING_PAYMENT_API_URL", "http://127.0.0.1:8765"
).rstrip("/")
PAYMENT_CAPABILITY_LIFETIME_SECONDS = 15 * 60

CAR_RATE = 20
BIKE_RATE = 10
VEHICLE_TYPES = [
    "Motorcycle",
    "Scooter",
    "Bicycle",
    "Hatchback Car",
    "Sedan",
    "SUV",
    "Electric Car",
    "Van",
    "Pickup Truck",
    "Bus",
    "Truck",
    "Car",
    "Bike",
    "Other"
]
VEHICLE_ICONS = {
    "Motorcycle": "🏍️",
    "Scooter": "🛵",
    "Bicycle": "🚲",
    "Hatchback Car": "🚗",
    "Sedan": "🚘",
    "SUV": "🚙",
    "Electric Car": "🔋",
    "Van": "🚐",
    "Pickup Truck": "🛻",
    "Bus": "🚌",
    "Truck": "🚚",
    "Car": "🚗",
    "Bike": "🏍️",
    "Other": "🚘"
}
PARKING_PAGE_PHOTOS = {
    "Dashboard": "multilevel-garage.jpg",
    "My Vehicles": "underground-garage.jpg",
    "Register Vehicle": "underground-garage.jpg",
    "Park Vehicle": "underground-garage.jpg",
    "Remove Vehicle": "multilevel-garage.jpg",
    "Search Vehicle": "multilevel-garage.jpg",
    "Search by Color": "aerial-parking.jpg",
    "Parking Slots": "aerial-parking.jpg",
    "Parking History": "underground-garage.jpg",
    "Fee Calculator": "multilevel-garage.jpg",
    "Payments": "underground-garage.jpg",
    "My Profile": "multilevel-garage.jpg",
    "User Management": "multilevel-garage.jpg",
    "Fee Settings": "multilevel-garage.jpg"
}

# ---------------- DATABASE ----------------

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                mobile TEXT,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user'
                    CHECK (role IN ('admin', 'user')),
                created_at TEXT NOT NULL,
                session_version INTEGER NOT NULL DEFAULT 0
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS vehicles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_user_id INTEGER NOT NULL REFERENCES users(id),
                registration TEXT NOT NULL UNIQUE COLLATE NOCASE,
                vehicle_type TEXT NOT NULL,
                color TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS parking_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                registration TEXT NOT NULL,
                color TEXT NOT NULL,
                vehicle_type TEXT NOT NULL,
                slot INTEGER,
                entry_time TEXT NOT NULL,
                exit_time TEXT,
                fee REAL DEFAULT 0,
                owner_user_id INTEGER REFERENCES users(id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                registration TEXT NOT NULL,
                amount REAL NOT NULL,
                paid_at TEXT NOT NULL,
                owner_user_id INTEGER REFERENCES users(id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS parking_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL
            )
        """)

        ensure_payment_schema(conn)

        conn.executemany(
            "INSERT OR IGNORE INTO parking_settings (setting_key, setting_value) VALUES (?, ?)",
            (
                ("car_rate", str(CAR_RATE)),
                ("bike_rate", str(BIKE_RATE))
            )
        )

        user_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(users)")
        }
        if "session_version" not in user_columns:
            conn.execute(
                "ALTER TABLE users ADD COLUMN session_version "
                "INTEGER NOT NULL DEFAULT 0"
            )

        for table in ("parking_events", "payments"):
            columns = {
                row[1]
                for row in conn.execute(f"PRAGMA table_info({table})")
            }
            if "owner_user_id" not in columns:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN owner_user_id "
                    "INTEGER REFERENCES users(id)"
                )

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_owner_id
            ON parking_events(owner_user_id, id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_payments_owner_id
            ON payments(owner_user_id, id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_vehicles_owner_id
            ON vehicles(owner_user_id, vehicle_type)
        """)


def bootstrap_admin_if_configured():
    configured = {
        "full_name": os.environ.get("GOPARKING_ADMIN_NAME", "").strip(),
        "email": os.environ.get("GOPARKING_ADMIN_EMAIL", "").strip().casefold(),
        "password": os.environ.get("GOPARKING_ADMIN_PASSWORD", "")
    }
    admins = db_query("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
    if admins:
        return None

    if not all(configured.values()):
        if any(configured.values()):
            return (
                "First administrator setup is incomplete. Set "
                "GOPARKING_ADMIN_NAME, GOPARKING_ADMIN_EMAIL, and "
                "GOPARKING_ADMIN_PASSWORD before restarting GoParking."
            )
        return (
            "No administrator exists yet. Set "
            "GOPARKING_ADMIN_NAME, GOPARKING_ADMIN_EMAIL, and "
            "GOPARKING_ADMIN_PASSWORD in the environment, then restart."
        )

    if not is_valid_email(configured["email"]):
        return "GOPARKING_ADMIN_EMAIL must contain a valid email address."
    if len(configured["password"]) < 12:
        return "GOPARKING_ADMIN_PASSWORD must contain at least 12 characters."

    now = datetime.now().isoformat(timespec="seconds")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO users (full_name, email, password_hash, role, created_at)
            VALUES (?, ?, ?, 'admin', ?)
            """,
            (
                configured["full_name"],
                configured["email"],
                hash_password(configured["password"]),
                now
            )
        )
        admin_id = conn.execute(
            "SELECT id FROM users WHERE email = ?",
            (configured["email"],)
        ).fetchone()[0]

        conn.execute(
            "UPDATE parking_events SET owner_user_id = ? WHERE owner_user_id IS NULL",
            (admin_id,)
        )
        conn.execute(
            "UPDATE payments SET owner_user_id = ? WHERE owner_user_id IS NULL",
            (admin_id,)
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO vehicles
                (owner_user_id, registration, vehicle_type, color, created_at)
            SELECT ?, registration, vehicle_type, color, MIN(entry_time)
            FROM parking_events
            GROUP BY UPPER(registration)
            """,
            (admin_id,)
        )

    return "Initial administrator created from the configured environment."


def get_parking_rates():
    rates = {
        row["setting_key"]: float(row["setting_value"])
        for row in db_query(
            "SELECT setting_key, setting_value FROM parking_settings"
        )
    }
    return (
        rates.get("car_rate", CAR_RATE),
        rates.get("bike_rate", BIKE_RATE)
    )

def db_execute(query, values=()):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(query, values)
        conn.commit()


def db_query(query, values=()):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in conn.execute(query, values).fetchall()
        ]


init_db()
ADMIN_SETUP_MESSAGE = bootstrap_admin_if_configured()


def get_current_user():
    user_id = st.session_state.get("user_id")
    if user_id is None:
        return None

    users = db_query(
        """
        SELECT id, full_name, email, mobile, role, session_version
        FROM users WHERE id = ?
        """,
        (user_id,)
    )
    if not users:
        st.session_state.pop("user_id", None)
        st.session_state.pop("user_session_version", None)
        return None
    user = users[0]
    session_version = st.session_state.get("user_session_version")
    if session_version != user["session_version"]:
        st.session_state.pop("user_id", None)
        st.session_state.pop("user_session_version", None)
        st.session_state.auth_notice = "Your session expired. Please sign in again."
        return None
    return user


def register_vehicle(owner_user_id, registration, vehicle_type, color):
    registration = registration.strip().upper()
    color = color.strip()
    existing = db_query(
        "SELECT id, owner_user_id FROM vehicles WHERE UPPER(registration) = ?",
        (registration,)
    )
    now = datetime.now().isoformat(timespec="seconds")

    if existing and existing[0]["owner_user_id"] != owner_user_id:
        return False, "That registration is already associated with another account."

    if existing:
        db_execute(
            """
            UPDATE vehicles
            SET vehicle_type = ?, color = ?
            WHERE id = ? AND owner_user_id = ?
            """,
            (vehicle_type, color, existing[0]["id"], owner_user_id)
        )
    else:
        try:
            db_execute(
                """
                INSERT INTO vehicles
                    (owner_user_id, registration, vehicle_type, color, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (owner_user_id, registration, vehicle_type, color, now)
            )
        except sqlite3.IntegrityError:
            return False, "That registration is already in use."

    return True, "Vehicle saved to your account."


def vehicle_is_owned(registration, user):
    if user["role"] == "admin":
        return True
    return bool(db_query(
        """
        SELECT id FROM vehicles
        WHERE UPPER(registration) = ? AND owner_user_id = ?
        """,
        (registration.strip().upper(), user["id"])
    ))


def get_user_vehicles(user):
    if user["role"] == "admin":
        return db_query(
            """
            SELECT v.id, v.owner_user_id, v.registration, v.vehicle_type,
                   v.color, v.created_at, u.full_name AS owner_name,
                   u.email AS owner_email
            FROM vehicles v
            JOIN users u ON u.id = v.owner_user_id
            ORDER BY v.registration
            """
        )
    return db_query(
        """
        SELECT id, owner_user_id, registration, vehicle_type, color,
               created_at, NULL AS owner_name, NULL AS owner_email
        FROM vehicles
        WHERE owner_user_id = ?
        ORDER BY registration
        """,
        (user["id"],)
    )


# ---------------- JAVA CONNECTION ----------------

def send_to_java(command):
    try:
        with socket.create_connection(
            ("127.0.0.1", 5000), timeout=5
        ) as client:
            client.sendall((command + "\n").encode("utf-8"))

            with client.makefile(
                "r", encoding="utf-8"
            ) as reader:
                response = reader.readline()

        return (
            response.strip()
            if response
            else "ERROR|No response from Java"
        )

    except OSError:
        return "ERROR|Java server not running. Start ParkingServer first."


def get_status():
    response = send_to_java("STATUS")
    parts = response.split("|")

    if len(parts) == 4 and parts[0] == "STATUS":
        try:
            return tuple(map(int, parts[1:]))
        except ValueError:
            pass

    return None


def get_slots():
    response = send_to_java("SLOTS")
    parts = response.split("|")

    if not parts or parts[0] != "SLOTS":
        return []

    slots = []
    i = 1

    try:
        while i < len(parts):
            number = int(parts[i])
            occupied = parts[i + 1].lower() == "true"

            if occupied:
                registration = parts[i + 2]
                color = parts[i + 3]
                vehicle_type = parts[i + 4]
            else:
                registration = ""
                color = ""
                vehicle_type = ""

            slots.append({
                "Slot": number,
                "Status": "Occupied" if occupied else "Available",
                "Registration": registration,
                "Color": color,
                "Type": vehicle_type
            })

            i += 5

    except (ValueError, IndexError):
        return []

    return slots


def render_slot_layout(slots, key_prefix, user):
    if not slots:
        st.info("Parking slot data is not available yet.")
        return

    selected_number = st.session_state.get("selected_slot")
    animation_event = st.session_state.get("slot_animation")

    for start in range(0, len(slots), 5):
        columns = st.columns(5)

        for column, slot in zip(columns, slots[start:start + 5]):
            number = slot["Slot"]
            occupied = slot["Status"] == "Occupied"
            css = "slot-busy" if occupied else "slot-free"
            can_view_vehicle = (
                user["role"] == "admin"
                or vehicle_is_owned(slot["Registration"], user)
            ) if occupied else True
            animating_entry = (
                animation_event
                and animation_event["slot"] == number
                and animation_event["action"] == "entry"
            )
            animating_exit = (
                animation_event
                and animation_event["slot"] == number
                and animation_event["action"] == "exit"
            )
            if animating_entry:
                css += " slot-enter"
            elif animating_exit:
                css += " slot-exit"
            selected = number == selected_number
            title = f'P{number:02d}'
            detail = (
                f'{html.escape(slot["Registration"])} · '
                f'{html.escape(slot["Type"])} · '
                f'{html.escape(slot["Color"])}'
                if slot["Registration"] and can_view_vehicle
                else "Vehicle details are private"
                if slot["Registration"]
                else "Ready to park"
            )
            car_class = (
                "slot-car-icon slot-car-icon--entering"
                if animating_entry else
                "slot-car-icon slot-car-icon--leaving"
                if animating_exit else
                "slot-car-icon"
            )
            car_icon = (
                f'<svg class="{car_class}" viewBox="0 0 24 18" fill="none" '
                f'xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
                f'<path d="M3 11 5 6.5C5.4 5.6 6.2 5 7.2 5h9.6c1 0 1.8.6 2.2 1.5l2 4.5v4H3v-4Z" '
                f'fill="currentColor" fill-opacity=".25" stroke="currentColor" stroke-width="1.4"/>'
                f'<circle cx="7" cy="14.5" r="1.5" fill="#0B1725" stroke="currentColor"/>'
                f'<circle cx="17" cy="14.5" r="1.5" fill="#0B1725" stroke="currentColor"/>'
                f'</svg>'
                if occupied or animating_exit else
                '<span class="slot-empty-label">OPEN</span>'
            )

            column.markdown(
                f'<div class="slot-card {css}{" selected" if selected else ""}" '
                f'style="animation-delay: {((number - 1) % 5) * 65}ms">'
                f'<div class="slot-heading"><b>{title}</b>'
                f'<span class="slot-status"><span class="slot-indicator"></span>'
                f'{html.escape(slot["Status"])}</span></div>'
                f'<div class="slot-details">'
                f'{car_icon}<span>{detail}</span></div></div>',
                unsafe_allow_html=True
            )
            if column.button(
                "Selected" if selected else "View slot",
                key=f"{key_prefix}_slot_{number}",
                disabled=selected,
                use_container_width=True
            ):
                st.session_state.selected_slot = number
                st.rerun()

    if animation_event and any(
        slot["Slot"] == animation_event["slot"] for slot in slots
    ):
        st.session_state.slot_animation = None

    selected_slot = next(
        (slot for slot in slots if slot["Slot"] == selected_number),
        None
    )
    if selected_slot:
        with st.container(border=True):
            left, right = st.columns([3, 1])
            with left:
                st.markdown(f'### P{selected_slot["Slot"]:02d} · {selected_slot["Status"]}')
                if selected_slot["Status"] == "Occupied":
                    if (
                        user["role"] == "admin"
                        or vehicle_is_owned(selected_slot["Registration"], user)
                    ):
                        st.write(
                            f'Registration: **{selected_slot["Registration"]}**  ·  '
                            f'Type: **{selected_slot["Type"]}**  ·  '
                            f'Color: **{selected_slot["Color"]}**'
                        )
                    else:
                        st.caption(
                            "Vehicle details in this occupied space are private."
                        )
                else:
                    st.caption(
                        "This space is available. Vehicle allocation follows "
                        "the Java parking lot's next-available-slot rule."
                    )
            with right:
                if (
                    selected_slot["Status"] == "Occupied"
                    and (
                        user["role"] == "admin"
                        or vehicle_is_owned(
                            selected_slot["Registration"], user
                        )
                    )
                ):
                    if st.button(
                        "Remove vehicle",
                        key=f"{key_prefix}_remove_selected",
                        use_container_width=True
                    ):
                        st.session_state.remove_registration = selected_slot["Registration"]
                        st.session_state.page = "Remove Vehicle"
                        st.rerun()
                elif st.button(
                    "Open parking form",
                    key=f"{key_prefix}_park_selected",
                    use_container_width=True
                ):
                    st.session_state.page = "Park Vehicle"
                    st.rerun()


# ---------------- RESTORE ACTIVE VEHICLES ----------------

def sync_active_vehicles():
    """
    Restore vehicles whose exit_time is NULL.
    Existing vehicles are skipped to avoid duplicates.
    """

    status_response = send_to_java("STATUS")

    if not status_response.startswith("STATUS|"):
        return

    active_vehicles = db_query("""
        SELECT registration, color, vehicle_type, slot
        FROM parking_events
        WHERE exit_time IS NULL
        ORDER BY id ASC
    """)

    for vehicle in active_vehicles:
        registration = vehicle["registration"]
        color = vehicle["color"]
        vehicle_type = vehicle["vehicle_type"]
        slot = vehicle["slot"]

        # Skip if the vehicle already exists in Java.
        find_response = send_to_java(f"FIND|{registration}")

        if find_response.startswith("FOUND|"):
            continue

        if slot is None:
            continue

        restore_command = (
            f"RESTORE|{registration}|{color}|"
            f"{vehicle_type}|{int(slot)}"
        )

        restore_response = send_to_java(restore_command)

        if restore_response.startswith("OK|"):
            print(
                f"Restored {registration} to slot {slot}"
            )
        elif restore_response.startswith("ERROR|"):
            print(
                f"Restore issue for {registration}: "
                f"{restore_response}"
            )


# ---------------- DATABASE HISTORY ----------------

def record_entry(owner_user_id, registration, color, vehicle_type, slot):
    now = datetime.now().isoformat(timespec="seconds")

    db_execute("""
        INSERT INTO parking_events
        (registration, color, vehicle_type, slot,
         entry_time, exit_time, fee, owner_user_id)
        VALUES (?, ?, ?, ?, ?, NULL, 0, ?)
    """, (
        registration, color, vehicle_type, slot, now, owner_user_id
    ))


def record_exit(registration, user):
    owner_filter = "" if user["role"] == "admin" else "AND owner_user_id = ?"
    values = (registration,) if user["role"] == "admin" else (
        registration, user["id"]
    )
    events = db_query("""
        SELECT id, entry_time, vehicle_type, owner_user_id
        FROM parking_events
        WHERE UPPER(registration) = UPPER(?)
          AND exit_time IS NULL
    """ + owner_filter + """
        ORDER BY id DESC
        LIMIT 1
    """, values)

    if not events:
        return None

    event = events[0]
    now = datetime.now()
    entry = datetime.fromisoformat(event["entry_time"])

    seconds = max(0, (now - entry).total_seconds())
    hours = max(1, int(seconds // 3600) +
                (1 if seconds % 3600 else 0))

    car_rate, bike_rate = get_parking_rates()
    rate = bike_rate if event["vehicle_type"].lower() in {
        "bike", "motorcycle", "scooter", "bicycle"
    } else car_rate
    fee = hours * rate

    now_text = now.isoformat(timespec="seconds")
    amount_paise = int(
        (Decimal(str(fee)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    with payment_db_connection(DB_PATH, timeout=5) as conn:
        conn.execute("BEGIN IMMEDIATE")
        updated = conn.execute("""
            UPDATE parking_events
            SET exit_time = ?, fee = ?
            WHERE id = ? AND exit_time IS NULL
        """, (now_text, fee, event["id"]))
        if updated.rowcount != 1:
            return None
        conn.execute("""
            INSERT INTO payments (
                registration, amount, paid_at, owner_user_id, event_id,
                amount_paise, currency, payment_status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'INR', 'CREATED', ?, ?)
        """, (
            registration, fee, now_text, event["owner_user_id"], event["id"],
            amount_paise, now_text, now_text
        ))

    return fee


def create_checkout_url(payment_id):
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = datetime.now()
    expires_at = now.timestamp() + PAYMENT_CAPABILITY_LIFETIME_SECONDS
    expires_text = datetime.fromtimestamp(expires_at).isoformat(timespec="seconds")
    with payment_db_connection(DB_PATH, timeout=5) as conn:
        conn.execute("""
            DELETE FROM razorpay_payment_capabilities
            WHERE expires_at <= ?
        """, (now.isoformat(timespec="seconds"),))
        payment = conn.execute("""
            SELECT id FROM payments
            WHERE id = ? AND event_id IS NOT NULL
              AND payment_status IN ('CREATED', 'PENDING', 'FAILED')
        """, (payment_id,)).fetchone()
        if payment is None:
            return None
        conn.execute("""
            INSERT INTO razorpay_payment_capabilities (token_hash, payment_id, expires_at)
            VALUES (?, ?, ?)
        """, (token_hash, payment_id, expires_text))
    return f"{PAYMENT_API_URL}/checkout#{token}"


# ---------------- SESSION ----------------

if "auth_page" not in st.session_state:
    st.session_state.auth_page = "Landing"
if "page" not in st.session_state:
    st.session_state.page = "Dashboard"

if "selected_slot" not in st.session_state:
    st.session_state.selected_slot = None


# ---------------- STYLE ----------------

st.markdown("""
<style>
* {
    box-sizing: border-box;
}
@keyframes vehicle-enter-slot {
    from {
        opacity: 0;
        transform: translateX(16px) scale(0.78);
    }
    to {
        opacity: 1;
        transform: translateX(0) scale(1);
    }
}
@keyframes vehicle-exit-slot {
    from {
        opacity: 1;
        transform: translateX(0) scale(1);
    }
    to {
        opacity: 0;
        transform: translateX(16px) scale(0.78);
    }
}
html, body {
    overflow-x: hidden;
}
.stApp {
    color: #e8f1ff;
    background:
        radial-gradient(ellipse at 12% 8%, rgba(29, 110, 203, 0.16), transparent 38%),
        linear-gradient(135deg, #071321 0%, #0a1930 48%, #07111f 100%);
    background-attachment: fixed;
}
[data-testid="stAppViewContainer"] {
    background: transparent;
}
[data-testid="stHeader"] {
    background: rgba(7, 19, 33, 0.72);
}
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, rgba(12, 29, 51, 0.98), rgba(7, 19, 33, 0.98));
    border-right: 1px solid rgba(129, 173, 224, 0.13);
}
[data-testid="stSidebar"] > div:first-child {
    background: transparent;
}
.block-container {
    width: 100%;
    max-width: 1440px;
    padding: 2rem 2rem 3rem;
}
.hero {
    position: relative;
    overflow: hidden;
    display: grid;
    grid-template-columns: minmax(0, 1.1fr) minmax(280px, 0.9fr);
    align-items: center;
    gap: 22px;
    padding: clamp(22px, 4vw, 36px);
    border: 1px solid rgba(143, 196, 255, 0.2);
    border-radius: 22px;
    background:
        radial-gradient(ellipse at 82% 30%, rgba(38, 194, 220, 0.14), transparent 38%),
        linear-gradient(115deg, rgba(19, 57, 103, 0.92), rgba(12, 36, 66, 0.94) 58%, rgba(8, 50, 68, 0.92));
    box-shadow: 0 18px 48px rgba(0, 0, 0, 0.24), inset 0 1px 0 rgba(255, 255, 255, 0.06);
    margin-bottom: 26px;
    animation: fade-slide-up 650ms cubic-bezier(0.2, 0.75, 0.25, 1) both;
}
.hero--login {
    display: block;
}
.landing-hero {
    position: relative;
    display: grid;
    min-height: clamp(420px, 64vh, 650px);
    align-items: center;
    overflow: hidden;
    padding: clamp(28px, 7vw, 76px);
    border: 1px solid rgba(143, 196, 255, 0.2);
    border-radius: 24px;
    background-color: #0a1930;
    background-image:
        linear-gradient(90deg, rgba(5, 13, 27, 0.96) 0%, rgba(5, 16, 33, 0.83) 46%, rgba(5, 16, 33, 0.37) 100%),
        linear-gradient(0deg, rgba(7, 18, 34, 0.58), transparent 55%),
        url("/app/static/parking/aerial-parking.jpg");
    background-size: cover;
    background-position: center;
    box-shadow: 0 22px 60px rgba(0, 0, 0, 0.33);
}
.landing-copy {
    position: relative;
    z-index: 1;
    max-width: 700px;
}
.landing-copy h1 {
    margin: 12px 0;
    color: #f4f8ff;
    font-size: clamp(2.5rem, 6vw, 5rem);
    letter-spacing: -0.055em;
    line-height: 1.02;
}
.landing-copy p {
    max-width: 580px;
    color: #d0e1f4;
    font-size: clamp(1rem, 2vw, 1.2rem);
    line-height: 1.7;
}
.auth-panel {
    max-width: 680px;
    margin: 26px auto 0;
    padding: clamp(20px, 4vw, 36px);
    border: 1px solid rgba(141, 177, 220, 0.18);
    border-radius: 20px;
    background: rgba(13, 29, 49, 0.74);
    box-shadow: 0 18px 44px rgba(0, 0, 0, 0.22);
    backdrop-filter: blur(14px);
    animation: fade-slide-up 420ms ease-out both;
}
.hero-copy {
    position: relative;
    z-index: 1;
}
.hero-eyebrow {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 15px;
    color: #8ce7f3;
    font-size: 0.76rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
}
.live-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #54e1b3;
    box-shadow: 0 0 12px rgba(84, 225, 179, 0.72);
}
.hero-scene {
    position: relative;
    min-width: 0;
    pointer-events: none;
}
.garage-illustration {
    display: block;
    width: 100%;
    height: auto;
    overflow: visible;
    filter: drop-shadow(0 12px 26px rgba(0, 0, 0, 0.24));
}
.garage-illustration .cruising-car {
    transform-box: fill-box;
    transform-origin: center;
    animation: park-in 7s cubic-bezier(0.2, 0.75, 0.25, 1) 350ms both;
}
.garage-illustration .road-light {
    animation: road-light 2.8s ease-in-out infinite alternate;
}
.garage-illustration .road-light--delayed {
    animation-delay: 450ms;
}
.hero h1 {
    margin: 0 0 7px;
    color: #f4f8ff;
    font-size: clamp(1.75rem, 3.5vw, 2.55rem);
    font-weight: 750;
    letter-spacing: -0.035em;
    line-height: 1.12;
}
.hero p {
    margin: 0;
    color: #c1d6ef;
    font-size: 1rem;
    line-height: 1.65;
}
.metric-card {
    height: 100%;
    padding: 20px 22px;
    border: 1px solid rgba(141, 177, 220, 0.17);
    border-radius: 18px;
    background: rgba(12, 20, 40, 0.78);
    box-shadow: 0 12px 30px rgba(0, 0, 0, 0.16), inset 0 1px 0 rgba(255, 255, 255, 0.035);
    backdrop-filter: blur(12px);
    transition: transform 180ms ease, border-color 180ms ease, box-shadow 180ms ease;
    animation: fade-slide-up 600ms cubic-bezier(0.2, 0.75, 0.25, 1) both;
}
.metric-card:hover {
    transform: translateY(-2px);
    border-color: rgba(72, 190, 230, 0.42);
    box-shadow: 0 16px 34px rgba(0, 0, 0, 0.22);
}
.metric-card p {
    margin: 0 0 8px;
    color: #a9bfd9;
    font-size: 0.9rem;
}
.metric-card h2 {
    margin: 0;
    color: #f4f8ff;
    font-size: 2rem;
    font-weight: 700;
    animation: counter-arrive 750ms cubic-bezier(0.2, 0.75, 0.25, 1) both;
}
.slot-card {
    position: relative;
    min-height: 96px;
    margin-bottom: 12px;
    padding: 15px;
    border: 1px solid transparent;
    border-radius: 15px;
    color: #f5f9ff;
    line-height: 1.55;
    overflow-wrap: anywhere;
    box-shadow: 0 8px 20px rgba(0, 0, 0, 0.15);
    transition: transform 200ms ease, filter 200ms ease, box-shadow 200ms ease, border-color 200ms ease;
    animation: fade-slide-up 500ms cubic-bezier(0.2, 0.75, 0.25, 1) both;
}
.slot-card:hover {
    transform: translateY(-2px);
    filter: brightness(1.08);
    box-shadow: 0 12px 25px rgba(0, 0, 0, 0.24);
}
.slot-card.selected {
    border-color: #46c4ff;
    box-shadow: 0 0 0 2px rgba(70, 196, 255, 0.25), 0 0 22px rgba(41, 169, 255, 0.2);
}
.metric-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 14px;
}
.metric-icon {
    display: grid;
    width: 38px;
    height: 38px;
    place-items: center;
    border: 1px solid rgba(95, 208, 238, 0.24);
    border-radius: 12px;
    color: #7ee8f5;
    background: rgba(41, 149, 196, 0.13);
}
.metric-icon svg {
    width: 21px;
    height: 21px;
}
.metric-live {
    color: #7c9ab8;
    font-size: 0.65rem;
    font-weight: 750;
    letter-spacing: 0.12em;
}
.occupancy-panel,
.activity-card {
    padding: 20px;
    border: 1px solid rgba(141, 177, 220, 0.16);
    border-radius: 16px;
    background: rgba(12, 20, 40, 0.72);
    box-shadow: 0 10px 25px rgba(0, 0, 0, 0.13);
}
.occupancy-track {
    height: 9px;
    margin: 14px 0 9px;
    overflow: hidden;
    border-radius: 99px;
    background: rgba(123, 159, 192, 0.16);
}
.occupancy-fill {
    height: 100%;
    border-radius: inherit;
    background: linear-gradient(90deg, #2a9fff, #51e1db);
    box-shadow: 0 0 15px rgba(59, 188, 233, 0.34);
    transition: width 400ms ease;
}
.activity-card {
    margin: 0 0 10px;
    padding: 14px 16px;
    animation: fade-slide-up 400ms ease-out both;
}
.activity-topline {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    color: #f0f6ff;
    font-weight: 650;
}
.activity-card small {
    color: #9bb3ce;
}
.slot-card {
    min-height: 106px;
}
.slot-empty-label {
    flex: 0 0 auto;
    color: #9de7c0;
    font-size: 0.62rem;
    font-weight: 750;
    letter-spacing: 0.1em;
}
.slot-car-icon--entering {
    animation: vehicle-enter-slot 650ms cubic-bezier(0.2, 0.75, 0.25, 1) both;
}
.slot-car-icon--leaving {
    animation: vehicle-exit-slot 650ms cubic-bezier(0.4, 0, 1, 1) both;
}
.sidebar-brand {
    display: flex;
    align-items: center;
    gap: 12px;
    margin: 4px 0 20px;
    padding: 13px 10px;
    border: 1px solid rgba(104, 216, 237, 0.19);
    border-radius: 14px;
    background: linear-gradient(135deg, rgba(27, 77, 125, 0.42), rgba(12, 36, 61, 0.56));
}
.sidebar-brand-mark {
    display: grid;
    width: 40px;
    height: 40px;
    place-items: center;
    border: 1px solid rgba(111, 230, 245, 0.45);
    border-radius: 12px;
    color: #a8f3ff;
    background: rgba(24, 155, 205, 0.18);
    box-shadow: 0 0 18px rgba(30, 171, 222, 0.16);
    font-size: 1.2rem;
    font-weight: 800;
}
.sidebar-brand strong {
    display: block;
    color: #f1f7ff;
    font-size: 0.98rem;
}
.sidebar-brand small {
    color: #8eaac7;
    font-size: 0.64rem;
    letter-spacing: 0.1em;
}
.slot-heading {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 9px;
}
.slot-heading b {
    display: inline-block;
    color: #ffffff;
    font-size: 0.98rem;
}
.slot-status {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: #eaf3ff;
    font-size: 0.72rem;
    font-weight: 650;
    white-space: nowrap;
}
.slot-indicator {
    width: 8px;
    height: 8px;
    border-radius: 50%;
}
.slot-details {
    display: flex;
    align-items: center;
    gap: 7px;
    color: #d1e1f4;
    font-size: 0.82rem;
}
.slot-car-icon {
    width: 20px;
    height: 16px;
    flex: 0 0 auto;
    color: currentColor;
}
.slot-free {
    border-color: rgba(96, 221, 164, 0.3);
    background: linear-gradient(145deg, rgba(24, 105, 79, 0.76), rgba(17, 61, 59, 0.92));
}
.slot-free .slot-indicator {
    background: #67e6a5;
    box-shadow: 0 0 10px rgba(103, 230, 165, 0.7);
}
.slot-busy {
    border-color: rgba(255, 139, 117, 0.32);
    background: linear-gradient(145deg, rgba(132, 55, 58, 0.8), rgba(82, 36, 48, 0.92));
}
.slot-busy .slot-indicator {
    background: #ff807f;
    box-shadow: 0 0 10px rgba(255, 128, 127, 0.65);
}
.slot-reserved {
    border-color: rgba(250, 193, 94, 0.36);
    background: linear-gradient(145deg, rgba(133, 91, 35, 0.82), rgba(82, 61, 35, 0.92));
}
.slot-reserved .slot-indicator {
    background: #ffc15a;
    box-shadow: 0 0 10px rgba(255, 193, 90, 0.68);
}
.small-note {
    color: #a9bfd9;
}
h1, h2, h3, h4, h5, h6, p, label, [data-testid="stMarkdownContainer"] {
    color: #e8f1ff;
}
[data-testid="stMarkdownContainer"] a {
    color: #68d8ed;
}
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stSelectbox"] [data-baseweb="select"] > div,
[data-testid="stDateInput"] input,
[data-testid="stTimeInput"] input {
    color: #edf5ff;
    border-color: rgba(144, 178, 217, 0.28);
    border-radius: 11px;
    background-color: rgba(10, 25, 43, 0.78);
}
[data-testid="stTextInput"] input:focus,
[data-testid="stNumberInput"] input:focus,
[data-testid="stDateInput"] input:focus,
[data-testid="stTimeInput"] input:focus {
    border-color: #49bfd8;
    box-shadow: 0 0 0 1px rgba(73, 191, 216, 0.28);
}
[data-testid="stForm"] {
    padding: 20px;
    border: 1px solid rgba(141, 177, 220, 0.15);
    border-radius: 18px;
    background: rgba(13, 29, 49, 0.62);
    box-shadow: 0 12px 28px rgba(0, 0, 0, 0.12);
    animation: fade-slide-up 450ms ease-out both;
}
[data-testid="stButton"] button,
[data-testid="stFormSubmitButton"] button,
[data-testid="stDownloadButton"] button {
    min-height: 42px;
    border: 1px solid rgba(104, 216, 237, 0.38);
    border-radius: 11px;
    color: #f5fbff;
    background: linear-gradient(110deg, #176eb8, #087f91);
    font-weight: 650;
    transition: transform 160ms ease, filter 160ms ease, box-shadow 160ms ease;
}
[data-testid="stButton"] button:hover,
[data-testid="stFormSubmitButton"] button:hover,
[data-testid="stDownloadButton"] button:hover {
    border-color: rgba(139, 237, 249, 0.74);
    color: #ffffff;
    filter: brightness(1.1);
    transform: translateY(-1px);
    box-shadow: 0 8px 20px rgba(0, 132, 165, 0.22);
}
[data-testid="stDataFrame"],
[data-testid="stTable"] {
    overflow: hidden;
    border: 1px solid rgba(141, 177, 220, 0.16);
    border-radius: 14px;
}
[data-testid="stSidebar"] [data-testid="stRadio"] label {
    border-radius: 9px;
    transition: background-color 160ms ease, color 160ms ease;
}
[data-testid="stSidebar"] [data-testid="stRadio"] label:hover {
    background: rgba(67, 150, 218, 0.14);
}
[data-testid="stSidebar"] [data-testid="stRadio"] input[type="radio"] {
    accent-color: #49c5ef;
}
[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) {
    border-left: 3px solid #49c5ef;
    color: #b8f5ff;
    background: linear-gradient(90deg, rgba(36, 145, 206, 0.23), rgba(36, 145, 206, 0.04));
    box-shadow: inset 10px 0 18px -16px #5ad9ff;
}
hr {
    border-color: rgba(141, 177, 220, 0.16);
}
@keyframes fade-slide-up {
    from {
        opacity: 0;
        transform: translateY(12px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}
@keyframes counter-arrive {
    from {
        opacity: 0;
        transform: translateY(8px) scale(0.96);
    }
    to {
        opacity: 1;
        transform: translateY(0) scale(1);
    }
}
@keyframes park-in {
    0%, 6% {
        transform: translate(0, 0);
    }
    45% {
        transform: translate(155px, 0);
    }
    58% {
        transform: translate(174px, 0);
    }
    100% {
        transform: translate(246px, -75px);
    }
}
@keyframes road-light {
    from {
        opacity: 0.35;
    }
    to {
        opacity: 1;
    }
}
@media (max-width: 768px) {
    .block-container {
        padding: 1.25rem 1rem 2rem;
    }
    .hero {
        grid-template-columns: minmax(0, 1fr);
        gap: 12px;
        margin-bottom: 20px;
        border-radius: 18px;
    }
    .hero-scene {
        max-width: 520px;
        width: 100%;
        margin-inline: auto;
    }
    .metric-card {
        padding: 16px;
    }
    .metric-card h2 {
        font-size: 1.65rem;
    }
    [data-testid="stForm"] {
        padding: 15px;
    }
}
@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
        scroll-behavior: auto !important;
        transition-duration: 0.01ms !important;
    }
    .hero,
    .metric-card,
    .metric-card h2,
    .slot-card,
    .garage-illustration .cruising-car,
    .garage-illustration .road-light,
    .slot-car-icon--entering,
    .slot-car-icon--leaving {
        animation: none !important;
    }
    .garage-illustration .cruising-car {
        transform: translate(246px, -75px);
    }
}
</style>
""", unsafe_allow_html=True)


# ---------------- PAGE PHOTOGRAPH ----------------

def apply_page_background(photo_name):
    st.markdown(
        f"""
        <style>
        .stApp {{
            background-color: #071321;
            background-image:
                linear-gradient(112deg, rgba(4, 11, 23, 0.78), rgba(5, 16, 32, 0.66)),
                radial-gradient(ellipse at 82% 12%, rgba(15, 117, 181, 0.16), transparent 42%),
                url("/app/static/parking/{photo_name}");
            background-size: cover, cover, cover;
            background-position: center, center, center;
            background-repeat: no-repeat, no-repeat, no-repeat;
            background-attachment: fixed;
        }}
        .landing-hero {{
            background-image:
                linear-gradient(90deg, rgba(5, 13, 27, 0.84) 0%, rgba(5, 16, 33, 0.62) 46%, rgba(5, 16, 33, 0.24) 100%),
                linear-gradient(0deg, rgba(7, 18, 34, 0.38), transparent 55%),
                url("/app/static/parking/aerial-parking.jpg");
        }}
        @media (max-width: 768px) {{
            .stApp {{
                background-position: center, center, 58% center;
                background-attachment: scroll;
            }}
            .landing-hero {{
                background-position: center, center, 62% center;
            }}
        }}
        </style>
        """,
        unsafe_allow_html=True
    )


current_user = get_current_user()
if current_user is None:
    page_photo = (
        "aerial-parking.jpg"
        if st.session_state.auth_page == "Landing"
        else "underground-garage.jpg"
    )
    apply_page_background(page_photo)


# ---------------- PUBLIC LANDING AND AUTHENTICATION ----------------

if current_user is None:
    auth_page = st.session_state.auth_page
    if st.session_state.pop("auth_notice", False):
        st.info("Your session expired. Please sign in again.")

    if auth_page == "Landing":
        st.markdown("""
        <section class="landing-hero">
            <div class="landing-copy">
                <div class="hero-eyebrow"><span class="live-dot"></span> GoParking · Smart mobility</div>
                <h1>Smart Parking.<br>Seamless Experience.</h1>
                <p>Find your perfect parking spot, park your vehicle, and manage your parking effortlessly.</p>
            </div>
        </section>
        """, unsafe_allow_html=True)
        landing_login, landing_register, _ = st.columns([1, 1, 4])
        with landing_login:
            if st.button("Login", key="landing_login", use_container_width=True):
                st.session_state.auth_page = "Login"
                st.rerun()
        with landing_register:
            if st.button("Get Started", key="landing_register", use_container_width=True):
                st.session_state.auth_page = "Register"
                st.rerun()
        if ADMIN_SETUP_MESSAGE:
            st.warning(ADMIN_SETUP_MESSAGE)
        st.stop()

    if auth_page == "Forgot Password":
        with st.container(border=True):
            st.subheader("Password recovery")
            st.info(
                "Email-based password recovery is not configured. "
                "Contact the parking administrator to reset your account securely."
            )
            if st.button("Back to login", key="forgot_back"):
                st.session_state.auth_page = "Login"
                st.rerun()
        st.stop()

    heading = "Create your account" if auth_page == "Register" else "Welcome back"
    st.markdown(
        '<div class="auth-panel">'
        '<div class="hero-eyebrow"><span class="live-dot"></span> GoParking account</div>'
        f'<h2>{heading}</h2>'
        '</div>',
        unsafe_allow_html=True
    )

    if st.session_state.pop("registration_notice", False):
        st.success("Account created. Sign in to continue.")
    if ADMIN_SETUP_MESSAGE and auth_page == "Register":
        st.warning(ADMIN_SETUP_MESSAGE)

    if auth_page == "Register":
        with st.form("register_account_form"):
            full_name = st.text_input("Full Name", max_chars=100).strip()
            email = st.text_input("Email Address", max_chars=254).strip().casefold()
            mobile = st.text_input(
                "Mobile Number (optional)",
                max_chars=20
            ).strip()
            password = st.text_input(
                "Password (at least 12 characters)",
                type="password"
            )
            confirm_password = st.text_input(
                "Confirm Password",
                type="password"
            )
            register_submitted = st.form_submit_button(
                "Create account",
                use_container_width=True
            )

        if register_submitted:
            if not full_name or not email or not password:
                st.error("Name, email, and password are required.")
            elif not is_valid_email(email):
                st.error("Enter a valid email address.")
            elif mobile and (
                len(mobile) < 7
                or any(not (character.isdigit() or character in "+- ()")
                       for character in mobile)
            ):
                st.error("Enter a valid mobile number or leave it blank.")
            elif len(password) < 12:
                st.error("Choose a password with at least 12 characters.")
            elif password != confirm_password:
                st.error("The passwords do not match.")
            else:
                try:
                    db_execute(
                        """
                        INSERT INTO users
                            (full_name, email, mobile, password_hash, role, created_at)
                        VALUES (?, ?, ?, ?, 'user', ?)
                        """,
                        (
                            full_name,
                            email,
                            mobile or None,
                            hash_password(password),
                            datetime.now().isoformat(timespec="seconds")
                        )
                    )
                except sqlite3.IntegrityError:
                    st.error("An account with that email already exists.")
                else:
                    st.session_state.registration_notice = True
                    st.session_state.auth_page = "Login"
                    st.rerun()

        if st.button("Already registered? Sign in", key="register_to_login"):
            st.session_state.auth_page = "Login"
            st.rerun()
    else:
        with st.form("login_form"):
            email = st.text_input("Email Address").strip().casefold()
            password = st.text_input("Password", type="password")
            login_submitted = st.form_submit_button(
                "Login",
                use_container_width=True
            )

        if login_submitted:
            account = db_query(
                """
            SELECT id, password_hash, session_version
                FROM users
                WHERE email = ? COLLATE NOCASE
                LIMIT 1
                """,
                (email,)
            ) if is_valid_email(email) else []
            if account and verify_password(password, account[0]["password_hash"]):
                st.session_state.user_id = account[0]["id"]
                st.session_state.user_session_version = account[0]["session_version"]
                st.session_state.page = "Dashboard"
                st.session_state.auth_page = "Landing"
                st.rerun()
            else:
                st.error("Invalid email or password.")

        forgot_column, register_column = st.columns(2)
        with forgot_column:
            if st.button("Forgot password?", key="login_forgot"):
                st.session_state.auth_page = "Forgot Password"
                st.rerun()
        with register_column:
            if st.button("Create an account", key="login_register"):
                st.session_state.auth_page = "Register"
                st.rerun()

    st.stop()


# ---------------- SIDEBAR ----------------

st.sidebar.markdown(
    '<div class="sidebar-brand"><span class="sidebar-brand-mark">G</span>'
    '<span><strong>GoParking</strong><small>SMART PARKING</small></span></div>',
    unsafe_allow_html=True
)

pages = [
    "Dashboard",
    "My Vehicles",
    "Register Vehicle",
    "Park Vehicle",
    "Remove Vehicle",
    "Search Vehicle",
    "Search by Color",
    "Parking Slots",
    "Parking History",
    "Fee Calculator",
    "Payments",
    "My Profile"
]
if current_user["role"] == "admin":
    pages.extend(["User Management", "Fee Settings"])

page_icons = {
    "Dashboard": "◈",
    "My Vehicles": "▣",
    "Register Vehicle": "＋",
    "Park Vehicle": "↗",
    "Remove Vehicle": "↙",
    "Search Vehicle": "⌕",
    "Search by Color": "◉",
    "Parking Slots": "▦",
    "Parking History": "◷",
    "Fee Calculator": "₹",
    "Payments": "◇",
    "My Profile": "◎",
    "User Management": "♙",
    "Fee Settings": "₹"
}

st.session_state.page = st.sidebar.radio(
    "Navigation",
    pages,
    index=(
        pages.index(st.session_state.page)
        if st.session_state.page in pages else 0
    ),
    format_func=lambda page_name: (
        f'{page_icons.get(page_name, "•")}  {page_name}'
    )
)

if current_user is not None:
    page_photo = (
        "multilevel-garage.jpg"
        if current_user["role"] == "admin"
        and st.session_state.page == "Dashboard"
        else PARKING_PAGE_PHOTOS.get(
            st.session_state.page,
            "multilevel-garage.jpg"
        )
    )
    apply_page_background(page_photo)

if st.sidebar.button("Logout", use_container_width=True):
    st.session_state.pop("user_id", None)
    st.session_state.pop("user_session_version", None)
    st.session_state.page = "Dashboard"
    st.session_state.auth_page = "Landing"
    st.rerun()


st.markdown("""
<section class="hero">
    <div class="hero-copy">
        <div class="hero-eyebrow"><span class="live-dot"></span> Live parking system</div>
        <h1>Smart Parking.<br>Seamless Experience.</h1>
        <p>Find, manage, and optimize parking spaces with intelligent parking management.</p>
    </div>
    <div class="hero-scene" aria-hidden="true">
        <svg class="garage-illustration" viewBox="0 0 520 280" fill="none" xmlns="http://www.w3.org/2000/svg">
            <defs>
                <linearGradient id="garage-wall" x1="260" y1="30" x2="260" y2="205" gradientUnits="userSpaceOnUse">
                    <stop stop-color="#183B60"/>
                    <stop offset="1" stop-color="#10243D"/>
                </linearGradient>
                <linearGradient id="garage-floor" x1="260" y1="175" x2="260" y2="280" gradientUnits="userSpaceOnUse">
                    <stop stop-color="#1B3654"/>
                    <stop offset="1" stop-color="#0A192B"/>
                </linearGradient>
                <linearGradient id="car-paint" x1="0" y1="0" x2="0" y2="1">
                    <stop stop-color="#65DFF4"/>
                    <stop offset="1" stop-color="#1685C8"/>
                </linearGradient>
            </defs>
            <rect x="1" y="1" width="518" height="278" rx="19" fill="#0B1C30" fill-opacity=".74" stroke="#75B8EA" stroke-opacity=".2"/>
            <path d="M22 50H498M37 32H143M376 32H482" stroke="#7BCDF3" stroke-opacity=".26" stroke-width="2"/>
            <rect x="31" y="52" width="458" height="127" rx="5" fill="url(#garage-wall)" fill-opacity=".36"/>
            <path d="M62 49V175M458 49V175" stroke="#8ABDE0" stroke-opacity=".18" stroke-width="3"/>
            <path d="M73 68H165V174H73zM180 68H272V174H180zM287 68H379V174H287zM394 68H447V174H394z" stroke="#77BBD9" stroke-opacity=".35" stroke-width="2"/>
            <path d="M84 78H154M191 78H261M298 78H368M405 78H436" stroke="#82E7F0" stroke-opacity=".55" stroke-width="3"/>
            <path d="M28 188L260 162L492 188V260H28V188Z" fill="url(#garage-floor)" stroke="#83CBE8" stroke-opacity=".16"/>
            <path d="M29 226H491M45 250H475" stroke="#8DBDD6" stroke-opacity=".12" stroke-width="2"/>
            <path d="M52 209H468" stroke="#DBF7FF" stroke-opacity=".66" stroke-width="2" stroke-dasharray="20 18"/>
            <path class="road-light" d="M160 210H184" stroke="#53DFF2" stroke-width="4" stroke-linecap="round"/>
            <path class="road-light road-light--delayed" d="M335 210H359" stroke="#53DFF2" stroke-width="4" stroke-linecap="round"/>
            <g transform="translate(40 207)">
              <g class="cruising-car">
                <path d="M10 28L17 15C20 10 24 8 30 8H58C64 8 68 11 71 16L78 28L85 32V43H6V33L10 28Z" fill="url(#car-paint)" stroke="#B9F5FC" stroke-width="1.5"/>
                <path d="M24 16C26 13 28 12 32 12H42V25H17L24 16ZM47 12H58C62 12 65 14 68 18L72 25H47V12Z" fill="#D8F9FF" fill-opacity=".8"/>
                <circle cx="23" cy="42" r="6" fill="#071321" stroke="#A5C6D8" stroke-width="2"/>
                <circle cx="66" cy="42" r="6" fill="#071321" stroke="#A5C6D8" stroke-width="2"/>
                <path d="M7 31H13M79 31H84" stroke="#E9FAFF" stroke-width="2.5" stroke-linecap="round"/>
              </g>
            </g>
        </svg>
    </div>
</section>
""", unsafe_allow_html=True)

action_left, action_right, _ = st.columns([1.15, 1.55, 5])
with action_left:
    if st.button("Find Parking", key="hero_find_parking", use_container_width=True):
        st.session_state.page = "Park Vehicle"
        st.rerun()
with action_right:
    if st.button("View Parking Slots", key="hero_view_slots", use_container_width=True):
        st.session_state.page = "Parking Slots"
        st.rerun()


# ---------------- LIVE METRICS ----------------

# Sync before reading the current Java parking status.
sync_active_vehicles()

parking_status = get_status()
if parking_status is None:
    total = occupied = available = None
else:
    total, occupied, available = parking_status

registered_vehicles = get_user_vehicles(current_user)
owned_active_filter = (
    ""
    if current_user["role"] == "admin"
    else "AND owner_user_id = ?"
)
owned_active_values = (
    ()
    if current_user["role"] == "admin"
    else (current_user["id"],)
)
my_parked_count = db_query(
    """
    SELECT COUNT(*) AS count
    FROM parking_events
    WHERE exit_time IS NULL
    """ + owned_active_filter,
    owned_active_values
)[0]["count"]

st.markdown(
    f'**Welcome back, {html.escape(current_user["full_name"])}**'
    f' · {len(registered_vehicles)} registered vehicle'
    f'{"s" if len(registered_vehicles) != 1 else ""}'
)

m1, m2, m3, m4 = st.columns(4)

metric_icons = [
    '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 19V8l8-4 8 4v11M8 19v-6h8v6M4 10h16" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m5 15 1.5-5.2A2.5 2.5 0 0 1 8.9 8h6.2a2.5 2.5 0 0 1 2.4 1.8L19 15v4H5v-4Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><path d="M7 15h10M8 19v1m8-1v1M7 11h10" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>',
    '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 19V8l8-4 8 4v11M8 19v-6h8v6M4 10h16" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/><path d="m9 10 2 2 4-4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="9" cy="8" r="3" stroke="currentColor" stroke-width="1.7"/><path d="M3.5 19v-1.5A4.5 4.5 0 0 1 8 13h2a4.5 4.5 0 0 1 4.5 4.5V19M16 5.5a3 3 0 0 1 0 5.8m1 2a4.5 4.5 0 0 1 3.5 4.4V19" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>'
]

for metric_index, (col, label, value, icon) in enumerate([
    (m1, "Total Slots", total, metric_icons[0]),
    (m2, "Occupied Slots", occupied, metric_icons[1]),
    (m3, "Available Slots", available, metric_icons[2]),
    (
        m4,
        "Parked Vehicles" if current_user["role"] == "admin"
        else "Your Parked Vehicles",
        occupied if current_user["role"] == "admin" else my_parked_count,
        metric_icons[3]
    )
]):
    with col:
        st.markdown(
            f'<div class="metric-card" style="animation-delay: {metric_index * 90}ms">'
            f'<div class="metric-head"><span class="metric-icon">{icon}</span>'
            f'<span class="metric-live">LIVE</span></div>'
            f'<p>{label}</p>'
            f'<h2>{value if value is not None else "—"}</h2></div>',
            unsafe_allow_html=True
        )

if parking_status is None:
    st.error("Parking server is unavailable. Live statistics and slot data are not available.")

st.divider()


# ---------------- DASHBOARD ----------------

page = st.session_state.page

if page == "Dashboard":
    slots = get_slots()
    st.subheader("Parking Occupancy Overview")
    if parking_status is not None and total:
        occupancy_percent = round((occupied / total) * 100)
        st.markdown(
            '<div class="occupancy-panel">'
            '<div class="activity-topline"><span>Live occupancy</span>'
            f'<span>{occupancy_percent}% · {occupied} of {total} spaces</span></div>'
            '<div class="occupancy-track"><div class="occupancy-fill" '
            f'style="width: {occupancy_percent}%"></div></div>'
            f'<small>{available} spaces currently available</small>'
            '</div>',
            unsafe_allow_html=True
        )

    quick_left, quick_right, _ = st.columns([1, 1, 5])
    with quick_left:
        if st.button("＋  Park vehicle", key="dashboard_park", use_container_width=True):
            st.session_state.page = "Park Vehicle"
            st.rerun()
    with quick_right:
        if st.button("−  Remove vehicle", key="dashboard_remove", use_container_width=True):
            st.session_state.page = "Remove Vehicle"
            st.rerun()

    st.subheader("Live Parking Layout")
    if parking_status is not None:
        render_slot_layout(slots, "dashboard", current_user)
    else:
        st.info("Start the Java parking server to view live parking spaces.")

    st.subheader("Vehicle Search")
    search_registration, search_color = st.columns(2)
    with search_registration:
        with st.form("dashboard_registration_search"):
            registration_query = st.text_input(
                "Search by registration",
                key="dashboard_registration_query"
            ).strip().upper()
            registration_submitted = st.form_submit_button(
                "⌕  Find vehicle",
                use_container_width=True
            )
        if registration_submitted:
            if not registration_query:
                st.warning("Enter a registration number to search.")
            elif not vehicle_is_owned(registration_query, current_user):
                st.info("Vehicle not found or you do not have permission to view it.")
            else:
                response = send_to_java(f"FIND|{registration_query}")
                parts = response.split("|")
                if len(parts) == 5 and parts[0] == "FOUND":
                    st.success(
                        f'{parts[1]} · {parts[2]} {parts[3]} · '
                        f'Slot P{int(parts[4]):02d}'
                    )
                else:
                    st.info(response.replace("|", " "))
    with search_color:
        with st.form("dashboard_color_search"):
            color_query = st.text_input(
                "Search by vehicle color",
                key="dashboard_color_query"
            ).strip()
            color_submitted = st.form_submit_button(
                "◉  Find color",
                use_container_width=True
            )
        if color_submitted:
            if not color_query:
                st.warning("Enter a vehicle color to search.")
            elif "|" in color_query:
                st.warning("Vehicle colors cannot contain the '|' character.")
            else:
                response = send_to_java(f"COLOR|{color_query}")
                parts = response.split("|")
                matching_records = [
                    {
                        "Registration": parts[index],
                        "Color": parts[index + 1],
                        "Type": parts[index + 2],
                        "Slot": f'P{int(parts[index + 3]):02d}'
                    }
                    for index in range(1, len(parts) - 3, 4)
                ] if parts[0] == "COLOR" else []
                records = [
                    record for record in matching_records
                    if vehicle_is_owned(record["Registration"], current_user)
                ]
                if records:
                    st.dataframe(
                        pd.DataFrame(records),
                        hide_index=True,
                        use_container_width=True
                    )
                else:
                    st.info("No currently parked vehicles match that color.")

    st.subheader("Your Vehicle Types" if current_user["role"] != "admin" else "Vehicle Types")
    active_owner_filter = (
        ""
        if current_user["role"] == "admin"
        else "AND owner_user_id = ?"
    )
    active_values = (
        ()
        if current_user["role"] == "admin"
        else (current_user["id"],)
    )
    category_counts = db_query(
        """
        SELECT vehicle_type, COUNT(*) AS parked
        FROM parking_events
        WHERE exit_time IS NULL
        """ + active_owner_filter + """
        GROUP BY vehicle_type
        """,
        active_values
    )
    parked_by_type = {
        item["vehicle_type"]: item["parked"]
        for item in category_counts
    }
    if registered_vehicles:
        category_columns = st.columns(4)
        for index, vehicle_type in enumerate(VEHICLE_TYPES):
            owned_count = sum(
                vehicle["vehicle_type"] == vehicle_type
                for vehicle in registered_vehicles
            )
            if owned_count:
                with category_columns[index % len(category_columns)]:
                    st.markdown(
                        '<div class="activity-card">'
                        f'<div class="activity-topline"><span>'
                        f'{VEHICLE_ICONS[vehicle_type]} '
                        f'{html.escape(vehicle_type)}</span></div>'
                        f'<small>{owned_count} registered · '
                        f'{parked_by_type.get(vehicle_type, 0)} currently parked</small>'
                        '</div>',
                        unsafe_allow_html=True
                    )

    history = db_query("""
        SELECT registration, color, vehicle_type, slot,
               entry_time, exit_time, fee
        FROM parking_events
        WHERE 1 = 1
    """ + ("" if current_user["role"] == "admin"
           else " AND owner_user_id = ?") + """
        ORDER BY id DESC
        LIMIT 6
    """, () if current_user["role"] == "admin" else (current_user["id"],))

    activity_column, revenue_column = st.columns([1.7, 1])
    with activity_column:
        st.subheader("Recent Vehicle Activity")
        if history:
            for activity_index, event in enumerate(history):
                event_label = "Vehicle exited" if event["exit_time"] else "Vehicle parked"
                event_time = event["exit_time"] or event["entry_time"]
                st.markdown(
                    f'<div class="activity-card" style="animation-delay: {activity_index * 55}ms">'
                    f'<div class="activity-topline"><span>{html.escape(event_label)} · '
                    f'{html.escape(event["registration"])}</span>'
                    f'<small>{"P%02d" % event["slot"] if event["slot"] else "Slot —"}</small></div>'
                    f'<small>{html.escape(event["color"])} {html.escape(event["vehicle_type"])} '
                    f'· {html.escape(event_time)}</small></div>',
                    unsafe_allow_html=True
                )
        else:
            st.info("Vehicle activity will appear here after the first parking event.")

    with revenue_column:
        st.subheader("Parking Revenue")
        revenue = db_query(
            """
            SELECT COALESCE(SUM(amount), 0) AS total,
                   COUNT(*) AS payments
            FROM payments
            WHERE 1 = 1
            """ + (
                ""
                if current_user["role"] == "admin"
                else " AND owner_user_id = ?"
            ),
            ()
            if current_user["role"] == "admin"
            else (current_user["id"],)
        )[0]
        st.markdown(
            '<div class="metric-card">'
            '<p>Total recorded fees</p>'
            f'<h2>₹{float(revenue["total"]):,.2f}</h2>'
            f'<p>{revenue["payments"]} completed payments</p>'
            '</div>',
            unsafe_allow_html=True
        )


# ---------------- VEHICLE REGISTRATION AND PROFILE ----------------

elif page == "My Vehicles":
    st.subheader("Vehicle fleet")
    vehicles = get_user_vehicles(current_user)
    type_filter = st.selectbox(
        "Filter by vehicle type",
        ["All vehicle types"] + sorted({
            vehicle["vehicle_type"] for vehicle in vehicles
        })
    )
    visible_vehicles = [
        vehicle for vehicle in vehicles
        if type_filter == "All vehicle types"
        or vehicle["vehicle_type"] == type_filter
    ]
    owner_clause = "" if current_user["role"] == "admin" else "AND owner_user_id = ?"
    owner_values = () if current_user["role"] == "admin" else (current_user["id"],)
    active_records = db_query(
        """
        SELECT registration, slot, vehicle_type
        FROM parking_events
        WHERE exit_time IS NULL
        """ + owner_clause,
        owner_values
    )
    active_by_registration = {
        record["registration"].upper(): record
        for record in active_records
    }
    if visible_vehicles:
        cards = st.columns(3)
        for index, vehicle in enumerate(visible_vehicles):
            active_record = active_by_registration.get(
                vehicle["registration"].upper()
            )
            parking_slot_label = (
                f'P{active_record["slot"]:02d}'
                if active_record else "Not parked"
            )
            owner_note = (
                f'<small>Owner: {html.escape(vehicle["owner_name"])}</small>'
                if current_user["role"] == "admin" else ""
            )
            with cards[index % len(cards)]:
                st.markdown(
                    '<div class="activity-card">'
                    f'<div class="activity-topline"><span>'
                    f'{VEHICLE_ICONS.get(vehicle["vehicle_type"], "🚘")} '
                    f'{html.escape(vehicle["registration"])}</span>'
                    f'<small>{parking_slot_label}</small></div>'
                    f'<small>{html.escape(vehicle["vehicle_type"])} · '
                    f'{html.escape(vehicle["color"])}</small>{owner_note}</div>',
                    unsafe_allow_html=True
                )
    else:
        st.info("No vehicles match this filter. Register a vehicle to get started.")

elif page == "Register Vehicle":
    st.subheader("Register a vehicle")
    owner_accounts = (
        db_query("SELECT id, full_name, email FROM users ORDER BY full_name")
        if current_user["role"] == "admin"
        else [current_user]
    )
    owner_by_label = {
        f'{account["full_name"]} · {account["email"]}': account["id"]
        for account in owner_accounts
    }
    with st.form("register_vehicle_form"):
        if current_user["role"] == "admin":
            owner_label = st.selectbox(
                "Vehicle owner",
                list(owner_by_label)
            )
            vehicle_owner_id = owner_by_label[owner_label]
        else:
            vehicle_owner_id = current_user["id"]
        registration = st.text_input(
            "Registration Number",
            max_chars=32
        ).strip().upper()
        vehicle_type = st.selectbox("Vehicle Type", VEHICLE_TYPES)
        color = st.text_input("Vehicle Color", max_chars=40).strip()
        save_vehicle = st.form_submit_button(
            "Save vehicle",
            use_container_width=True
        )
    if save_vehicle:
        if not registration or not color:
            st.error("Registration number and color are required.")
        elif "|" in registration or "|" in color:
            st.error("Vehicle details cannot contain the '|' character.")
        else:
            saved, message = register_vehicle(
                vehicle_owner_id, registration, vehicle_type, color
            )
            st.success(message) if saved else st.error(message)

elif page == "My Profile":
    st.subheader("My Profile")
    st.caption(f'Signed in as {current_user["email"]} · {current_user["role"].title()}')
    with st.form("profile_form"):
        full_name = st.text_input(
            "Full Name",
            value=current_user["full_name"],
            max_chars=100
        ).strip()
        mobile = st.text_input(
            "Mobile Number",
            value=current_user["mobile"] or "",
            max_chars=20
        ).strip()
        save_profile = st.form_submit_button(
            "Save profile",
            use_container_width=True
        )
    if save_profile:
        if not full_name:
            st.error("Full name is required.")
        elif mobile and (
            len(mobile) < 7
            or any(not (character.isdigit() or character in "+- ()")
                   for character in mobile)
        ):
            st.error("Enter a valid mobile number or leave it blank.")
        else:
            db_execute(
                "UPDATE users SET full_name = ?, mobile = ? WHERE id = ?",
                (full_name, mobile or None, current_user["id"])
            )
            st.success("Profile updated.")
            st.rerun()

    with st.form("change_password_form"):
        st.markdown("#### Change password")
        old_password = st.text_input("Current Password", type="password")
        new_password = st.text_input(
            "New Password (at least 12 characters)",
            type="password"
        )
        new_password_confirm = st.text_input(
            "Confirm New Password",
            type="password"
        )
        change_password = st.form_submit_button(
            "Update password",
            use_container_width=True
        )
    if change_password:
        saved_hash = db_query(
            "SELECT password_hash FROM users WHERE id = ?",
            (current_user["id"],)
        )[0]["password_hash"]
        if not verify_password(old_password, saved_hash):
            st.error("Current password is incorrect.")
        elif len(new_password) < 12:
            st.error("Choose a password with at least 12 characters.")
        elif new_password != new_password_confirm:
            st.error("The new passwords do not match.")
        else:
            db_execute(
                """
                UPDATE users
                SET password_hash = ?, session_version = session_version + 1
                WHERE id = ?
                """,
                (hash_password(new_password), current_user["id"])
            )
            st.session_state.user_session_version += 1
            st.success("Password updated. Other signed-in sessions have been signed out.")

elif page == "User Management" and current_user["role"] == "admin":
    st.subheader("Registered users")
    users = db_query(
        """
        SELECT id, full_name AS Name, email AS Email, mobile AS Mobile,
               role AS Role, created_at AS "Created At"
        FROM users
        ORDER BY id
        """
    )
    if users:
        st.dataframe(
            pd.DataFrame(users),
            hide_index=True,
            use_container_width=True
        )

elif page == "Fee Settings" and current_user["role"] == "admin":
    st.subheader("Parking fee settings")
    current_car_rate, current_bike_rate = get_parking_rates()
    with st.form("fee_settings_form"):
        updated_car_rate = st.number_input(
            "Car, van, and heavy-vehicle rate per hour (₹)",
            min_value=0.0,
            max_value=100000.0,
            value=current_car_rate,
            step=5.0
        )
        updated_bike_rate = st.number_input(
            "Motorcycle, scooter, and bicycle rate per hour (₹)",
            min_value=0.0,
            max_value=100000.0,
            value=current_bike_rate,
            step=5.0
        )
        save_rates = st.form_submit_button(
            "Save rates",
            use_container_width=True
        )
    if save_rates:
        with sqlite3.connect(DB_PATH) as conn:
            conn.executemany(
                """
                INSERT INTO parking_settings (setting_key, setting_value)
                VALUES (?, ?)
                ON CONFLICT(setting_key)
                DO UPDATE SET setting_value = excluded.setting_value
                """,
                (
                    ("car_rate", str(updated_car_rate)),
                    ("bike_rate", str(updated_bike_rate))
                )
            )
        st.success("Parking fee rates updated.")
        st.rerun()


# ---------------- PARK VEHICLE ----------------

elif page == "Park Vehicle":
    st.subheader("Park a Vehicle")

    with st.form("park_form"):
        registration = st.text_input(
            "Registration Number",
            max_chars=32
        ).strip().upper()
        color = st.text_input("Vehicle Color", max_chars=40).strip()
        vehicle_type = st.selectbox("Vehicle Type", VEHICLE_TYPES)
        submitted = st.form_submit_button(
            "Park Vehicle", use_container_width=True
        )

    if submitted:
        if not registration or not color:
            st.error(
                "Registration number aur color required hain."
            )
        elif any("|" in value for value in (
            registration, color, vehicle_type
        )):
            st.error("Vehicle details mein '|' character use nahi kar sakte.")
        else:
            registered = db_query(
                """
                SELECT owner_user_id
                FROM vehicles
                WHERE UPPER(registration) = ?
                """,
                (registration,)
            )
            if (
                registered
                and current_user["role"] != "admin"
                and registered[0]["owner_user_id"] != current_user["id"]
            ):
                st.error("That registration is associated with another account.")
            else:
                vehicle_owner_id = (
                    registered[0]["owner_user_id"]
                    if registered else current_user["id"]
                )
                saved, message = register_vehicle(
                    vehicle_owner_id, registration, vehicle_type, color
                )
                if not saved:
                    st.error(message)
                else:
                    response = send_to_java(
                        f"PARK|{registration}|{color}|{vehicle_type}"
                    )
                    parts = response.split("|")

                    if (
                        len(parts) >= 6
                        and parts[0] == "OK"
                        and parts[1] == "Vehicle parked"
                    ):
                        slot = int(parts[5])
                        record_entry(
                            vehicle_owner_id,
                            registration,
                            color,
                            vehicle_type,
                            slot
                        )
                        st.session_state.slot_animation = {
                            "action": "entry",
                            "slot": slot
                        }
                        st.success(
                            f"Vehicle parked successfully at Slot {slot}."
                        )
                        st.rerun()
                    else:
                        st.error(response.replace("|", " "))


# ---------------- REMOVE VEHICLE ----------------

elif page == "Remove Vehicle":
    st.subheader("Remove a Vehicle")

    with st.form("remove_form"):
        registration = st.text_input(
            "Registration Number",
            key="remove_registration"
        ).strip().upper()
        submitted = st.form_submit_button(
            "Remove Vehicle", use_container_width=True
        )

    if submitted:
        if not registration:
            st.error("Registration number enter karo.")
        elif not vehicle_is_owned(registration, current_user):
            st.error("Vehicle not found or you do not have permission to remove it.")
        else:
            response = send_to_java(
                f"REMOVE|{registration}"
            )

            if response.startswith("OK|"):
                removal_parts = response.split("|")
                if len(removal_parts) == 4 and removal_parts[3].isdigit():
                    st.session_state.slot_animation = {
                        "action": "exit",
                        "slot": int(removal_parts[3])
                    }
                fee = record_exit(registration, current_user)

                if fee is None:
                    st.success(
                        "Vehicle removed. Is session ka history "
                        "record database mein nahi mila."
                    )
                else:
                    st.success(
                        f"Vehicle removed. Parking fee due: ₹{fee:.2f}. "
                        "Open Payments to complete it securely."
                    )

                st.rerun()
            else:
                st.error(response.replace("|", " "))


# ---------------- SEARCH VEHICLE ----------------

elif page == "Search Vehicle":
    st.subheader("Search by Registration Number")

    with st.form("search_form"):
        registration = st.text_input(
            "Registration Number"
        ).strip().upper()
        submitted = st.form_submit_button("Search")

    if submitted:
        if not registration:
            st.warning("Enter a registration number.")
        elif not vehicle_is_owned(registration, current_user):
            st.info("Vehicle not found or you do not have permission to view it.")
        else:
            response = send_to_java(f"FIND|{registration}")
            parts = response.split("|")

            if len(parts) == 5 and parts[0] == "FOUND":
                st.success("Vehicle found.")

                st.dataframe(
                    pd.DataFrame([{
                        "Registration": parts[1],
                        "Color": parts[2],
                        "Type": parts[3],
                        "Slot": parts[4]
                    }]),
                    hide_index=True,
                    use_container_width=True
                )
            else:
                st.warning(response.replace("|", " "))


# ---------------- SEARCH BY COLOR ----------------

elif page == "Search by Color":
    st.subheader("Search Vehicles by Color")

    live_slots = get_slots()
    live_colors = sorted({
        slot["Color"]
        for slot in live_slots
        if slot["Color"]
    }, key=str.casefold)

    with st.form("color_form"):
        color_mode = st.radio(
            "Choose a color source",
            ["Currently parked colors", "Enter a color"],
            horizontal=True
        )
        if color_mode == "Currently parked colors" and live_colors:
            owned_live_colors = sorted({
                slot["Color"]
                for slot in live_slots
                if slot["Color"] and (
                    current_user["role"] == "admin"
                    or vehicle_is_owned(slot["Registration"], current_user)
                )
            }, key=str.casefold)
            color = st.selectbox(
                "Vehicle Color",
                owned_live_colors or ["No visible parked vehicle colors"]
            )
        else:
            color = st.text_input(
                "Vehicle Color",
                placeholder="For example: blue"
            )
        submitted = st.form_submit_button(
            "⌕  Search vehicles",
            use_container_width=True
        )

    if submitted:
        if not color:
            st.warning("Color enter karo.")
        elif "|" in color:
            st.warning("Color mein '|' character use nahi kar sakte.")
        else:
            response = send_to_java(f"COLOR|{color}")
            parts = response.split("|")
            records = []

            if parts[0] == "COLOR":
                data = parts[1:]

                for i in range(0, len(data), 4):
                    if i + 3 < len(data):
                        if (
                            current_user["role"] == "admin"
                            or vehicle_is_owned(data[i], current_user)
                        ):
                            records.append({
                                "Registration": data[i],
                                "Color": data[i + 1],
                                "Type": data[i + 2],
                                "Slot": data[i + 3]
                            })

                if records:
                    result_columns = st.columns(min(len(records), 3))
                    for index, record in enumerate(records):
                        with result_columns[index % len(result_columns)]:
                            st.markdown(
                                '<div class="activity-card">'
                                f'<div class="activity-topline">'
                                f'<span>{html.escape(record["Registration"])}</span>'
                                f'<small>P{int(record["Slot"]):02d}</small></div>'
                                f'<small>{html.escape(record["Color"])} · '
                                f'{html.escape(record["Type"])}</small></div>',
                                unsafe_allow_html=True
                            )
                else:
                    st.info("No currently parked vehicles match that color.")
            else:
                st.info(response.replace("|", " "))


# ---------------- PARKING SLOTS ----------------

elif page == "Parking Slots":
    st.subheader("All Parking Slots")
    slots = get_slots()

    if parking_status is not None and slots:
        render_slot_layout(slots, "parking_slots", current_user)
    else:
        st.error("Parking server slot data is not available.")


# ---------------- PARKING HISTORY ----------------

elif page == "Parking History":
    st.subheader("Parking History")

    owner_filter = (
        ""
        if current_user["role"] == "admin"
        else "AND owner_user_id = ?"
    )
    owner_values = (
        ()
        if current_user["role"] == "admin"
        else (current_user["id"],)
    )
    records = db_query("""
        SELECT registration AS Registration,
               color AS Color,
               vehicle_type AS Type,
               slot AS Slot,
               entry_time AS Entry,
               exit_time AS Exit,
               fee AS Fee
        FROM parking_events
        WHERE 1 = 1
    """ + owner_filter + """
        ORDER BY id DESC
    """, owner_values)

    if records:
        st.dataframe(
            pd.DataFrame(records),
            hide_index=True,
            use_container_width=True
        )

        csv_data = (
            pd.DataFrame(records)
            .to_csv(index=False)
            .encode("utf-8")
        )

        st.download_button(
            "Download History CSV",
            csv_data,
            file_name="goparking_history.csv",
            mime="text/csv"
        )
    else:
        st.info("Abhi parking history available nahi hai.")


# ---------------- FEE CALCULATOR ----------------

elif page == "Fee Calculator":
    st.subheader("Parking Fee Calculator")

    car_rate, bike_rate = get_parking_rates()
    st.write(f"Car rate: ₹{car_rate:g} per hour")
    st.write(f"Motorcycle, scooter, and bicycle rate: ₹{bike_rate:g} per hour")

    with st.form("fee_form"):
        vehicle_type = st.selectbox("Vehicle Type", VEHICLE_TYPES)
        hours = st.number_input(
            "Parking Duration (hours)",
            min_value=1,
            max_value=720,
            value=1
        )
        submitted = st.form_submit_button("Calculate Fee")

    if submitted:
        rate = (
            bike_rate
            if vehicle_type.lower() in {
                "bike", "motorcycle", "scooter", "bicycle"
            }
            else car_rate
        )
        fee = rate * hours
        st.metric("Estimated Parking Fee", f"₹{fee:.2f}")
        st.caption(
            "Actual fee on exit is calculated from "
            "recorded entry and exit times."
        )


# ---------------- PAYMENTS ----------------

elif page == "Payments":
    st.subheader("Parking Fees and Payments")
    st.caption(
        "A fee is not marked paid until Razorpay confirms it and the server "
        "verifies the payment."
    )

    payment_owner_filter = (
        ""
        if current_user["role"] == "admin"
        else "AND owner_user_id = ?"
    )
    payment_owner_values = (
        ()
        if current_user["role"] == "admin"
        else (current_user["id"],)
    )
    payments = db_query("""
        SELECT id, event_id, owner_user_id, registration,
               amount, amount_paise, payment_status,
               COALESCE(created_at, paid_at) AS fee_date,
               razorpay_order_id, razorpay_payment_id
        FROM payments
        WHERE 1 = 1
    """ + payment_owner_filter + """
        ORDER BY id DESC
    """, payment_owner_values)

    if payments:
        payment_display = [
            {
                "Registration": payment["registration"],
                "Amount": f"₹{float(payment['amount']):.2f}",
                "Status": payment["payment_status"],
                "Fee Date": payment["fee_date"]
            }
            for payment in payments
        ]
        st.dataframe(
            pd.DataFrame(payment_display),
            hide_index=True,
            use_container_width=True
        )

        total_paid = sum(
            float(payment["amount"])
            for payment in payments
            if payment["payment_status"] == "PAID"
        )
        if total_paid:
            st.metric("Razorpay-verified payments", f"₹{total_paid:.2f}")

        if not os.environ.get("RAZORPAY_KEY_ID"):
            st.warning(
                "Online payment is not configured. The administrator must "
                "set the server-side Razorpay Test Mode credentials."
            )
        else:
            st.caption(
                "Checkout links expire after 15 minutes. The GoParking "
                "payment API must be running."
            )
            for payment in payments:
                if (
                    payment["event_id"] is not None
                    and payment["owner_user_id"] == current_user["id"]
                    and payment["payment_status"] in {
                        "CREATED", "PENDING", "FAILED"
                    }
                ):
                    checkout_url = create_checkout_url(payment["id"])
                    if checkout_url:
                        st.link_button(
                            f"Pay ₹{float(payment['amount']):.2f} "
                            f"for {payment['registration']}",
                            checkout_url,
                            key=f"pay_fee_{payment['id']}",
                            use_container_width=True
                        )
    else:
        st.info("Abhi koi fee record nahi hai.")


# ---------------- FOOTER ----------------

st.divider()
st.caption(
    "GoParking | Java DSA + Python Streamlit + SQLite"
)