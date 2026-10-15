# GoParking Technical Documentation

## 1. Architecture

The project uses an existing Python Streamlit interface, Java parking engine,
and SQLite database:

1. Streamlit authenticates the current browser session and presents the UI.
2. Python connects to the Java server at `127.0.0.1:5000` for live parking
   operations.
3. The Java `ParkingLot` owns the in-memory slot allocation state.
4. Python writes the web app's account, vehicle, parking-event, fee, and
   payment records to `goparking.db`.
5. A separate Python payment API creates Razorpay orders, serves the checkout
   page, verifies checkout responses, and accepts signed webhooks.

The Java process is the allocation authority. SQLite history is not
transactionally coordinated with Java memory, so an application or process
failure between the two operations can leave the systems out of sync. On
startup, `sync_active_vehicles()` attempts to restore database events whose
exit time is still null.

An event with a null `exit_time` is treated as a vehicle that is still parked.
If an exit is not recorded, startup restoration will correctly reoccupy its
saved slot even if the physical vehicle has already left. Administrators
should reconcile a genuinely stale active record rather than changing Java
slot initialization or disabling restoration for legitimate active vehicles.

## 2. Components and files

```text
GoParking - Copy/
├── app.py
├── auth_security.py
├── payment_api.py
├── payment_storage.py
├── requirements.txt
├── goparking.db
├── .streamlit/
│   └── config.toml
├── static/
│   └── parking/
│       ├── aerial-parking.jpg
│       ├── multilevel-garage.jpg
│       └── underground-garage.jpg
├── tests/
│   ├── test_auth_security.py
│   └── ParkingLotSmokeTest.java
├── java_backend/
│   ├── Main.java
│   ├── ParkingServer.java
│   ├── ParkingLot.java
│   ├── ParkingSlot.java
│   ├── Vehicle.java
│   └── ParkingHistory.java
└── docs/
```

`app.py` contains Streamlit pages, SQL access, Java socket commands, and
inline HTML/CSS/SVG. `auth_security.py` contains password hashing and basic
email-shape validation. `payment_api.py` uses the official Razorpay Python
SDK and serves Standard Checkout.js from a separate HTTP process.
`payment_storage.py` applies the same non-destructive SQLite migration from
both the app and API. The Java sources preserve the existing console menu and
allocation model.

## 3. Identity, roles, and account scope

Accounts are stored in SQLite with unique case-insensitive email addresses,
name, optional mobile number, password hash, role, and creation timestamp.
Self-service registration always assigns the `user` role. Role is read from
the database on each Streamlit rerun; navigation alone is not the access
control. Administrator-only fee settings and user listing also check the
current role in the page branch.

Passwords use PBKDF2-HMAC-SHA256 with a random 16-byte salt and 600,000
iterations. The database stores the algorithm, iteration count, salt, and
digest—not the original password. Account passwords require at least 12
characters. Recovery email is not configured; users can change their
password after authenticating. Each account has a session version. The app
checks the signed-in version against the database on reruns; changing a
password increments it, revoking previous app sessions while updating the
current session to remain active.

Vehicle registry rows have one owner. Non-administrator vehicle lists,
history, payments, registration lookup, color results, and removal checks
are scoped to that owner. Slot status and overall occupancy remain shared,
but other users' registration, type, and color are hidden in the slot view.
Administrators can view system-wide records.

The Python app applies these ownership checks before it uses Java's
registration-based `FIND`, `COLOR`, or `REMOVE` commands. The Java protocol
itself has no user identity and is intended to remain local; it must not be
exposed as a network-facing authorization boundary.

## 4. Database and startup migration

`init_db()` creates `users`, `vehicles`, `parking_events`, `payments`, and
`parking_settings`. For an older database, it adds the session-version field
to `users`, nullable `owner_user_id` columns to events and payments, and
supporting indexes. The gateway migration adds nullable Razorpay identifiers and mode/key ID,
amount in paise, currency, status, event relationship, and timestamps to
`payments`; existing rows are retained and default to `RECORDED`, not
misrepresented as verified Razorpay payments. A separate
`razorpay_payment_capabilities` table stores expiring token hashes without
invalidating still-open checkout sessions on a Streamlit rerun. Unique
indexes prevent an event, order, payment, or token from being associated with
duplicate records. A webhook-event table deduplicates provider event IDs.

The first administrator is created only when no administrator exists and all
of these environment variables are configured:

- `GOPARKING_ADMIN_NAME`
- `GOPARKING_ADMIN_EMAIL`
- `GOPARKING_ADMIN_PASSWORD`

The initial admin bootstrap assigns legacy null-owner event/payment rows to
that admin and seeds a vehicle registry from recorded event history. This is
a one-time local migration. Back up `goparking.db` before running a new
version against important data.

The payment service uses `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, optional
`RAZORPAY_WEBHOOK_SECRET`, `GOPARKING_RAZORPAY_MODE`, `GOPARKING_DB_PATH`,
`GOPARKING_PAYMENT_API_URL`, and `GOPARKING_APP_URL`. It defaults to Test
Mode and requires the API key prefix to match the configured mode. The secret
is server-side only; the public Key ID is sent to Checkout.js.

## 5. Razorpay payment flow

1. After an owner removes a vehicle, `record_exit()` calculates the fee from
   the stored event and current server fee settings, then atomically updates
   the event and inserts a `CREATED` payment row with the amount in paise.
2. The authenticated Streamlit **Payments** page issues a random 15-minute
   checkout capability for an owned unpaid fee. Only its SHA-256 hash is
   stored, and multiple unexpired capabilities remain valid across reruns.
   The browser opens the payment API's Checkout page using the capability in
   a URL fragment; the fragment is removed before network requests.
3. The API resolves that capability to one stored payment and creates a
   Razorpay order with the stored amount/currency. The browser never supplies
   the authoritative amount.
4. Checkout returns the order ID, payment ID, and signature. The API verifies
   the signature with the server secret and fetches the payment from Razorpay.
   It checks order, amount, currency, and provider status before setting
   `PAID`; an authorized payment remains `PENDING`.
5. Signed `payment.captured` and `payment.failed` webhooks update status
   asynchronously. The API checks the HMAC over the exact raw body and stores
   event IDs for duplicate protection. Repeated verified callbacks are
   idempotent.

The API routes are:

| Method and route | Purpose |
|---|---|
| `POST /api/orders` | Create/reuse a server-calculated Razorpay order |
| `POST /api/verify` | Verify Checkout signature and fetch the payment |
| `POST /api/failed` | Confirm a failed attempt with Razorpay's API |
| `GET /api/status` | Return status for the capability-bound payment |
| `POST /api/webhooks/razorpay` | Verify/deduplicate asynchronous events |
| `GET /health` | Local process health check |

The checkout/status routes require a short-lived per-payment bearer
capability; Streamlit issues it only after its existing login and owner check.
This service does not independently authenticate user passwords or accept
browser-supplied user IDs. It applies per-client in-memory rate limits and
request-size/JSON/origin validation. Production must use HTTPS, a trusted
reverse proxy, managed secrets, and deployment-level rate limiting. The
development listener binds to localhost.

## 6. Java TCP protocol

The Python client opens one TCP connection per request, sends a UTF-8 command
terminated by a newline, and reads one response line. The Java server listens
on port 5000 on the local host.

| Command | Purpose |
|---|---|
| `STATUS` | Return total, occupied, and available counts |
| `SLOTS` | Return each slot and occupied vehicle fields |
| `PARK|registration|color|type` | Allocate the lowest-numbered available slot |
| `REMOVE|registration` | Remove an active vehicle |
| `FIND|registration` | Find one parked vehicle |
| `COLOR|color` | Find parked vehicles of a color |
| `RESTORE|registration|color|type|slot` | Restore an active database event |

Fields use `|` as a delimiter. The UI rejects that character in vehicle
registration and color fields. Java validates non-empty fields and supports
the vehicle-type allowlist in `ParkingLot.java`.

## 7. Allocation and fees

The Java parking lot uses a `TreeSet<Integer>` for free slot numbers. Adding
slots and selecting the lowest available slot are logarithmic operations;
the minimum is obtained with `first()`. A `HashMap` indexes registrations to
occupied slots for expected constant-time lookup and removal. Lists preserve
vehicle and parking-history order.

Fee calculation rounds elapsed parking time upward to whole hours and
charges a one-hour minimum. Motorcycle, scooter, bicycle, and legacy `Bike`
use the two-wheel rate; other categories use the car/vehicle rate. The rates
are editable by administrators and stored in `parking_settings`. Exit fees
are saved as `CREATED` payment records and are not represented as paid until
Razorpay confirms capture.

## 8. Interface and accessibility

The app uses inline CSS, an SVG garage illustration, responsive layout rules,
and lightweight transitions. Three optimized Unsplash photos are bundled
under `static/parking/`; `PARKING_PAGE_PHOTOS` selects a page-specific
photograph and a separate administrator dashboard background. Authenticated
page styling is applied after sidebar navigation is resolved.
`.streamlit/config.toml` enables Streamlit static file serving for the local
photos. Keep this configuration and the `static` directory when deploying.
A `prefers-reduced-motion` media rule suppresses decorative animations.
Streamlit widgets provide the forms, sidebar navigation, tables, and buttons.

## 9. Known operational limitations

- Java parking state is in memory and is reset when the Java server restarts;
  Python restoration is best effort.
- Java actions and SQLite updates are not one distributed transaction.
- The Java server has no authentication and must remain local/trusted.
- SQLite is a local single-file store without a separate migration framework.
- Payment refunds, payment reconciliation jobs, and production-grade
  distributed rate limiting are not implemented.
- A production multi-user deployment needs hardened session handling,
  transport security, server-side API authorization, database concurrency
  planning, backups, and monitoring.
