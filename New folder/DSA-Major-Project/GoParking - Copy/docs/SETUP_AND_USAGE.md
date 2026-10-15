# GoParking Setup and Usage

## Prerequisites

- Python 3.10 or newer.
- A JDK for compiling the Java files when `.class` files are absent or stale.
- Windows Command Prompt, PowerShell, or another terminal.

Install the project dependencies in the Python environment you will use to
run GoParking:

```cmd
python -m pip install -r requirements.txt
```

## Configure the first administrator

When no administrator is present, set the following variables in the same
terminal session that starts Streamlit:

```cmd
set GOPARKING_ADMIN_NAME=Parking Administrator
set GOPARKING_ADMIN_EMAIL=admin@example.com
set GOPARKING_ADMIN_PASSWORD=replace-with-a-long-unique-password
```

Use a unique password with at least 12 characters. Never publish real
credentials. The first successful bootstrap creates the administrator and
assigns any historical rows without owners to that account. Subsequent app
starts do not reset credentials from the environment.

For PowerShell, use `$env:GOPARKING_ADMIN_NAME = "..."`, and similarly set the
email and password before starting Streamlit. In Command Prompt, use `set`,
not PowerShell's `Set-Location`; use `cd /d "C:\path\to\project"` to change
drives and directories.

## Configure Razorpay Test Mode

In the Razorpay Dashboard, switch to **Test Mode**, open the API Keys settings,
and generate a Test Mode Key ID and Key Secret. Do not use Live Mode keys for
development. Keep the secret in the payment API process environment; never put
it in source code, browser code, or a committed file.

Set the API environment in the terminal that runs the payment API. Replace
the placeholder values locally with the Test Mode credentials from your
Razorpay Dashboard; do not share or commit them:

```powershell
$env:RAZORPAY_KEY_ID = "rzp_test_REPLACE_LOCALLY"
$env:RAZORPAY_KEY_SECRET = "REPLACE_LOCALLY"
$env:GOPARKING_RAZORPAY_MODE = "test"
$env:RAZORPAY_WEBHOOK_SECRET = "REPLACE_LOCALLY_IF_WEBHOOKS_ARE_ENABLED"
$env:GOPARKING_DB_PATH = "C:\path\to\GoParking - Copy\goparking.db"
$env:GOPARKING_PAYMENT_API_URL = "http://127.0.0.1:8765"
$env:GOPARKING_APP_URL = "http://localhost:8501"
```

`GOPARKING_RAZORPAY_MODE` defaults to `test`; the payment service rejects a
key whose prefix does not match the selected mode. `RAZORPAY_WEBHOOK_SECRET`
is the secret generated for the webhook endpoint, not the API Key Secret.

## Start the application

Run each process in its own terminal, using the same database path:

1. Start the Java parking server:

   ```cmd
   cd /d "C:\path\to\GoParking - Copy\java_backend"
   javac *.java
   java -cp . ParkingServer
   ```

   It listens on local port 5000. Keep it running.

2. Start Streamlit in a second terminal. Set the public Key ID and payment API
   URL in that terminal; the API Key Secret is not needed by Streamlit:

   ```powershell
   Set-Location "C:\path\to\GoParking - Copy"
   $env:RAZORPAY_KEY_ID = "rzp_test_REPLACE_LOCALLY"
   $env:GOPARKING_PAYMENT_API_URL = "http://127.0.0.1:8765"
   streamlit run app.py
   ```

   If first-admin bootstrap is required, also set the three
   `GOPARKING_ADMIN_*` variables in this terminal. This initializes/migrates
   the database. Open the URL printed by Streamlit, usually
   `http://localhost:8501`.

3. Start the payment API in a third PowerShell terminal, with the Razorpay
   environment above configured in that terminal:

   ```powershell
   Set-Location "C:\path\to\GoParking - Copy"
   python payment_api.py
   ```

   It listens on `127.0.0.1:8765` by default. Keep it running. The API
   requires the database initialized by Streamlit.

The separate payment service is required for payment checkout and webhook
verification. In a hosted deployment, run it behind HTTPS and configure
`GOPARKING_PAYMENT_API_URL` to the HTTPS origin reachable by the user's
browser. Do not expose its development HTTP listener directly to the internet.

Keep the `.streamlit` configuration and `static/parking` image folder beside
`app.py`; Streamlit uses them to serve the locally bundled page backgrounds.
Restart Streamlit after changing the static-serving configuration.

## Typical user workflow

1. Create an account with a valid email shape and a password of at least 12
   characters.
2. Sign in and optionally complete the profile.
3. Register a vehicle under **Register Vehicle**, or use **Park Vehicle**,
   which also registers an eligible new vehicle.
4. Use the parking dashboard or **Parking Slots** to inspect occupancy.
5. Use **Search Vehicle**, **Search by Color**, or **My Vehicles** to find
   account-owned vehicles.
6. Remove an owned parked vehicle to record its exit and calculated fee.
7. Open **Payments** and choose **Pay** for the fee due. The checkout opens
   Razorpay's hosted Checkout interface.
8. The payment is shown as paid only after server verification. A dismissed
   checkout remains unpaid; a captured payment can also be confirmed later by
   webhook.

Administrators also have **User Management** and **Fee Settings**. The admin
role can view system-wide records and change hourly rate settings.

## Webhook configuration

For asynchronous payment updates, configure a Razorpay webhook that points to
`https://<your-https-host>/api/webhooks/razorpay` and subscribe to
`payment.captured` and `payment.failed`. Copy that webhook's signing secret to
`RAZORPAY_WEBHOOK_SECRET` in the payment API environment and restart it.
Razorpay cannot call a local-only URL; use a deployed HTTPS endpoint or a
trusted HTTPS development tunnel. The API verifies the raw request bytes and
the `X-Razorpay-Signature`, and deduplicates `X-Razorpay-Event-Id`.

## Testing checkout and Live Mode

Create a parking fee using a test account, then select **Pay** from
**Payments**. Use a test payment method supported by the Razorpay Test Mode
account and shown in the current Razorpay documentation/dashboard. Verify the
result in the UI and Razorpay's Test Mode dashboard. Test a failed attempt,
close Checkout to test cancellation, and try opening an expired checkout link.

Do not switch to Live Mode until the Razorpay account is approved, the HTTPS
endpoint and production secret handling have been reviewed, webhook delivery
has been tested, and the payment scenarios have passed. Back up the database,
then configure the approved Live Key ID/Secret only in the payment API
environment and deliberately set `GOPARKING_RAZORPAY_MODE=live`. Keep Test
Mode and Live Mode credentials separate. No refund flow is implemented.

## Backup and privacy

Stop Streamlit before making a manual backup of `goparking.db`. Keep backups
private; the database includes account contact information, password hashes,
vehicle registrations, and payment records. Do not expose the Java server's
port 5000 to an untrusted network.

## Troubleshooting

| Symptom | Action |
|---|---|
| Streamlit says the Java server is unavailable | Start `ParkingServer` and verify local port 5000 is free |
| First-admin warning remains | Set all three environment variables in the Streamlit terminal and restart |
| User cannot see another vehicle | This is expected: vehicle and history details are owner-scoped |
| Data appears empty after Java restart | Confirm SQLite has active events; startup restoration is best effort |
| Browser page differs from source | Stop the old Streamlit process and start the intended project folder |
| `Set-Location` is not recognized | The terminal is Command Prompt; use `cd /d "..."` instead |

For technical boundaries and known limitations, see
[TECHNICAL_DOCUMENTATION.md](./TECHNICAL_DOCUMENTATION.md).
