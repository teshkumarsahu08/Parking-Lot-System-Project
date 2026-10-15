# GoParking

GoParking is a local smart parking management application built with
Streamlit, a Java parking engine, and SQLite. Users can register accounts and
vehicles, view their own history and payments, and park or remove vehicles.
Administrators can view system-wide information and configure fee rates.

## Features

- Public landing page, account registration, login, profile, and password
  change.
- First administrator provisioned from environment variables on startup.
- Role-aware navigation and user/admin account data access.
- Account-owned vehicle registrations, parking events, history, and payments.
- Live parking availability, selection, vehicle lookup, and color search.
- Parking history export, fee estimates, configurable per-hour fee rates, and
  recorded payments.
- Vehicle categories including motorcycles, scooters, bicycles, cars, vans,
  trucks, and buses.
- Dark automotive-inspired interface with a responsive layout and
  reduced-motion support.
- Locally bundled, optimized Unsplash parking photographs used as page-specific
  backgrounds.

The Java engine remains the allocator. It chooses the lowest-numbered free
slot and currently models only available or occupied spaces; reserved parking
and vehicle-size-specific allocation are not implemented. Fee totals are
application records, not payment-gateway transactions.

## Requirements

- Python with Streamlit and pandas installed.
- A JDK to compile the Java sources if compiled classes are unavailable.
- Two local processes: the Java server on `127.0.0.1:5000` and Streamlit.

No dependency manifest or Java build configuration is included.

## Parking photographs

Optimized JPEG photographs are served locally from `static/parking/`, so
application pages do not need to fetch background photos from a third-party
host at runtime. The image sources are Unsplash:

| Local image | Source |
|---|---|
| `aerial-parking.jpg` | [Unsplash photo 1506521781263-d8422e82f27a](https://images.unsplash.com/photo-1506521781263-d8422e82f27a) |
| `multilevel-garage.jpg` | [Unsplash photo 1573348722427-f1d6819fdf98](https://images.unsplash.com/photo-1573348722427-f1d6819fdf98) |
| `underground-garage.jpg` | [Unsplash photo 1590674899484-d5640e854abe](https://images.unsplash.com/photo-1590674899484-d5640e854abe) |

The images are used under the
[Unsplash License](https://unsplash.com/license).

## First administrator

Set all three values in the environment used to start Streamlit. Use a
password of at least 12 characters:

```cmd
set GOPARKING_ADMIN_NAME=Parking Administrator
set GOPARKING_ADMIN_EMAIL=admin@example.com
set GOPARKING_ADMIN_PASSWORD=replace-with-a-long-unique-password
```

On first startup, GoParking creates the administrator account and stores a
salted PBKDF2-HMAC-SHA256 password hash. Existing unowned historical events
and payments are assigned to this first administrator, and vehicle records
are seeded from history. Once an administrator exists, these variables are
not used to change that account. Do not commit real credentials or use the
example values.

## Run on Windows Command Prompt

In one Command Prompt window, compile if needed and start the Java server:

```cmd
cd /d "C:\path\to\GoParking - Copy\java_backend"
javac *.java
java -cp . ParkingServer
```

In another Command Prompt window, set the administrator variables (for the
first run only) and start the app:

```cmd
cd /d "C:\path\to\GoParking - Copy"
set GOPARKING_ADMIN_NAME=Parking Administrator
set GOPARKING_ADMIN_EMAIL=admin@example.com
set GOPARKING_ADMIN_PASSWORD=replace-with-a-long-unique-password
streamlit run app.py
```

Open the local URL printed by Streamlit, normally `http://localhost:8501`.
For more details and troubleshooting, see
[SETUP_AND_USAGE.md](./SETUP_AND_USAGE.md).

## Project documentation

- [Project report](./PROJECT_REPORT.md)
- [Technical documentation](./TECHNICAL_DOCUMENTATION.md)
- [DSA documentation](./DSA_DOCUMENTATION.md)
- [Setup and usage](./SETUP_AND_USAGE.md)
- [Testing documentation](./TESTING_DOCUMENTATION.md)
- [Viva questions and answers](./VIVA_QUESTIONS.md)
- [Architecture and UML diagrams](./DIAGRAMS.md)

## Limitations

This is a local learning project, not a production-ready multi-tenant service.
The Java TCP server accepts local commands without account credentials; keep
it bound to a trusted local environment and do not expose port 5000. Streamlit
session state and the single SQLite database are not a substitute for
production identity, authorization, backup, or concurrency controls. Password
recovery by email and online payment processing are not implemented.
