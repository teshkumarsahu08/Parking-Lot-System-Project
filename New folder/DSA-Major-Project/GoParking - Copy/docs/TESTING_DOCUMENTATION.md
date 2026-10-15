# GoParking Testing Documentation

## Automated tests

The focused Python tests cover password/email security and Razorpay payment
storage, order, verification, and webhook behavior:

- `tests/test_auth_security.py` covers salted password hashes, wrong-password
  rejection, malformed hashes, and basic email-shape validation.
- `tests/test_payment_integration.py` covers non-destructive/repeatable
  migration, legacy-row preservation, capability scoping, server-derived
  order amounts, invalid signatures, incorrect amounts, idempotent capture,
  webhook signature validation, duplicate delivery, and wrong amounts.

Run it from the project folder:

```cmd
python -m unittest discover -s tests -v
```

The source files can be syntax-checked with Python's compile step without
executing the Streamlit UI:

```cmd
python -m py_compile app.py auth_security.py payment_storage.py payment_api.py
```

Compile Java without replacing project `.class` files by selecting a
temporary output directory:

```cmd
mkdir "%TEMP%\goparking-classes"
javac -d "%TEMP%\goparking-classes" java_backend\*.java tests\ParkingLotSmokeTest.java
java -cp "%TEMP%\goparking-classes" ParkingLotSmokeTest
```

Remove that specific temporary output folder after compilation.

## Manual application checks

Use a copy of the project database for any test that creates an account,
parks/removes a vehicle, or changes a fee setting. Do not run destructive
checks against the only copy of an important database.

1. Start the Java server and Streamlit; confirm the dashboard shows live
   capacity and available/occupied slot cards.
2. Bootstrap an admin in an isolated test database. Confirm the admin-only
   pages are shown after login.
3. Register two regular users and verify duplicate email handling and
   password login.
4. Register one vehicle for each user. Confirm each user sees only their
   own fleet, registration results, history, and payments.
5. Park a vehicle and verify that the lowest-numbered free slot is selected,
   event data is recorded, and occupancy updates.
6. Attempt to find/remove the other user's vehicle. Confirm details remain
   hidden and removal is denied before Java is called.
7. Remove an owned vehicle; verify the slot becomes available, an exit time
   and `CREATED` fee are recorded, and the fee appears only to its owner/admin.
8. Search by color and verify results include only visible owned vehicles.
9. Change rates as admin and verify fee estimates and newly recorded exit
   fees use the configured values.
10. Change a user's password. Confirm the current session stays signed in
    and another session for that account is redirected to login.
11. Resize the dashboard to mobile width and enable reduced motion; confirm
    there is no horizontal overflow and decorative animations are suppressed.
12. With Razorpay Test Mode credentials, complete a test checkout and confirm
    the server marks it `PAID`; fail and dismiss other checkouts and confirm
    neither is shown as paid.
13. Submit an invalid signature, a payment with an unexpected amount, a
    repeated verification, and a duplicate signed webhook. Only the correctly
    captured payment should become `PAID`, and duplicates should not duplicate
    records.
14. Try an expired capability and a capability belonging to another payment;
    the payment API must reject them.
15. Test a pending/authorized payment followed by `payment.captured`; verify
    the webhook updates the existing payment row exactly once.
16. Stop the payment API during checkout to exercise the visible network
    error and retry/status guidance.

## Current validation evidence

The latest payment integration validation compiled all changed Python modules
and ran `python -m unittest discover -s tests -v`: all 16 tests passed (four
authentication utility tests and 12 payment migration/flow tests). A payment
page smoke check rendered one Pay Now link without app exceptions using an
isolated temporary database. The payment unit tests mock the Razorpay provider
and do not perform live transactions.

The focused auth utility suite contains four passing tests. The Java smoke test
checks lowest-free-slot allocation, full-lot rejection, vehicle-type
validation, empty startup, duplicate-registration rejection, removal and
reallocation, fresh-process state, explicit restore, and registration lookup.
The Java source
set compiles with `javac`. Isolated Streamlit `AppTest` runs also verified
first-admin bootstrap, account registration and login, vehicle registration
and account listing, password-change session revocation, and denied
cross-account vehicle lookup/removal. A live 390px browser viewport showed
no horizontal overflow.

The Streamlit checks used an isolated temporary SQLite database. The complete
Streamlit-to-Java-to-SQLite park/remove fee transaction and automated browser
tests for all dashboard pages remain to be covered before deployment.

An isolated Streamlit runtime with static serving enabled returned HTTP 200
for all three bundled photos. Browser checks confirmed the selected
photographs on the landing page, dashboard, vehicle fleet, parking layout,
and administrator fee-settings page. The dashboard and fee-settings pages
had no horizontal overflow at desktop or 390px mobile width.

## Coverage gaps

- No automated tests currently exercise Streamlit pages.
- Razorpay network integration and real webhook delivery still need manual
  Test Mode verification.
- End-to-end unauthorized/cross-account browser attempts and browser network
  failure handling need manual verification.
- Java allocation and protocol behavior have no dedicated automated test
  class in this project.
- Cross-process consistency after failures is not tested or transactionally
  guaranteed.
