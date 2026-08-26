# FlexSys KDS — Authoritative Test Contracts

Status: **DRAFT v1 — Phase 1 of the Test Suite Reset.**
Baseline: `19.0.7.29.12`. Every statement below is verified directly
against the current Production code (not memory, not historical
CHANGELOG framing). Where a contract could not be verified from static
code alone, it is marked `[UNVERIFIED — confirm on Odoo.sh]`.

This document is the source of truth for the classification pass
(KEEP/REWRITE/MERGE/DELETE) that follows. A test that contradicts this
document is wrong by definition, unless this document is itself wrong
— in which case fix this document first, from code, not from the test.

---

## 1. POS Send Contract

Trigger modes: `kds_send_trigger` = `'payment'` (default) or `'send'`.

| Change type | `write()` alone | `write()` + explicit Send (`register_send()` / native Send RPC) |
|---|---|---|
| Increase | Never syncs | Syncs (creates a new delta `kds.order.line`, `qty` = the increase only, not the new total) |
| Decrease (any amount, including partial) | **Syncs immediately** via a dedicated path (`pos_order_line.py::write()`, `decrease_only=True`), independent of trigger mode, provided `order.kds_order_id` already exists | Same result; the following Send is a correct, idempotent no-op |
| Zero (`qty <= 0`) | **Syncs/cancels immediately**, same immediate path as Decrease | Same result |
| Note/variant-only change (no qty change) | Never syncs | Syncs — creates a full-quantity delta line (re-confirms the whole batch with new instructions) |
| New product line | Never syncs | Syncs — creates a new `kds.order.line` |

Under `'payment'` trigger mode, `ready` for any sync depends **solely**
on `order.state in ('paid', 'done', 'invoiced')` — independent of
whether a write was flagged as a "Send write." An order in `'draft'`
state under `'payment'` mode never syncs, regardless of any explicit
Send call.

**Increase example**: `1 → 3` does not create the delta until Send.
After Send: a new delta line with `qty=2` (not `qty=3`).

**Decrease example**: `3 → 2` reconciles immediately (no Send
required). A Send afterward must not duplicate the decrease (the
existing `qty`/`last_kds_sent_qty` idempotency guard prevents a
repeated write).

**Zero example**: `1 → 0` cancels immediately.

---

## 2. POS Line `unlink()` Contract

`pos_order_line.py::unlink()` does **not** perform an implicit Send.
It only flags every non-cancelled `kds.order.line` sharing the deleted
line's `pos_order_line_id` with `pending_removal = True`. The actual
cancellation + audit event is applied later, at the next genuine sync
boundary (`_flexsys_kds_diff_lines()`, called from the next Send/
Payment), never from `unlink()` itself.

- Immediately after `unlink()`, with no Send yet: the corresponding
  `kds.order.line` state is **unchanged**.
- After the next Send/Payment: the `pending_removal` sweep processes
  it — `completed` → `_system_cancel_after_completion()`; anything
  else → `action_cancel()`.
- If multiple `kds.order.line` records share the same
  `pos_order_line_id` (a historical family), **all** are flagged and
  cancelled together, with **one consolidated audit event** when the
  group has more than one member; a single-member group logs only its
  own individual cancellation event (no separate consolidated event).
- `unlink()` under `'payment'` trigger mode on an already-`paid` order
  is not reachable in real Odoo 19 — Odoo core itself refuses to
  unlink a `pos.order.line` unless the order is `'new'`/`'cancel'`
  (draft-equivalent). Any test simulating `unlink()` must use an order
  still in `'draft'`.

A genuine quantity **decrease** on an unrelated line in the same order
is unaffected by another line's pending removal — the immediate
decrease-sync path only ever touches the lines that genuinely
decreased.

---

## 3. Historical READY/COMPLETED Contract

Once a `kds.order.line` reaches `'ready'` or `'completed'`, its own
`qty`/`state`/timestamps are **never rewritten** by a later POS
change. A later genuine increase creates a **new, separate**
`kds.order.line` (a "delta sibling") carrying the same
`pos_order_line_id` — the original historical line is left completely
untouched.

- Multiple siblings may accumulate over time, all sharing the same
  `pos_order_line_id`. Reconciliation logic must consider the
  **combined** historical quantity across every active sibling, not
  just the most-recently-created one.
- A `qty → 0` event on a POS line with a historical family must
  cancel **every** active sibling in that family, not just one.
- A decrease that exceeds the most-recent (non-historical) sibling's
  own share must cascade into older historical siblings, newest-first,
  never writing a negative quantity anywhere.
- `Completed`, POS order still `'draft'` (active): further POS
  changes (increase/decrease/removal) are still received and applied
  — Completed does not mean "POS can no longer modify it."
- `Completed`, POS order closed (`paid`/`done`/`invoiced`/`cancel`):
  further decreases are informational-only (an audit event is logged,
  but neither state nor quantity is rewritten) — "the original
  completed work remains historically completed."

---

## 4. Effective Quantity Contract

For a given `pos_order_line_id`, the **effective KDS quantity** is the
sum of every active (non-cancelled) `kds.order.line`'s own `qty`
sharing that id. This is the quantity that must reconcile to the
current POS line quantity — never a single sibling's own `qty` in
isolation.

Tests must validate:
- The **effective quantity** (sum across all active siblings for the
  same `pos_order_line_id`) matches the current POS quantity.
- The **delta** applied is correct relative to what was last actually
  sent (`last_kds_sent_qty`), never relative to a stale or
  coincidentally-matching single value.
- The **historical state** is preserved where required (Section 3).

Tests must **not** assume that "the KDS line" (singular) always
reflects the full POS quantity — this is true only in the
single-sibling case, and coupling a test to that assumption is exactly
the failure mode that caused BUG-06 (a stale-partial-share vs. new-
total numeric coincidence silently suppressing reconciliation).

---

## 5. Routing Contract

Verified directly from `models/kds_routing_rule.py`
(`route_product()`, `_matches()`, `_station_eligible()`) during the
`test_routing.py` classification phase.

**Resolution order** (first match wins, highest priority level first):
1. An explicit `kds.routing.rule` whose own criteria match (product,
   product category, order type, POS config, company) — ordered by
   `sequence` ascending among matching rules (see "Rule ordering"
   below).
2. The product's own `kds_station_id` default, if set.
3. The product's own `product.category`'s own `kds_station_id`
   default (the inventory-category fallback), if set.
4. No match — returns an empty station (never raises, never guesses).

An explicit rule at level 1 always wins over both fallback levels,
regardless of the fallback levels' own configuration.

**Company / POS Config / Station eligibility isolation**:
- A rule with `company_id` set only ever matches an order for that
  same company. A rule with `company_id = False` is a deliberate
  "applies to every company" rule — not an isolation gap — but the
  destination *station* it names must still independently pass its
  own eligibility checks (see next point); a global rule does not
  imply a global station.
- Every resolution level (explicit rule and both fallback levels)
  independently re-checks that the destination station belongs to the
  correct company and is eligible for the requesting POS config
  (`station.pos_config_ids` empty = allows any POS; non-empty = must
  contain the requesting POS config) — isolation is enforced at every
  level, not only at the rule-matching step itself.
- A rule scoped to specific `pos_config_ids` must reject a request
  carrying no POS config at all, never silently match it.

**Inactive/archived rules**: a `kds.routing.rule` with `active = False`
never participates in matching at any level — resolution proceeds
exactly as if that rule did not exist, falling through to the next
eligible rule or fallback level.

**Many2many matching semantics**: `product_ids`, `product_categ_ids`,
`order_type_ids`, and `pos_config_ids` are all Many2many — a value
matches a rule if it is a member of any non-empty one of these fields
(OR within one field); a field left empty on the rule means "matches
any value for that criterion" (matches everything, not nothing). A
single rule can therefore legitimately cover several products, several
order types, etc. at once.

**Rule ordering — `sequence` field**: the technical field
`kds.routing.rule.sequence` is what actually controls which matching
rule wins when more than one rule's own criteria match the same
request — lower `sequence` value is checked first and wins. This is
the real, currently-active mechanism behind "Routing Rule Priority."

**Naming clarification — critical, verified directly against the
view's own arch (`views/kds_routing_rule_views.xml`) and the model's
own field definitions**: the Routing UI labels the `sequence` field's
own column/section as "Priority" (a display-label-only choice). This
is **"Routing Rule Priority"** — it governs only which routing rule is
checked first when multiple rules could match the same product/order.
It is **completely unrelated** to `kds.order.priority` (Order Priority
/ Urgent / VIP), which has been removed from every functional and UI
surface (see Section 10) — the two concepts share an English display
word by coincidence of relabeling, never a code path, a field, or a
business meaning. A test asserting routing-rule ordering behavior via
`sequence` is exercising the Routing Contract, never the removed Order
Priority feature, regardless of which UI label is currently shown.

---

## 6. Audit Event Contract

Authoritative `event_type` values (from `kds.event.event_type`
Selection field, `models/kds_event.py`):

| event_type | Semantic meaning |
|---|---|
| `order_created` | A `kds.order` was created for a POS order reaching the sync boundary for the first time. |
| `order_routed` | A line was assigned/reassigned to a station. |
| `station_received` | A station acknowledged receipt (if applicable to the flow in use). |
| `preparation_started` | A line's `action_start()` was called. |
| `line_ready` | A line's `action_ready()` was called. |
| `line_added` | A genuinely new `kds.order.line` was created for a POS line with no prior active sibling. |
| `line_removed` | A line (or a consolidated group sharing one `pos_order_line_id`) was cancelled — via `qty→0`, full POS-line removal, or POS-driven deletion after Completed. |
| `order_updated` | A quantity/note/variant change was applied to an **existing** line (in place, for a non-historical line) or a **new delta line** was created for an existing historical `pos_order_line_id` (increase-after-Ready/Completed). This is the event type used for what might otherwise be called "line_updated" — there is no separate `line_updated` value. |
| `status_changed` | A `kds.order`'s own aggregate status transitioned (e.g. to `preparing`/`ready`/`completed`). This is the event type used for what might otherwise be called "state_changed" — there is no separate `state_changed` value. |
| `order_reopened` | A completed/ready order was reopened because new, incomplete work exists. |
| `order_completed` | A `kds.order` reached the `completed` aggregate state. |
| `reprint` | A manual reprint was requested (`create_reprint()`). |
| `station_moved` | Reserved; `action_move_station()` itself is removed from Production (dead feature — see Section "Removed Features"). Any test exercising this action must be deleted. |
| `priority_changed` | Reserved; Priority/Urgent/VIP is a removed feature (see below). Any test exercising this must be deleted. |
| `print_retry` | A failed print job was retried. |
| `printer_fallback` | A print job fell back to a backup printer. |
| `override` | A supervisor/admin bypass of a normal restriction (e.g. `bypass_check=True` paths). |

**Rule for tests**: assert on `event_type` + the specific fact needed
(e.g. `old_value`/`new_value`, or a `note` substring that is itself
part of the contract — not incidental phrasing). Do not assert
`events_after > events_before` alone as the only check when a more
specific assertion is available; do not depend on exact event *count*
across a consolidated + individual event combination unless that
combination is itself the thing under test (as in the
`pending_removal` multi-sibling case, Section 2).

---

## 7. Printing Contract

- **Queue creation**: `action_print_full_order()` / auto-print create
  exactly one `kds.print.job` per (order, station) that has a printer
  configured. A station with **no printer configured** gets **no
  job at all** — never a job with `printer_id=False`, never a
  `'failed'`-status job (a `'failed'` status is reserved for a job
  that reached the agent and failed there).
- **Print sequence**: `print_number` is computed as this job's own
  1-based position among every `kds.print.job` sharing the same
  `(order_id, station_id)` pair, ordered strictly by database `id`.
  Never recomputed retroactively for an earlier sibling once stored.
  `display_job_type` is `'print'` for position 1, `'reprint'` for any
  later position.
- **Atomic claim**: `_claim_pending_jobs(printer, agent_id, limit=20,
  lease_seconds=90)` (`models/kds_print_job.py`) uses a single raw-SQL
  `UPDATE ... WHERE id IN (SELECT ... FOR UPDATE SKIP LOCKED) RETURNING
  id` against Postgres. This guarantees two concurrent claim calls for
  the same printer can never both receive the same job — no
  application-level locking needed. A job is claimable when
  `status='pending'`, OR `status='dispatched'` AND its lease has
  expired (`lease_expires_at IS NULL OR lease_expires_at < now()`).
  Claiming sets `status='dispatched'`, `dispatched_at=now()`,
  `claimed_by_agent=agent_id`, `claimed_at=now()`,
  `lease_expires_at = now() + lease_seconds`. The method explicitly
  flushes pending ORM writes before the raw SQL runs, and invalidates
  the claimed records' cache afterward — both required because raw SQL
  bypasses the ORM's own write-buffering and cache.
- **Lease / expiry / reclaim**: default lease is `DEFAULT_LEASE_SECONDS
  = 90` seconds. There is no separate cron/cleanup step — an expired
  lease on a still-`'dispatched'` job simply makes that job eligible
  again inside the *next* `_claim_pending_jobs()` call's own `WHERE`
  clause (see above). "Reclaim" is therefore not a distinct action to
  test in isolation; it is the natural behavior of the claim query
  once `lease_expires_at` has passed.
- **Failure / retry / fallback escalation** (`action_mark_failed()`):
  while `retry_count < MAX_AUTO_RETRY`, the SAME job is retried on the
  SAME printer (`status→'pending'`, `retry_count += 1`,
  `event_type='print_retry'`). Once retries are exhausted: if the
  station has a `is_backup` printer different from the failed job's
  own printer, a **new**, separate `kds.print.job` is created on that
  backup printer (same order/station/job_type/scope/copies/user), the
  original job is marked `status='failed', escalated=True`, and
  `event_type='printer_fallback'` is logged. If no backup printer
  exists, the original job is still marked `status='failed',
  escalated=True` with the same `printer_fallback` event type (a
  `note` distinguishes "MANAGER ALERT: ... no backup printer
  available"). Escalation never mutates the failed job's own printer
  in place — a new record is always created for the backup attempt.
- **Reprint**: `create_reprint()` requires a `reason`; raises
  `ValidationError` if missing. Requires a printer to already be
  resolvable for the station (`is_default` printer, else any
  configured printer) — raises `NoPrinterConfiguredError` (a
  `UserError`) if none exists, and creates **no** job in that case
  (never a job with `printer_id=False`). On success: creates exactly
  one new `kds.print.job` (`job_type='reprint'`) plus one `kds.event`
  (`event_type='reprint'`). Never mutates an existing job record in
  place — one-record-per-request architecture (no reuse).
- **Newest-order-first sorting**: the print job list view's own
  `default_order` is `"order_id.id desc, print_number"` — newer
  orders' jobs sort before older orders' jobs; within one order, jobs
  read 1, 2, 3 top to bottom. The dotted `order_id.id` form is
  required, not merely stylistic: `kds.order` has its own `_order =
  'create_date desc'`, so a plain `order_id desc` clause resolves via
  the ORM's own Many2one-sorting behavior to that related model's
  `_order` (create_date), not the raw FK id column — the two usually
  agree but are not guaranteed to, and have been observed to diverge.
  `order_id.id desc` explicitly sorts by the FK column itself on this
  table, bypassing the related model's own `_order` entirely — this
  is the one correct, reliable way to express "sort by which order is
  newer" for this specific relationship.

---

## 8. Kiosk Contract

All four public kiosk routes (`kiosk_page`, `kiosk_orders`,
`kiosk_action`, `kiosk_print`) call the same single, central function,
`_station_from_token(env, station_code, token)`
(`controllers/kds_kiosk.py`) — confirmed by direct read, no route
bypasses it. Its checks run in this exact order, each a hard reject
(`return None`) on failure:

1. **Presence**: `station_code` and `token` must both be non-empty.
2. **Station lookup**: an **active** `kds.station` with matching
   `code` must exist. The search is **not** scoped by `company_id` —
   it searches across every company. Isolation between
   companies/stations is therefore enforced entirely by the secrecy
   and uniqueness of the per-station `kiosk_token` value, not by a
   company/station filter in the lookup itself.
3. **Token validation**: `hmac.compare_digest(station.kiosk_token,
   token)` — a constant-time comparison specifically to avoid timing-
   attack token discovery. A station with no `kiosk_token` set at all
   is always rejected.
4. **`kiosk_disabled`**: if `True`, every request for that station is
   rejected regardless of a correct token — lets an administrator
   instantly kill kiosk access without regenerating the token/URL.
5. **Operating Mode gate**: `operating_mode == 'printer_only'` is
   rejected outright — a bookmarked/old kiosk URL for a station later
   reconfigured to `printer_only` fails authentication itself, not
   merely a hidden UI element. `kds_only` and `kds_printer` (the only
   other two valid values — **not** `'kds_and_printer'`) both pass
   this gate.

`operating_mode` (`models/kds_station.py`) is a required Selection
with exactly three values: `kds_only`, `printer_only`, `kds_printer`
(default `kds_printer`).

**Station-scoped order visibility**: `kiosk_orders`/`kiosk_action`/
`kiosk_print` all further filter/check against the authenticated
station specifically (e.g. `kiosk_print`: `station not in
order.station_ids` → `{'ok': False, 'error': 'Order not found for this
station'}`) — a valid token for station A cannot act on an order that
does not include station A among its own `station_ids`.

**Printing availability within an allowed session**: `kiosk_print`
additionally rejects with `{'ok': False, 'error': 'Printing is not
enabled for this station'}` when `operating_mode == 'kds_only'` —
distinct from the `printer_only` full-session rejection above; a
`kds_only` station's kiosk session is otherwise fully valid, only
printing specifically is unavailable. `kiosk_page`'s own rendered
`printing_enabled` flag is `operating_mode != 'kds_only'`, matching
this.

**Company isolation, stated precisely**: there is no explicit
`company_id` check anywhere in `_station_from_token()` beyond the
unscoped station lookup above — a test asserting "company isolation"
for the kiosk must test it as a consequence of **token secrecy/
uniqueness** (a token issued for a station in company A does not exist
in company B, so no valid cross-company access is *possible* without
already knowing another company's own secret token), not as a
separate, explicit company-id filter in the code, because no such
filter exists.

---

## 9. Test Helper Table

Every "helper produces an unexpected `kds_order_id` state" failure
this project has hit (multiple CI rounds) traced back to a helper's
contract not being read carefully before use. This table is the fix.

| Helper | File | POS `state` | Sent to KDS? | `kds_order_id` guaranteed? | Intended use |
|---|---|---|---|---|---|
| `_create_pos_order(product_qty_list, state='paid')` | test_pos_sync.py | Caller-chosen (default `'paid'`) | Only if `state` resolves to `paid`/`done`/`invoiced` under `'payment'` trigger mode (the untouched default) | Yes if default `state='paid'` used; **No** if `state='draft'` passed (payment-mode gate requires a paid state regardless of any `write()` call) | Standard "order already paid, KDS ticket exists" scenarios under default `'payment'` mode. |
| `_create_active_pos_order(product_qty_list)` | test_pos_sync.py | `'draft'` | Yes — sets `kds_send_trigger='send'` and calls `flexsys_kds_register_send()` internally | Yes, always | Scenarios needing an order that is genuinely `'draft'` (still open) **and** already has a real `kds_order_id`. |
| `_create_never_sent_pos_order(product_qty_list)` | test_pos_sync.py | `'draft'` | No | No | Scenarios that must start with **zero** sync having happened yet — e.g. testing authorization/sync-from-ui logic from a clean slate. |
| `_send_order(product_qty_list)` | test_pos_sync.py | `'draft'` | Yes — same as `_create_active_pos_order` | Yes | Equivalent to `_create_active_pos_order`; used historically in the "immediate decrease reconciliation" test family. Candidate for **MERGE** with `_create_active_pos_order` during helper consolidation (Phase 2) unless a real behavioral difference is found. |
| `_make_send_write_order()` | test_pos_sync.py | `'draft'` | No — caller must call `register_send()` explicitly | Only after caller's own explicit `register_send()` call | Scenarios needing to control the exact moment of the first Send. |
| `order.flexsys_kds_register_send()` | production method | n/a | Triggers `_flexsys_kds_sync(is_send_write=True)` | Creates `kds_order_id` if not present | The one explicit "genuine Send" call every helper above either calls internally or expects the caller to call. |

**Rule going forward**: no new test may call `_create_active_pos_order`
or `_send_order` when the scenario requires "not yet sent" — use
`_create_never_sent_pos_order`. No new test may assume
`_create_pos_order(..., state='draft')` produces a real `kds_order_id`
— it does not, under the current default trigger mode.

---

## 10. Removed Features — No Test May Exercise These

Confirmed removed from Production (verified by absence in current
`models/`/`static/` — re-verify at classification time before deleting
any specific test, but treat this list as the starting assumption):

- Priority / Urgent / VIP: **correction (found during
  `test_permissions.py` classification, Phase 2)** — `priority` is
  **not** a removed field. It still exists as a real Selection field
  on both `kds.order` (`models/kds_order.py`) and `kds.order.line`
  (a `related` field, `models/kds_order_line.py`), with the same
  `normal`/`priority`/`urgent`/`vip` values. What is actually removed
  is every **functional/UI use** of it — confirmed by a full grep of
  `models/*.py` and `controllers/*.py` (zero non-definition usages)
  and of every view/JS file (the only "priority" hits are (a) comments
  documenting the column was deliberately removed from the order list
  view, and (b) an unrelated "priority" concept — routing *rule*
  priority/sequence ordering, a different feature entirely, not order
  Priority/VIP). This is exactly the "legacy database field kept for
  upgrade safety" case Section 9 of this document already anticipates
  — the field itself is a dormant compatibility column, not deleted,
  and a test that writes to it (e.g. to verify the direct-write
  protection mechanism applies to it like any other protected field)
  remains **functionally valid**, not obsolete. Do not delete such a
  test on the assumption the field is gone — verify with `grep -n
  "priority = fields\." models/*.py` first, every time.
- `action_move_station()` (dead method — historical station-transfer
  action, fully removed).
- `action_test_connection()` on `kds.printer` (dead method — replaced
  by real print-agent architecture).
- Any workflow-status foundation predating the current
  `new/preparing/ready/completed/cancelled` state model.
- Any legacy print dispatch path predating the current
  `kds.print.job` queue/claim/lease architecture.

Any test whose only purpose is confirming one of the above **still
exists or still works** must be **DELETE**d. A test confirming one of
the above **is genuinely absent** (a "not present" structural check)
may be **KEEP**, but only one such test per feature is needed — not a
whole family.

---

## Change Log for This Document

- v1: initial authoritative contract, Sections 1–5 and the Helper
  Table verified directly against code.
- v2: Sections 6 (Printing) and 7 (Kiosk) completed from a full,
  direct read of `models/kds_print_job.py` (claim/lease SQL, retry/
  fallback escalation, reprint gating) and
  `controllers/kds_kiosk.py` + `models/kds_station.py`
  (`_station_from_token()`'s exact check order, the real
  `operating_mode` selection values — corrected from an assumed
  `kds_and_printer` to the actual `kds_printer` — and the explicit
  absence of a company_id filter in the kiosk auth path). **No
  `[UNVERIFIED]` markers remain.** This document is now the complete
  reference for the Phase 2 classification pass.
- v3: added Section 5, Routing Contract — verified directly against
  `models/kds_routing_rule.py` and `views/kds_routing_rule_views.xml`
  during the `test_routing.py` classification phase. Documents the
  current resolution order, isolation rules, inactive-rule exclusion,
  Many2many matching semantics, and — critically — the distinction
  between the `sequence` field (Routing Rule Priority, currently
  active) and the removed `kds.order.priority` (Order Priority /
  Urgent / VIP, Section 10). Sections 6–10 renumbered accordingly
  (previously 5–9); all internal cross-references updated to match.
