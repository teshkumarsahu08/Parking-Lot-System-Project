# GoParking: Smart Parking Management System

## Abstract

GoParking is a local parking management application combining a Streamlit
interface, a Java allocation engine, and SQLite persistence. It supports
account registration and sign-in, account-owned vehicle records, live parking
operations, history, fee estimates, and recorded payments. An administrator
can view system-wide records and configure hourly rates. The Java engine
selects the lowest available numbered space using its existing data
structures. Locally bundled Unsplash photographs provide page-specific
parking backgrounds beneath dark overlays and translucent UI cards.

The application is intended for learning and local demonstration. It is not
a payment service or a hardened multi-tenant deployment.

## Problem statement

Manual parking operations make it difficult to identify the next free space,
track entry and exit events, and provide drivers with a current view of lot
occupancy. The project demonstrates how an interactive web application can
coordinate these tasks with a separate Java parking engine and persistent
records.

## Objectives

- Display capacity and live space status in a web interface.
- Allocate and release spaces without replacing the existing Java algorithm.
- Keep a record of parking events and calculated fees.
- Associate registered vehicles and their history with user accounts.
- Provide role-aware administrator views and fee-rate configuration.
- Support vehicle search, responsive presentation, and reduced-motion users.

## Scope

The Java model manages ten numbered spaces and assigns the lowest available
number. The web application communicates with Java through a local,
line-oriented TCP protocol. SQLite stores accounts, registered vehicles,
parking events, fee settings, and payments. It does not store card details or
communicate with a payment provider.

Supported vehicle categories include motorcycles, scooters, bicycles,
hatchback cars, sedans, SUVs, electric cars, vans, pickup trucks, buses,
trucks, and legacy `Car`, `Bike`, and `Other` types. The lot currently does
not differentiate slot dimensions, reservations, or vehicle-specific
capacity.

## Design and implementation

Streamlit provides the public landing page and authenticated app views.
Account passwords are stored as salted PBKDF2-HMAC-SHA256 hashes. A first
administrator is created from environment variables when no admin account
exists. Regular registrations receive the user role. The application scopes
individual vehicle lookup, removal, history, and payment rows to the
authenticated owner, while administrators have system-wide views.

The Java `ParkingLot` class preserves a `TreeSet` of available slot numbers
and a `HashMap` from registration numbers to occupied slots. Python uses
parameterized SQLite operations for persistence. The dark interface includes
a full-width photo hero, page-specific garage backgrounds, translucent cards,
a dashboard illustration, parking layout, vehicle filters, and lightweight
animations that respect
`prefers-reduced-motion`.

## Results

The implementation provides account creation and login, user profiles and
password changes, vehicle registration and listing, live park/remove/search
operations, owner-filtered history and fees, administrator fee controls, and
a redesigned responsive UI. Focused automated tests cover password hashing,
hash verification, malformed hashes, and email-shape checks. Java sources
compile successfully with `javac`.

The Java and SQLite operations are separate and not a distributed
transaction. Java keeps active allocation state in memory and the app
attempts to restore active vehicles from SQLite after a restart.

## Limitations and future work

- Protect and authenticate every Java command before exposing the service
  beyond the local machine.
- Add automated integration tests for SQLite migrations, authorization,
  ownership, and full park/remove operations.
- Add durable allocation state and transactional coordination across the
  Java engine and database.
- Add secure password reset, audit logging, backups, and production session
  management.
- Add payment-provider integration only if required.
- Add reserved spaces or size-aware allocation only with an explicit
  business rule and a compatible data model.

## Conclusion

GoParking demonstrates a web-to-Java parking workflow while retaining its
existing DSA allocation approach. It now includes account-oriented data views
and a modern parking-focused interface. It remains a local project and
requires additional security, operational, and integration work before
internet-facing or commercial use.
