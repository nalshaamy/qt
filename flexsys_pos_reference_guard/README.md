# FlexSys POS Reference Guard — Odoo 19

Version: **19.0.1.1.0**

## Purpose

Protect Odoo POS from duplicate customer-facing receipt references and keep the
same POS device numbering identity when the cashier uses **Reload Data**.

Observed production patterns included:

- `2651-3-000725` repeated across different UUIDs/orders.
- `2653-3-000001` repeated across different UUIDs/orders.
- Reload Data changing the browser device namespace, e.g. `2656-3-000411`
  followed by `2657-3-000001`.

The module deliberately prefers a harmless gap in numbering over reusing a
previously allocated order number.

## Protection layers

### 1. Frontend: never recycle an allocated local number

The patch overrides `DeviceIdentifierSequence.useNext()` and
`saveUnusedNumber()` so `unsynced_number_stack` is no longer used to recycle
numbers.

Normal flow remains monotonically increasing:

`000001 -> 000002 -> 000003 ...`

A deleted/abandoned number may therefore create a gap. That is intentional.

### 2. Reload Data: preserve device identifier and next number

In the deployed Odoo 19 build, Reload Data clears IndexedDB, sessionStorage and
localStorage. Odoo therefore loses the device-sequence key, registers a new
`device_identifier`, and starts again from `next_number = 1`.

V1.1 patches `PosStore.reloadData()` so the reload still resets Odoo's local
data, but restores **only** the POS numbering identity afterward:

- same `device_identifier`,
- same `next_number`,
- `unsynced_number_stack = []`.

Example:

Before Reload Data:

`2656-3-000411` (device 56, sequence 411)

If the stored next number is 412, after Reload Data the next newly allocated
receipt remains in the same namespace, e.g.:

`2656-3-000412`

instead of changing to a new device such as `2657-3-000001`.

No other localStorage value is deliberately preserved by this patch.

### 3. Backend: duplicate receipt guard

Before a `pos.order` is created, the module checks the incoming
`pos_reference`.

If another order already owns that receipt number with a different UUID, the
incoming order is repaired using Odoo's backend sequence namespace
(`device_identifier=0`).

Example:

Incoming duplicate: `2653-3-000001`

Possible repaired value: `260-3-003191`

The repaired order receives the complete backend sequence suffix as
`tracking_number`, keeping the emergency number numeric and unique.

### 4. Audit trail

Every automatic repair is recorded in:

**Point of Sale -> Reference Guard Logs**

The log includes the original/replacement receipt numbers, UUID, POS, session,
cashier/user, and the existing order that caused the collision when available.

The affected `pos.order` is also marked with:

- `flexsys_reference_repaired`
- `flexsys_original_pos_reference`
- `flexsys_original_tracking_number`
- `flexsys_reference_repair_reason`

## Why no SQL UNIQUE constraint?

Production already contains historical duplicate `pos_reference` values.
Adding a UNIQUE constraint would fail installation or require rewriting
historical fiscal/payment records. The guard protects **new orders** without
altering old transactions.

## Staging acceptance test — 19.0.1.1.0

1. Install/upgrade the module on Staging.
2. Hard refresh the POS after the asset build completes.
3. Record the Local Storage sequence object before testing:
   - `device_identifier`
   - `next_number`
   - `unsynced_number_stack`
4. Complete at least 3 paid orders and confirm receipt references advance.
5. Note the current `device_identifier` and `next_number`.
6. Use **Reload Data** from the POS.
7. After POS reload, confirm:
   - `device_identifier` is unchanged,
   - `next_number` is unchanged from the preserved value (unless a new order
     was already allocated during screen initialization),
   - `unsynced_number_stack` is empty.
8. Create and pay one new order. Confirm:
   - it remains in the same device namespace,
   - its sequence is greater than all previously allocated numbers,
   - Reload Data did not reset numbering to `000001`.
9. Force a duplicate only on Staging by creating/submitting a second order with
   an already-used `pos_reference` but a different UUID.
10. Confirm the backend guard:
    - saves the second order successfully,
    - replaces its duplicate `pos_reference`,
    - preserves its unique UUID,
    - creates a Reference Guard Log,
    - does not break payment or receipt printing.
11. Verify **Point of Sale -> Reference Guard Logs** is visible only to the
    intended POS management group.

## Production rollout

Deploy only after all Staging acceptance checks pass. Do not renumber, merge or
delete historical duplicated orders as part of this module.

## Upgrade notes from 19.0.1.0.0

- Added Reload Data sequence preservation.
- Reload Data no longer intentionally changes the POS device identifier.
- Reload Data no longer intentionally resets the POS browser sequence to 1.
- Existing no-recycle frontend guard, backend duplicate repair and audit log are
  unchanged.
