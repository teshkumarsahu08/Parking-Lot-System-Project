# GoParking DSA Documentation

## Data structures in the Java parking engine

### `TreeSet<Integer>`: available slots

The parking lot initializes a `TreeSet` with slot numbers from 1 through its
capacity. A successful allocation obtains `availableSlots.first()` and
removes that value. This preserves the current lowest-numbered-free-slot
policy without scanning every space.

| Operation | Complexity |
|---|---:|
| Initialize `n` slots by repeated insertion | `O(n log n)` |
| Read lowest free slot with `first()` | `O(1)` |
| Insert/remove a free slot | `O(log n)` |
| Check whether a slot is free | `O(log n)` |

### `HashMap<String, ParkingSlot>`: registration lookup

`vehicleMap` maps normalized registration numbers to their occupied slot.
It supports expected `O(1)` find, duplicate-check, and removal lookup, subject
to normal hash-table assumptions. The stored key is uppercase to make
registration matching case-insensitive.

### `ArrayList<Vehicle>` and `ArrayList<ParkingHistory>`: ordered records

The lists preserve insertion order for the Java process's in-memory vehicle
and parking history views. Appending is amortized `O(1)`; scanning by
registration or other property is `O(n)`. SQLite, not these Java lists, is
the durable history source used by the Streamlit pages.

## Allocation algorithm

1. Validate registration, color, and vehicle type.
2. Normalize the registration to uppercase.
3. Reject a duplicate registration already present in `vehicleMap`.
4. Reject when `availableSlots` is empty.
5. Read and remove the minimum element from `availableSlots`.
6. Create the `ParkingSlot`, map the registration to it, and append vehicle
   and history objects.
7. Return an `OK` response containing the allocated slot.

With `n` available slots, choosing the minimum is constant-time and removal
from the balanced tree is `O(log n)`. Hash-map insertion is expected `O(1)`.
The primary allocation operation is therefore `O(log n)` overall. The
capacity is currently ten, but the data structure supports larger capacities.

## Removal and restore

Removal looks up the normalized registration in `vehicleMap`, removes the
vehicle mapping and list entry, and returns the freed slot to the `TreeSet`.
Lookup and list removal together are expected `O(n)` because `ArrayList`
removal searches and shifts elements. `restoreVehicle` validates that the
specified slot is within capacity and available before rebuilding the in-memory
map and list state.

All public `ParkingLot` state-changing and query methods are synchronized so
the Java object serializes concurrent access to these collections. The
current `ParkingServer` additionally handles one client request at a time.

## Python-side search and persistence

Python uses SQLite indexes for owner/event and owner/payment queries and
parameterized SQL for database access. The current color query is executed by
the Java engine over active in-memory vehicles, then filtered to account-owned
registrations by the Streamlit app. The visual slot map uses the Java `SLOTS`
response and masks another user's vehicle details.

## Complexity summary

Let `n` be occupied vehicles, `s` be total slots, and `h` be SQLite history
rows:

| Operation | Approximate complexity |
|---|---:|
| Lowest free slot allocation | `O(log s)` |
| Registration map lookup | Expected `O(1)` |
| Registration map removal | Expected `O(1)` plus `O(n)` list removal |
| Search Java list history by scan | `O(n)` |
| Color search over active Java vehicles | `O(n)` |
| Render all slot records | `O(s)` |
| Read indexed owner history | `O(log h + k)` for `k` returned rows, depending on query plan |

## Preserved algorithm

Vehicle categories are validated against an allowlist in `ParkingLot`; the
new categories do not alter the lowest-free-slot rule or introduce unsupported
space sizing/reservation behavior.
