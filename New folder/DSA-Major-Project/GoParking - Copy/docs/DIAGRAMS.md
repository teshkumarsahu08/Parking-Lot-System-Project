# GoParking Architecture and UML Diagrams

## Component architecture

```mermaid
flowchart LR
    Browser[User browser]
    UI[Streamlit app.py]
    Auth[auth_security.py]
    PayAPI[Razorpay payment_api.py]
    DB[(SQLite goparking.db)]
    Java[Java ParkingServer]
    Lot[ParkingLot]
    Slots[ParkingSlot and Vehicle]
    Razorpay[Razorpay Checkout and API]

    Browser --> UI
    UI --> Auth
    UI -->|accounts, registry, events, fees, payments| DB
    UI -->|local TCP commands| Java
    UI -->|short-lived payment link| Browser
    Browser -->|Checkout and capability-bound API| PayAPI
    PayAPI -->|server-created orders and verification| Razorpay
    Razorpay -->|signed webhooks| PayAPI
    PayAPI -->|payment status| DB
    Java --> Lot
    Lot --> Slots
```

The app database and Java in-memory allocation state are separate stores.
Restoration on startup is best effort; operations are not a distributed
transaction.

The payment API is a separate Python process and shares the SQLite database
with Streamlit. The browser receives only a short-lived capability for one
owner-scoped payment; the API secret and webhook verification stay server-side.

## Payment sequence

```mermaid
sequenceDiagram
    actor User
    participant UI as Streamlit app
    participant DB as SQLite
    participant API as Payment API
    participant RZ as Razorpay

    User->>UI: Remove own parked vehicle
    UI->>DB: Close event and create CREATED fee row
    User->>UI: Open Pay Now
    UI->>DB: Store hash of expiring checkout capability
    UI-->>User: Payment API checkout URL
    User->>API: Open checkout with capability
    API->>DB: Resolve fee and amount from stored row
    API->>RZ: Create order using stored amount/currency
    RZ-->>API: Razorpay order
    API-->>User: Checkout.js configuration (public Key ID)
    User->>RZ: Complete or cancel checkout
    RZ-->>User: Order, payment, signature
    User->>API: Submit callback for server verification
    API->>RZ: Verify signature and fetch payment
    API->>DB: Mark PAID only for verified captured payment
    RZ->>API: Signed payment.captured/payment.failed webhook
    API->>DB: Verify raw-body HMAC and deduplicate event
```

## Park vehicle sequence

```mermaid
sequenceDiagram
    actor User
    participant UI as Streamlit app
    participant DB as SQLite
    participant Java as ParkingServer
    participant Lot as ParkingLot

    User->>UI: Submit vehicle details
    UI->>DB: Check registration owner
    DB-->>UI: Owner record / no registration
    UI->>DB: Create or update authorized vehicle record
    UI->>Java: PARK|registration|color|type
    Java->>Lot: Validate and allocate
    Lot-->>Java: Lowest available slot
    Java-->>UI: OK|Vehicle parked|...|slot
    UI->>DB: Insert owner-scoped active event
    UI-->>User: Show allocated slot
```

## Account entity relationships

```mermaid
erDiagram
    USERS ||--o{ VEHICLES : owns
    USERS ||--o{ PARKING_EVENTS : records
    USERS ||--o{ PAYMENTS : receives
    VEHICLES {
        int id PK
        int owner_user_id FK
        string registration UK
        string vehicle_type
        string color
        string created_at
    }
    USERS {
        int id PK
        string full_name
        string email UK
        string mobile
        string password_hash
        string role
        string created_at
    }
    PARKING_EVENTS {
        int id PK
        int owner_user_id FK
        string registration
        string color
        string vehicle_type
        int slot
        string entry_time
        string exit_time
        float fee
    }
    PAYMENTS {
        int id PK
        int owner_user_id FK
        string registration
        float amount
        string paid_at
    }
```

## Parking allocation activity

```mermaid
flowchart TD
    A[Receive PARK command] --> B{Details valid and supported?}
    B -- No --> X[Return error]
    B -- Yes --> C{Registration already parked?}
    C -- Yes --> X
    C -- No --> D{Any available slot?}
    D -- No --> X
    D -- Yes --> E[Select smallest TreeSet slot]
    E --> F[Remove slot from available set]
    F --> G[Store registration in HashMap]
    G --> H[Append vehicle and history]
    H --> I[Return allocated slot]
```
