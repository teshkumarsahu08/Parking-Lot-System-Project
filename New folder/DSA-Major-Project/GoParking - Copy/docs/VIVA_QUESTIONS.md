# GoParking Viva Questions and Answers

### 1. What is GoParking?

It is a local parking management application with a Streamlit UI, Java
parking engine, and SQLite persistence.

### 2. Why are Python and Java both used?

Python provides the web UI, authentication, and database integration. Java
preserves the existing parking allocation implementation and its data
structures.

### 3. How does Python communicate with Java?

Python sends one newline-terminated command over a TCP socket to the local
Java server on port 5000 and reads one response line.

### 4. How is the next free slot selected?

The Java `ParkingLot` stores available slot numbers in a `TreeSet` and reads
the smallest value with `first()`.

### 5. What is the role of the `HashMap`?

It maps normalized registration numbers to occupied `ParkingSlot` instances
for expected constant-time vehicle lookups.

### 6. Why normalize registrations to uppercase?

It makes registration lookup and duplicate detection case-insensitive.

### 7. Where are durable records stored?

Account, vehicle registry, event, fee-setting, and payment records are stored
in SQLite. Active Java allocation state is in memory and is restored on app
startup on a best-effort basis.

### 8. How are passwords stored?

The app uses PBKDF2-HMAC-SHA256 with a unique random salt and stores the
iteration count, salt, and digest rather than plaintext.

### 9. How does the first administrator get created?

The app reads `GOPARKING_ADMIN_NAME`, `GOPARKING_ADMIN_EMAIL`, and
`GOPARKING_ADMIN_PASSWORD` when there is no admin. It creates one account
after validating the supplied values.

### 10. How are previous sessions revoked after a password change?

Each account has a session-version number. The app compares it with the
version held by the signed-in session; changing the password increments the
database value, invalidating sessions with the older version.

### 11. How are users' vehicles isolated?

Every registry entry has an owner ID. The app filters user-facing lookups,
events, history, and payments by the logged-in owner's ID, and checks
ownership before sending lookup/removal commands to Java.

### 12. Can regular users assign themselves the admin role?

No. Self-service registration inserts accounts with the `user` role. Admin
pages are conditionally shown and their page handlers check the database
role.

### 13. How are fees calculated?

Elapsed time is rounded up to whole hours with a one-hour minimum. Two-wheel
vehicle types use one configured rate; other types use the vehicle rate.

### 14. Does the app process real payments?

No. It records calculated fees in a payments table; it has no external
payment gateway or card-processing integration.

### 15. What happens if the Java server restarts?

Its in-memory slots are cleared. On startup, Python attempts to restore
vehicles with active SQLite event records and recorded slots.

### 16. What are the main security limitations?

The Java TCP protocol has no account authentication, and the project lacks
production-grade session management, transport security, password-reset
email, and operational controls. Keep the Java server local and do not
expose this learning project directly to the internet.
