# FlexSys POS Reference Guard — Odoo 19

Version: **19.0.1.4.0**

## Purpose

Protect Odoo POS from duplicate customer-facing receipt references while keeping
one stable browser/device numbering namespace across **Reload Data** and normal POS tab close/reopen cycles.

Observed production patterns included duplicate references such as
`2651-3-000725` and `2653-3-000001` across different UUIDs/orders. Cashiers were
using Reload Data as a workaround, which changed the device identifier and
started a new sequence.

## Protection layers

### 1. Frontend: never recycle allocated numbers

`DeviceIdentifierSequence.useNext()` is monotonic. `unsynced_number_stack` is
not reused. A harmless gap is preferred to a duplicated customer-facing number.

### 2. Reload Data: preserve identity and conditionally reclaim an empty draft

Reload Data keeps the existing `device_identifier` and `next_number` instead of
starting a new browser namespace at 1. A single *empty, unpaid, not-yet-synced*
local draft holding the very last allocated number may be reclaimed **only**
when (a) there are no other unsynced local orders, (b) a live-tab probe finds no
other POS window, and (c) the server verifies the reference is absent. Otherwise
the counter remains monotonic; gaps are preferable to duplicate fiscal receipts.
On a verified one-step reclaim, the durable backup cookie is updated together
with Local Storage, so it cannot silently undo the reclaim after restart.
Other local data is still reloaded/reset by Odoo.


### 3. Durable browser backup across tab close/reopen

V1.3 keeps a redundant, first-party cookie backup of only the numbering state
(`device_identifier` and `next_number`), scoped per POS configuration. If the
native Odoo localStorage entry disappears while the cookie remains, the module
restores the same device identity and the highest known counter **before** Odoo
can register a new device and restart at 1.

The cookie contains no customer, product, payment, or fiscal data. Allocated numbers are never recycled except the narrowly verified, last empty draft during Reload Data.

### 4. Backend duplicate guard: repair in the SAME device sequence

If a new UUID arrives with a `pos_reference` already used by another order, the
guard keeps the year/device/POS prefix and allocates the next persisted number.

Example:

- duplicate incoming: `2656-3-000003`
- repaired: `2656-3-000004`
- repaired tracking/order number: `56004`

The repair is serialized with PostgreSQL advisory transaction locks for both the
incoming reference and the device/POS namespace.

If the incoming reference does not match the normal browser format, the module
keeps an emergency fallback to Odoo's backend (`device_identifier=0`) sequence.

### 5. Frontend re-alignment after a server repair

Odoo calls `postSyncAllOrders()` before returning from the synchronization flow.
V1.2 uses that hook to make the browser counter at least one number above the
server-repaired receipt before the next blank order is allocated.

If an unsynced local draft already holds a number that now conflicts with the
repaired server number, that draft is shifted forward to the next free number.

This prevents the sequence:

`repair to 000004 -> browser immediately creates another 000004`.

### 6. Audit trail

Every repair is recorded in **Point of Sale -> Reference Guard Logs**, including
original/replacement references, UUID, POS, session, cashier/user, and the
existing order that caused the collision when available.

The affected `pos.order` is marked with:

- `flexsys_reference_repaired`
- `flexsys_original_pos_reference`
- `flexsys_original_tracking_number`
- `flexsys_reference_repair_reason`

## Why no SQL UNIQUE constraint?

Production already contains historical duplicate `pos_reference` values. A
UNIQUE constraint would fail on those records or require rewriting historical
fiscal/payment data. The guard protects new orders without touching history.

## Staging acceptance test — 19.0.1.3.0

1. Upgrade the module on Staging and hard-refresh the POS assets.
2. Confirm normal paid orders advance in one device namespace.
3. Use Reload Data and confirm the device identifier does not change/reset.
4. Force a duplicate by setting the local counter back to a previously used
   suffix on Staging only.
5. Pay the order.
6. Expected result:
   - server detects the duplicate UUID/reference,
   - repaired receipt remains in the same namespace (e.g. `2656-3-000004`),
   - tracking/order number matches the same device (e.g. `56004`),
   - printed receipt shows the repaired values,
   - Local Storage `next_number` is greater than the repaired suffix,
   - the next normal order continues with `000005` (or the next free number),
   - a Reference Guard Log is created.
7. Run at least 5 additional normal paid orders and one more Reload Data cycle.

## Upgrade notes from 19.0.1.1.0

- Duplicate repair now stays in the same year/device/POS sequence.
- Added namespace-level locking for concurrent repairs.
- Added browser counter re-alignment after server repairs.
- Unsynced local drafts that conflict with a repaired sequence are shifted
  forward before subsequent use.
- Backend `260-...` repair remains only as an emergency fallback for malformed
  or non-browser references.


## Upgrade notes from 19.0.1.2.0

- Added a durable per-POS browser backup for `device_identifier` and `next_number`.
- Normal tab close/reopen can recover the same identity even if native
  localStorage unexpectedly disappears.
- Reconciliation keeps the highest counter when both native and backup state
  exist for the same device, preventing rollback.
- No customer/payment data is stored in the backup cookie.

## V1.4: draft reuse limits and test requirements

This is a **conditional best-effort continuity feature**, NOT a guarantee of
gapless statutory invoice numbers. POS allocates receipt numbers when opening a
draft; offline orders, closed tabs, pending requests, and concurrent tabs can
make unconditional reuse unsafe. The server-side collision guard stays enabled.

On staging, verify (1) an online single-window empty draft can reclaim the last
number after Reload Data, (2) drafts with product lines or payments never
reclaim, (3) server-persisted or offline/pending orders never reclaim, (4) two
active POS windows do not reclaim, (5) cookie/LocalStorage agree after reload,
(6) the next two paid orders and printed receipts remain unique, and (7) the
collision/audit scenario still works. A complete Odoo 19 regression, real device
print, and tax-invoice numbering review are required before production rollout.
