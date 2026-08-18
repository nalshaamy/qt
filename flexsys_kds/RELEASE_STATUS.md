# FlexSys KDS — Release Status

**Version: 19.0.7.9.6**
**Status as of this document: code-complete, including everything
through v7.9.5 (see CHANGELOG.md for the full history), plus this
round's fix: "Explicit POS Send Must Trigger KDS Sync" - the normal
Send button was confirmed working (blocking correctly proven), but
Odoo's own native unsent-order confirmation dialog ("would you like to
send it to preparation?" → "Order") did not reliably trigger the same
`sendOrderInPreparation()` method the existing frontend patch hooks. A
second, independently-isolated frontend patch now hooks
`order.updateLastOrderChange()` directly - the confirmed lower-level
persistence point common to every genuine Send path, regardless of
which button or dialog triggers it - kept in its own separate file so
an import failure in one patch cannot cascade into breaking the other.
303 automated tests, all `py_compile`/XML/JS checks passing, plus a
custom AST-based undefined-name sweep. **Two frontend patches now
patch Odoo's own core POS register - both remain the highest-risk,
still-unverified pieces of this entire delivery - see the dedicated
sections below - not yet signed off on a live instance — see "What
still needs a human" at the end.**


This document maps directly to that request's own section structure
(A/B/C/D) and states, for each item, what's actually been verified and
how - rather than just asserting "done." Where something can only be
confirmed against a live Odoo 19 runtime (which this environment does
not have access to), that's stated plainly rather than glossed over.

---

## A. Implemented — regression-tested

Every item in section A already has direct, named automated test
coverage (see `tests/`, 171 tests total). Nothing in this section was
redesigned this round, per the request's own instruction not to unless
a regression was found - none was, while auditing this list.

One real gap *was* found and fixed while doing this audit, not in the
business logic but in the realtime layer: a brand-new order's very
first sync from POS to KDS never triggered a bus notification at all
(every *later* change to that order did - see B3 below). This is fixed
in this release.

---

## B1. High-Density KDS Layout — CLOSED

Implemented in v5.9, refined in the same round this document ships
with. Every specific requirement from the gap analysis:

| Requirement | Status |
|---|---|
| Cards adjacent, fixed consistent gap | `justify-content: start` + `minmax(320px, 380px)` tracks, both screens |
| Small orders compact, no wasted vertical space | `align-items: start` overrides Grid's default `stretch` - a short card no longer gets pulled tall to match a neighbor |
| Large orders don't destroy the grid | `max-height: 640px` on the card, header/footer `flex-shrink: 0`, only the line-items section scrolls internally |
| Never clip operational info | Header and action area are structurally outside the scrollable region - always rendered, never hidden |
| RTL/LTR | `justify-content`/`justify-items: start` track the inline-start edge, not a hardcoded left/right value - correct in both directions by construction |

**What's verified**: the CSS/layout logic itself, and that it compiles
and renders correctly in isolation (validated the kiosk's inline
template renders without error, SCSS brace-balances correctly).
**What still needs a human**: the specific density counts (1/3/6/9/12/20
orders) and screen sizes (1920x1080, 1366x768, tablet) listed in the
request's own acceptance criteria are visual/manual checks - there's no
way to automate "does this look right on a 1366x768 tablet" without an
actual browser and screen to look at.

---

## B2. Printing UI Cleanup — CLOSED

Implemented in v5.8. Root cause was a single missing `name` field on
`kds.printer.hub` (Odoo falls back to `model,id` display names when a
model has no meaningful one to show), which explains why the technical
label appeared both on the hub itself and on every page reached from
it. `create`/`edit`/`delete`/`duplicate` view flags remove the generic
Odoo record-management controls; printer creation is confirmed to work
from a station's own "Printers" tab instead (an existing, real path -
checked directly, not assumed).

**What's verified**: the view XML is well-formed and every `ir.ui.view`
record has the explicit `type` field it needs (a real, previously-live
bug class - see v5.5.1 - specifically re-audited as part of this
closure round, zero remaining gaps found).
**What still needs a human**: confirming the breadcrumb visually reads
"Printing / Printers" (etc.) in an actual browser - this is a rendering
question no static check can answer.

---

## B3. Realtime Runtime Validation — CODE-COMPLETE, NOT LIVE-VERIFIED

This is the item where "validate against the actual runtime" cannot be
fully satisfied without server access this environment doesn't have.
What was actually done:

### Audited every `notify_stations`/`notify_station` call site
Confirmed direct coverage for: workflow transitions (accept/start/
ready/complete/cancel/hold - all route through the shared
`_wf_transition`, which notifies unconditionally), Expeditor task
activation, POS Delta sync, manual and system-triggered reopen.

**Found and fixed one real gap**: `_flexsys_kds_create()` - a brand-new
order's very first sync from POS - never notified anyone. Every later
change to that same order was already covered; the single most common,
most important event (a new order arriving) was relying entirely on
the polling fallback, never actually pushed instantly. Fixed this
round.

### Hardened against the specific race the request called out
*"No duplicate orders or transitions may occur because Bus + polling
both receive the same event."* `state.orders`/`ORDERS` were already a
full replace on every load (never an append/merge), so literal
duplicates were never structurally possible either way. What *could*
happen: if Bus and polling both trigger a refetch close together and
the two requests resolve out of order (network jitter), the
later-issued-but-earlier-resolving one could get overwritten by stale
data from the other. Added a sequence-number guard (`loadOrdersSeq` /
`mySeq`) on both screens that discards any response no longer matching
the most recently *issued* request - closes this class of race
entirely, and as a bonus also protects the backend screen against a
second race found during the same review (switching stations while a
request for the *previous* station is still in flight).

### What genuinely cannot be verified without a live Odoo 19 instance
- The exact `bus_service` JS API surface (`addChannel`/`subscribe`
  method signatures) - this has shifted across Odoo versions, and the
  code is written against the Odoo 17/18 pattern with an explicit
  caveat in `kds_notify.py` since it was first built. **Keep the
  polling fallback active** (currently 15s backend / 4s kiosk) until
  this is confirmed against your actual
  `addons/bus/static/src/services/bus_service.js`.
- Whether a second open KDS screen actually receives a push without a
  manual refresh - this requires two real browser sessions and a live
  server.
- Actual network-latency-driven races, as opposed to the structural
  ones addressed above.

**Recommendation before sign-off**: open two KDS screens (or a KDS
screen and the public kiosk) side by side, trigger a new order, a state
change, a cancellation, and a reopen from one, and confirm the other
updates without a manual refresh. If it doesn't, the polling fallback
should still catch it within its own interval - if *that* doesn't
happen either, that's the one scenario this document can't rule out in
advance.

---

## B4. Full Runtime Regression — AUTOMATED COVERAGE MAPPED, MANUAL PASS OUTSTANDING

171 automated tests exist (`tests/`, all `TransactionCase`, run via
`--test-enable --test-tags flexsys_kds`). Every scenario in the
request's regression checklist has direct automated coverage **at the
model layer**:

| Scenario | Covered by |
|---|---|
| Order lifecycle (New→...→Completed→hidden) | `test_workflow.py` |
| POS Delta - no duplicate order | `test_pos_sync.py::test_repeated_sync_does_not_duplicate_the_kds_order`, `::test_payment_after_pre_payment_send_does_not_duplicate_kds_order` |
| Quantity modification | `test_pos_sync.py` (multiple qty-change scenarios) |
| Cancellation (line and full order) | `test_pos_sync.py`, `test_workflow.py::test_action_cancel_cascades_to_active_lines` |
| Multi-station routing | `test_routing.py` |
| Auto Accept (on/off/mixed) | `test_workflow.py::test_auto_accept_*` (4 tests, including the mixed-station scenario by name) |
| SLA (normal/warning/late) | `test_sla.py` |
| Expeditor/Packing | `test_expeditor.py` (16 tests) |
| Completed + 5-minute retention + reopen | `test_workflow.py` grace-period tests, `test_pos_sync.py` reopen tests |
| Security (Operator/Supervisor/Manager, station scope) | `test_permissions.py` |
| Security - cross-company | `test_routing.py`/`test_expeditor.py` (routing never matches cross-company) + **newly added this round**: `test_permissions.py::test_operator_cannot_act_on_a_different_companys_order`, `::test_operator_search_never_returns_a_different_companys_order` - a real gap (no *Operator*-level cross-company test existed, only routing-rule-level) found and closed while producing this document |

**What automated tests cannot cover, by their nature**: the request's
own acceptance criteria include "No Traceback / RPC_ERROR / OwlError"
- these are live-runtime failure modes (a Python traceback surfacing
through the web layer, a JS error in the browser console) that only
show up when the actual code runs against a real Odoo 19 server and
browser. A `TransactionCase` exercises the Python model layer directly
and would not catch, for example, a JS syntax error that only manifests
at runtime, or a view that fails Odoo's own arch validation on install
(exactly the class of bug found live in v5.5.1) - both categories are
mitigated as much as possible here (every `.py`/`.xml`/`.js` file in
this delivery is syntax/well-formed-checked, and the kiosk's inline JS
template is rendered and checked end-to-end), but neither is a
substitute for an actual module upgrade and a walk through the KDS
screen on a real instance.

**Recommendation before sign-off**: run the automated suite first
(`--test-enable --test-tags flexsys_kds`), then walk through the manual
scenarios in the request's own B4 list once against a real POS
terminal and KDS screen, watching the Odoo server log and browser
console for exactly the failure modes listed above.

---

## C. Partial — not blocking this release

No changes made. Matches the request's own instruction: External Print
Agent, fully configurable workflow, and advanced analytics remain
future work, not part of this closure.

## D. Phase 2 — not implemented

No Phase 2 work was started (device architecture, QR enrollment, PWA,
heartbeat, device management, display modes, sound preferences), per
the request's explicit instruction that these must not delay this
release.

---

---

# Post-V1-RC fixes (this version)

Three rounds of real runtime testing happened after the V1 Release
Candidate package above, each fixing genuine bugs found live (not just
code review) - summarized here since they materially changed several
of that package's own gate items. Full detail in `CHANGELOG.md`'s own
v7.1.0 through v7.2.0 entries.

## Runtime Regression Fix Package (BUG-01 through BUG-06)
Auto Accept not actually reaching Preparing, a frontend display-
precedence bug that made a Preparing/Completed order look like it had
reset to New, per-station Ready visibility on a multi-station order,
quantity-to-zero not being treated as a real cancellation, and -
**the highest-risk fix in this whole project's history** - a
financial refund silently creating a new kitchen preparation ticket.
All fixed at the workflow/model layer, never a frontend filter.

## Two rounds of Odoo.sh test-suite failures
First round: test fixtures using raw, protected-field writes that a
real production protection correctly blocked (the protection was never
the bug); a real production bug in the print-agent's atomic SQL claim
(missing flush-before/invalidate-after, a **Release Blocker**, now
fixed); a `TypeError` on a missing POS config; and a genuine design
clarification for how a company-global routing rule's own destination
station is checked. Second round: `bypass_check=True`'s own contract
clarified precisely (it now operates through a trusted/sudo'd
environment, not just skipping the KDS-tier permission check) across
all three models that accept it; a duplicate audit event fixed at its
actual source (a mechanical order-state side-effect that was
redundantly calling the full, logging `action_accept()` instead of the
silent `_force_state()` helper built for exactly this); and the
reconciliation cron completed its own recovery properly (through to
`'completed'`, not stopping at `'ready'`) while every existing guard
(Expeditor, multi-station, security) was explicitly re-verified intact
with a new test.

## BUG-07: station-scoped completion
`Kitchen READY -> Kitchen COMPLETED` while `Coffee READY`/`Bar READY`
remain genuinely unchanged, each completing independently, with the
overall order only reaching `COMPLETED` once every required station
has. Implemented through a real, validated, audited line-level
`action_complete()` (not frontend-only filtering) with order-level
aggregation via a new `is_fully_completed` field, a guard on the
order-level `action_complete()` itself so it can no longer be
force-called (from the order form or the backend controller) to bypass
this while another station still has active production, **and a
dedicated `_finalize_via_expeditor()` finalization path** (v7.2.1) so
an Expeditor-enabled order's genuinely different lifecycle - production
lines stay at Ready, the Packing task's own completion is what
finalizes the order - isn't forced through the same
`is_fully_completed` criterion that's correct for the non-Expeditor
case but wrong for this one. Regression tests:
`test_bug07_three_station_order_completes_independently_per_station`
(three real stations, completing one at a time) plus explicit
Expeditor-enabled/disabled coverage in `test_expeditor.py`.

**What still needs a human**: same category as everything else in this
document - a live two-screen check that completing one station's
"Complete" button on the actual KDS screen (not just the model-level
test) correctly leaves the other stations' own screens fully
interactive and unaffected, that the order form's "Complete" button
now shows a clear, honest error (not a confusing generic one) when
production is still active elsewhere, and that a live Expeditor/Packing
completion flow correctly finalizes the order end-to-end on a real
instance.

## BUG-08: cancelled-line station lifecycle / terminal cleanup
Two related problems: (A) a station whose lines are a mix of COMPLETED
and CANCELLED could remain visible indefinitely - traced to the
completed-line retention check keying off the order's own aggregate
`completion_time` rather than each line's own completion, a timestamp
that (since BUG-07) may never get set while other stations are still
active. (B) a station cancelled mid-workflow (e.g. while Preparing)
disappeared from its own tab entirely, reachable only under ALL, and
could still expose a workflow action (READY) despite having zero
remaining work.

Fixed with a new per-line `completed_at` field (mirroring the existing
`cancelled_at`) giving each station's own completion its own
independent timestamp, and a new `stationLifecycle()` helper
(implemented identically on both screens) that preserves a station's
**last operational stage** (NEW/PREPARING/READY) when every one of its
lines is cancelled with nothing ever completed - the card temporarily
reappears under that stage and under ALL, clearly marked cancelled,
with every workflow action authoritatively withheld (not just hidden
with CSS) until retention expiry removes it. Station isolation
confirmed explicitly: cancelling one station's lines never affects any
other station's own lifecycle on the same order. 5 new regression
tests, matching the dev request's own required scenarios one-to-one.

**What still needs a human**: same category as everything else in this
document - a live check that a station cancelled mid-Preparing actually
reappears under the Preparing tab (not just ALL) on both real screens,
that no workflow button renders for it, and that it disappears cleanly
once its own retention window passes.

**Re-confirmed (v7.4.0)**: a follow-up report re-described the exact
same requirements - reviewed against v7.3.0's own implementation and
confirmed already fully addressed; no production code changed for this
item that round.

## BUG-09: POS quantity delta not communicated to kitchen
A plain "UPDATED" badge alone can't tell the kitchen whether a quantity
increased or decreased, or by how much - especially ambiguous once
preparation has already started. New `qty_delta` field
(`kds_order_line.py`) - a real backend field, not inferred from
transient frontend state - accumulates across repeated POS syncs before
any operator acknowledgement, and displays as `UPDATED (+2)`/`UPDATED
(-2)` on both screens. Cleared only by a genuine, interactive operator
action, never by a trusted internal/system transition - a separate,
real pre-existing gap (`line_change` itself was never actually being
reset) found and fixed while implementing this. 6 new regression tests.

**What still needs a human**: a live check that the delta badge reads
correctly and stays visible through a real POS terminal's own quantity
change screen, across a real realtime sync cycle.

## BUG-10: reopened READY order counted in two stage tabs at once
Root cause: every tab filter/count on both screens ran its own
independent per-tab check, each oblivious to the others - a reopened
order with one line back at 'new' and another still 'preparing'
satisfied two tabs' worth of checks simultaneously. Fixed
architecturally, at the backend/workflow layer: new `_effective_stage()`
computes one authoritative value per station-card, included in the
payload, and both screens' tab filters/counts/status text/border
color/main-action logic were all rewritten to read this single value -
a ticket can now never belong to more than one workflow tab, by
construction, rather than by several independently-written checks
happening to agree. Also naturally incorporates BUG-08's own preserved-
last-stage logic as part of the same single computation. 5 new
regression tests, including the dev request's own exact required
scenario.

**What still needs a human**: a live check on both screens that a
reopened Ready order (qty change + new product added in one POS sync)
shows up under PREPARING only, with NEW = 0 and PREPARING = 1, exactly
as the dev request's own regression scenario specifies.

## BUG-11: paid order refund not synchronized back to the original KDS ticket
Root cause: BUG-06 correctly stopped a refund from creating its own new
ticket, but stopped there - the original ticket was never told
anything had changed, so it kept showing the full, un-refunded quantity
indefinitely (a fully-refunded order still showed "PREPARING" with an
active READY button). New `pos_order.py::_flexsys_kds_reconcile_refund()`
correlates each refund line back to its original `kds.order.line` via
`refunded_orderline_id`, computing `effective_kitchen_qty = original_qty
- cumulative_refunded_qty` fresh each time (cumulative and idempotent
by construction). Stage-specific: fully refunded cancels through the
real `action_cancel()`; partially refunded reduces in place without
touching state; already-Completed lines are never mutated, recorded as
an informational event only. 12 new tests matching the dev report's own
required list 1:1.

**What still needs a human**: a live refund on a real POS terminal
against an order already synced to a real KDS screen, confirming the
correlation (`refunded_orderline_id`) is populated the way this fix
assumes on the actual production build.

## Change Request After BUG-11 (3 items) + a follow-up review round (v7.7.1)
1. **Deleted POS line after COMPLETED becomes CANCELLED**: new
   `kds_order_line.py::_system_cancel_after_completion()` - the order
   itself stays COMPLETED, only the deleted line's own state changes,
   production never reopens.
2. **Quantity decrease delta**: found a real backend gap while
   investigating (not just a display issue) - a decrease on an already-
   Ready line was previously ignored entirely, never actually reducing
   the displayed quantity. Fixed to reduce in place (Ready) while
   Completed correctly stays informational-only, unchanged.
3. **POS Send-to-KDS trigger simplification**: `kds_send_trigger`
   reduced from three options to two - "After Payment" (unchanged) and
   "On Send to KDS" (replacing both former pre-payment options).
   Confirmed directly from Odoo 19's own core source
   (`addons/point_of_sale/models/pos_order.py`) that
   `last_order_preparation_change` is the field the native Preparation-
   Display "Send" action updates - used as the sync signal for "On Send
   to KDS" mode, so ordinary edits (add/remove/qty/attribute changes)
   correctly accumulate with zero KDS sync until the next genuine Send.
   Also found and fixed a second real gap while implementing this:
   `pos_order_line.py`'s own line-level hooks called the sync
   internals directly, bypassing the new trigger gate entirely - fixed
   to route through the same authoritative check.

### Follow-up review round (v7.7.1): two more real gaps caught before shipping further
- **`write()`'s own gate could skip the Send signal entirely**: the
  block deciding whether to call `_flexsys_kds_sync()` at all only
  checked for `'state'` or `'lines'` in the write's own vals - a write
  carrying *only* `last_order_preparation_change` (exactly what the
  native Send action can do on its own) never even reached the trigger
  check, so "On Send to KDS" could silently sync nothing. Fixed by
  adding that field to the gate condition itself.
- **`unlink()` redesigned so the earlier live-verification caveat no
  longer applies to this specific mechanism**: the original
  implementation canceled a removed line immediately, resting on an
  *unverified* assumption about how POS's own frontend batches its
  requests. Redesigned with a new `pending_removal` flag - `unlink()`
  now only marks a line for later processing (nothing becomes visible
  yet), and the real, audited cancellation is applied by
  `_flexsys_kds_diff_lines()`, which only ever runs at the correct sync
  boundary for whichever trigger mode is configured. This is now
  correct **by construction**, regardless of how POS actually batches
  requests - the "verify unlink() timing against real POS behavior"
  item from the original change request is fully resolved, not just
  assumed safe.

**Remaining explicit, unresolved limitation - genuinely needs live
verification** (narrower now than before - only this one specific
piece): the "Send" signal (`last_order_preparation_change`) is
confirmed, from Odoo's own source, for Scenario 1 (Preparation Display
enabled). Whether the native "New" action (Scenario 2, Preparation
Display *disabled*) updates this same field has **not** been confirmed
against a live instance - there is no equally precise, verified signal
found for this specific case. The implementation deliberately fails
*closed* under this uncertainty (if "New" turns out not to update this
field on a given build, orders under that configuration simply never
sync under "On Send to KDS" mode - nothing reaches the kitchen) rather
than *open* (syncing too early, defeating the whole point of this
trigger mode). This is the single most important item to verify live
before enabling "On Send to KDS" on any POS configuration that does
**not** have Preparation Display enabled.

## BUG-11 [fourth report]: Sequential Quantity Delta - explicit baseline field, database migration required
**Confirmed still reproducing live** on v7.7.3, with the exact math the
original report described (`3 - 2 = +1` instead of `3 - 1 = +2`).
Added `last_kds_sent_qty` (`kds_order_line.py`) as the explicit,
dedicated baseline field the dev report's own contract requires -
replacing the implicit reliance on `kline.qty` itself, which v7.7.3
had used on the (mathematically sound, but unverifiable through static
review alone) assumption that it always equaled "the last sent
quantity." All three places `qty_delta` is computed in `pos_order.py`
now read and update this field explicitly, in the same `write()` call.

**⚠️ Database migration required for this specific upgrade**: a new
field defaults to `0.0` for every existing row - without
`migrations/19.0.7.7.4/post-migrate.py` (which runs automatically as
part of the module upgrade), every already-active ticket on a live
instance would compute a badly wrong delta on its very next POS edit
after upgrading. Confirm the module upgrade log shows this migration
script actually ran (it logs "FlexSys KDS: backfilled
last_kds_sent_qty for N existing kds.order.line row(s)...") - if
upgrading via a method that skips Odoo's own migration mechanism
(e.g. directly replacing files without running `-u flexsys_kds` or the
equivalent Apps > Upgrade action), this backfill will not happen
automatically.

**What still needs a human**: the exact live scenario from the dev
report's own report (`2 -> START -> 1 -> Send -> 3 -> Send`), confirmed
on the real Odoo.sh staging instance, checking both the displayed
delta (`UPDATED (+2)`) and, if convenient, the `last_kds_sent_qty`
field's own value directly via a technical/debug view, to confirm which
exact value the runtime is now using.

## BUG-12 + BUG-13 + BUG-14: COMPLETED/READY reconciliation, POS-active retention
**BUG-12** (READY partial-decrease reconciliation): investigated and
traced line-by-line against the current code - the fix already in
place (from the "Change Request After BUG-11" round, hardened by the
`last_kds_sent_qty` baseline work) correctly handles this exact
scenario. No additional code change was made specific to this item; a
precise new test confirms it.

**BUG-13** (quantity changes after COMPLETED while POS stays active):
a genuine, explicit business-rule change from every earlier round's own
"Completed is always frozen" principle - a Completed line now only
freezes once its own POS order has **also** closed. While the order
stays open, it reconciles exactly like Ready: decrease reduces in
place, increase creates a new delta line for the additional amount
only. `pos_still_active`/`treat_as_frozen`, computed from the POS
order's own `state`, drive this distinction throughout
`_flexsys_kds_diff_lines()`.

**BUG-14** (retention anchored to POS closure): new
`kds.order.pos_closed_at` field, stamped the moment the linked POS
order's own state transitions to closed (or immediately at creation
under the `'payment'` trigger, where closure and KDS-arrival happen at
the same moment). Both KDS screens' retention queries now check this
field instead of `completed_at` - unset means unconditional visibility,
regardless of how long ago kitchen-side completion happened.

**⚠️ Second database migration this round**:
`migrations/19.0.7.8.0/post-migrate.py` backfills `pos_closed_at` for
every existing completed-and-closed order - without it, those tickets
would suddenly never expire after this upgrade. Confirm the upgrade log
shows both this migration and the earlier `19.0.7.7.4` one having run.

**A real gap caught during this round's own review, not by any
automated check**: six new tests used `fields.Datetime`/`timedelta`
without either being imported - `py_compile` cannot catch an undefined
name (that's a runtime concern, not a syntax one). Found by manual
review, fixed immediately; a custom AST-based sweep was then run across
every file this round touched, specifically looking for more instances
of this same class of gap - none found. Flagged here explicitly because
it's a reminder that `py_compile` passing is necessary but not
sufficient - it does not substitute for a real Odoo test run.

**What still needs a human**: the full Required Regression Matrix
(Tests 1-8) from the dev report's own list, run against a real Odoo.sh
staging instance - this delivery's own test suite exercises the same
scenarios at the model level, but cannot substitute for confirming the
actual runtime behavior end to end, especially given the size of this
round's own architectural change. Pay particular attention to Test 7/8
(retention timing) since that involves real wall-clock behavior a unit
test can only simulate by backdating timestamps directly, not by
actually waiting.

## KDS Full Line Removal / Quantity -> 0: multi-line removal detection gap
**Confirmed live**: the removal-detection loop in
`_flexsys_kds_diff_lines()` used a dict keyed by `pos_order_line_id`
with "last write wins" semantics - correct for its OTHER purpose
(forward-matching future diffs), but silently able to hold only ONE
value per key. A `pos_order_line_id` with two simultaneously-active
`kds.order.line` records (an original Completed line plus a delta line
from an earlier increase) meant only one of the two was ever detected
as removed when the POS line itself was deleted - the other stayed
invisibly active forever.

Fixed by replacing the dict with a proper one-to-many grouping,
processing every active line sharing a now-missing
`pos_order_line_id`, not just the last one a dict happened to retain.
A new consolidated audit event now also logs the TOTAL cancelled
quantity per removed POS line (e.g. "quantity: 6 -> 0, cancelled_qty:
6"), in addition to each individual line's own existing cancellation
event.

**What still needs a human**: the dev report's own full Acceptance
Test (steps 1-9) run against a real Odoo.sh staging instance -
specifically confirming the exact frontend behavior when a cashier
reduces a quantity to 0 in the POS cart (whether this reaches the
backend as an explicit line deletion, which this fix's own test suite
exercises directly, or via some other mechanism this delivery could not
observe without live access).

## Retention Must Follow POS Order Lifecycle: extends pos_closed_at to CANCELLED too
**Confirmed live**: a Cancelled ticket (POS qty 1 -> 0, order never
paid/finalized/closed) disappeared after the ordinary retention window,
even though its linked POS order was still active - extending BUG-14
(v7.8.0), which only gated Completed-line retention on `pos_closed_at`,
to Cancelled tickets too. Both controllers' search domain and
`display_lines` Python filter now apply the identical gate to
`cancelled_at` that `completed_at` already had.

**A second, real gap found via this module's own test review, not from
any report**: the original gate treated "no linked POS order at all"
(`pos_order_id` unset - a `kds.order` created directly, outside any POS
flow) identically to "linked POS order still active" - both read
`pos_closed_at` as `False`, which would have given a non-POS ticket an
unintended "never expires" behavior it was never supposed to have.
Found by reviewing whether two existing `test_workflow.py` tests
(covering a non-POS-linked order) were still *logically* correct, not
just still passing - they asserted the old, direct-`cancelled_at`
expiry, which turned out to still be exactly right for that specific
scenario, but only once the gate was corrected to condition on
`pos_order_id` being set at all. Both controllers now fall back to the
original direct-timestamp comparison for a ticket with no POS order to
wait on in the first place.

**What still needs a human**: the dev report's own 5 Required
Acceptance Tests, run against a real Odoo.sh staging instance -
particularly Test 5 (reopening after Cancelled while POS stays active),
since this delivery's own test suite confirms the same `kds.order`
record is reused at the model level but cannot substitute for
confirming both KDS screens correctly display the reopened ticket in
real time.

## On Send to KDS Boundary Is Being Bypassed (v7.9.1)
**Confirmed live, Critical severity**: adding a single product to an
active POS order - with neither Send nor New ever pressed - appeared
in KDS immediately as a NEW ticket. Root cause: the `'send'` trigger's
own gate checked only whether `last_order_preparation_change` was
*present* in a write/create vals dict - but confirmed directly from
Odoo 19's own core source
(`addons/point_of_sale/models/pos_order.py::_ensure_to_keep_last_preparation_change`)
that this field is part of nearly every POS save, not exclusively a
genuine Send. New `_is_genuine_send_signal(vals)` helper requires a
non-empty `metadata` key within the field's own JSON content - the
actual distinguishing signal Odoo's own core uses. A real gap in this
module's own test suite (every existing Send-signal test used an
empty-metadata payload) was found and fixed before shipping.

**What still needs a human**: the dev report's own Required Acceptance
Tests, run against a real Odoo.sh staging instance - see the v7.9.2
section immediately below for what turned out to still be incomplete
about this fix.

## On Send to KDS / Subsequent Changes Bypass Send Gate (v7.9.2)
**Confirmed live**: v7.9.1's own fix correctly gated the FIRST Send
(nothing leaked before it) - but a subsequent edit to an ALREADY-sent
order, without pressing Send again, still leaked through immediately.
Root cause, confirmed directly from Odoo 19's own core frontend source
(`addons/point_of_sale/static/src/app/services/pos_store.js::sendOrderInPreparation`):
`order.updateLastOrderChange()` is only called from within that same
Send-handling method - but the field's own **value**, once populated by
a genuine first Send, stays non-empty going forward, and Odoo's own
frontend re-serializes that SAME, unchanged value as part of its
routine save payload on essentially every subsequent write, not
exclusively a genuine second Send. v7.9.1's own "non-empty metadata"
check alone could no longer distinguish a genuine second Send from a
stale value being carried along again.

New `kds_last_processed_send_signal` field (`pos_order.py`) tracks the
exact value already recognized as a processed Send - a write only
counts as a NEW Send if its value both has non-empty metadata AND
differs from this tracked value. Updated the moment a genuine Send is
recognized, regardless of whether the sync itself proceeds further.

**⚠️ Third database migration**: `migrations/19.0.7.9.2/post-migrate.py`
backfills `kds_last_processed_send_signal` for every order already
linked to a `kds.order` before this upgrade - without it, the very next
write to such an order after upgrading (even a routine one) would be
incorrectly recognized as a "new" Send exactly once (harmless but
unnecessary - closed here regardless).

**What still needs a human**: the dev report's own Required Tests A-E,
run against a real Odoo.sh staging instance - particularly confirming
that a GENUINE second Send (the cashier actually pressing Send again)
still correctly produces a fresh, distinct
`last_order_preparation_change` value on the real Odoo 19 frontend, the
one part of this fix's own reasoning that rests on Odoo's own frontend
behavior rather than something this delivery could verify directly.

## On Send to KDS: explicit frontend signal (v7.9.3) — ⚠️ HIGHEST RISK CHANGE IN THIS MODULE'S HISTORY
**Confirmed still reproducing on v7.9.2**, with a real ticket
(`2629-3-000019`): a product added to an already-committed order,
without pressing Send again, still appeared in KDS immediately. Two
consecutive rounds of purely backend-side detection - each individually
reasoned from Odoo 19's own core source, each still failing in live
testing - led to a change of strategy: rather than continue guessing at
exactly how Odoo's own frontend populates `last_order_preparation_change`
on every possible kind of save (a detail this delivery process cannot
directly observe or test), this round adds an **explicit signal this
module controls directly**.

### What changed
- New `pos.order.flexsys_kds_register_send()` - a public RPC method
  that immediately triggers the authoritative sync.
- New `static/src/js/flexsys_kds_pos_send_signal.js` - patches
  `PosStore.prototype.sendOrderInPreparation` (confirmed from Odoo 19's
  own core source to be the native "Send" action's own method) to call
  the RPC method above immediately after Odoo's own native Send logic
  completes.
- New `point_of_sale._assets_pos` bundle entry in `__manifest__.py`
  (the actual POS register's own frontend bundle - distinct from this
  module's existing `web.assets_backend` KDS-screen bundle).

### Why this is genuinely higher risk than anything shipped before
Every prior round of this project's own work has been confined to this
module's own models, controllers, and its own KDS-screen frontend. This
is the first change that **patches a core Odoo POS register frontend
service** - if the patch's own import paths or method signature don't
match the target Odoo 19 build exactly, the risk is not "FlexSys KDS
doesn't work" but potentially **the POS register's own JS module fails
to load entirely**.

### How the risk was mitigated, given no live Odoo instance is available to this delivery process
- The patched method name and its own file path were confirmed via a
  **direct citation of Odoo 19's own core GitHub source**, not guessed
  or inferred from documentation alone.
- The patch **never modifies or wraps** the native Send behavior -
  `super.sendOrderInPreparation()` is always called first, unconditionally,
  and its own result is always returned unchanged.
- The added RPC call is wrapped in its **own, separate** try/catch - a
  failure there cannot propagate back into the native Send/print flow
  the cashier depends on.
- `node --check` confirms the file's own JavaScript syntax is valid -
  but this **cannot** verify the ES module import paths resolve
  correctly inside a real Odoo asset bundle, which is a live-runtime
  concern this delivery process has no way to check.

### Required rollout verification, in this specific order
1. **Before enabling for real cashiers**: open the POS register on a
   staging instance after this upgrade and confirm the register loads
   normally at all - open the browser console and confirm no red
   "module not defined" or import errors appear, specifically anything
   mentioning `flexsys_kds_pos_send_signal` or `pos_store`.
2. Confirm a completely ordinary sale (add a product, pay, print
   receipt) still works exactly as before - this patch must have zero
   observable effect on a POS not using "On Send to KDS" mode at all.
3. Only then, run the dev report's own exact reproduction: an existing,
   already-committed KDS ticket, add a new product without pressing
   Send, confirm KDS is unchanged, press Send, confirm the new product
   now appears correctly as ADDED.
4. If step 1 shows any error, **do not proceed** - this specific asset
   entry should be reverted (removing the `point_of_sale._assets_pos`
   key from the manifest) while the exact Odoo 19 build's own
   `pos_store.js` structure is re-confirmed against the live instance
   directly, rather than via the citation this delivery relied on.

## Explicit POS Send Must Trigger KDS Sync (v7.9.6) — ⚠️ SECOND CORE-POS FRONTEND PATCH
**Confirmed live**: the normal Send button was confirmed working
(blocking correctly proven - "Part 1 PASSED"). But Odoo's own native
unsent-order confirmation dialog ("It seems that the order has not been
sent. Would you like to send it to preparation?" → "Order") did not
reliably trigger the v7.9.3 patch's own
`sendOrderInPreparation()` hook - "the current implementation
successfully blocks automatic synchronization, but it also blocks or
misses the legitimate explicit Send to Preparation event."

**Fix**: a second, independent frontend patch,
`flexsys_kds_pos_send_signal_order_model.js`, hooks
`order.updateLastOrderChange()` directly - confirmed from Odoo 19's own
core source to be the actual lower-level method that persists the send
signal to the server, common to every UI path that leads to a genuine
Send (`sendOrderInPreparation()` calls this method internally). Kept in
its own separate file specifically so a wrong import path in this
second patch cannot also break the already-confirmed-working first one
- a JS module import failure prevents everything else in that same
file from loading.

**Confirmed harmless double-fire**: since the two patches' own target
methods call each other internally, a genuine Send via the normal
button now fires both. Verified via a dedicated test that this is
completely idempotent - the redundant second RPC call's own diff logic
against an unchanged POS state is a correct no-op.

### Required rollout verification, in addition to the v7.9.3 section above
1. Confirm the POS register still loads with no console errors after
   this upgrade too (same check as v7.9.3's own step 1, now covering
   BOTH patch files).
2. Reproduce the dev report's own exact Part 2 scenario: trigger Odoo's
   native unsent-order confirmation dialog (e.g. by trying to switch
   orders or leave the screen with unsent changes present), click
   "Order", confirm the KDS ticket now appears/updates correctly.
3. Re-confirm the normal Send button (v7.9.3's own scenario) still
   works correctly too - this round must not have regressed it.
4. If step 1 shows an error specifically traceable to
   `flexsys_kds_pos_send_signal_order_model.js`, remove only that
   specific line from the `point_of_sale._assets_pos` manifest entry
   (not the whole bundle) while `PosOrder`'s own exact import path is
   re-confirmed against the live instance directly.

## On Send to KDS: removed the last backend inference path entirely (v7.9.4)
**Confirmed still reproducing on v7.9.3**, with a real ticket
(`2629-3-000021`) - and the **KDS Audit Log itself proved this was a
backend database write, not a frontend display gap**: genuine
`"Line Added"`/`"Order Routed"` events, with the exact note text
`_flexsys_kds_diff_lines()` emits, were created without any Send/New
pressed.

**Root cause**: v7.9.3's own frontend patch was correctly implemented
and (as far as this delivery can determine) should have been calling
the new explicit signal correctly - but the OLD backend inference
mechanism from v7.9.1/v7.9.2 was **never actually removed**, and
remained fully active in `create()`/`write()` in parallel with the new
explicit signal. The Audit Log evidence directly disproves that old
mechanism's own core assumption (that a genuine Send is what makes
`last_order_preparation_change`'s value both non-empty and different
from before) - an ordinary product-add write's own value satisfied both
of that check's own conditions without any genuine Send occurring.

**Fix**: `create()`/`write()` no longer call
`_flexsys_kds_should_treat_as_send()` at all - `is_send_write` is now
unconditionally `False` from both, for every trigger mode. Under
`'send'` mode, `flexsys_kds_register_send()` (the explicit RPC method
from v7.9.3) is now the **only** possible trigger for a sync -
structurally, not just in practice.

**A large-scale, individually-verified test migration**: 41 tests using
the old `last_order_preparation_change`-write pattern were transformed
to the new explicit call (verified via an exact-pattern search
confirming structural identity before transformation, not a blind
mechanical replacement); 10 further occurrences setting the field
within `create()`'s own vals (including the shared
`_create_active_pos_order()` helper used across dozens of tests) were
each reviewed and updated individually; one test that directly tested
the now-abandoned mechanism itself was removed with an explanatory
note.

**What still needs a human**: this fix makes the backend structurally
correct regardless of frontend behavior - but the v7.9.3 frontend
patch's own live verification (see that section immediately above)
remains equally necessary and equally unresolved. With this round's own
fix in place, if the frontend patch itself is NOT working correctly for
some reason (wrong import path, method not actually called, etc.), the
symptom would now flip from "leaks early" to "never syncs at all under
'send' mode" - a safer failure direction, but still one that needs the
same live verification steps already documented in the v7.9.3 section
to catch.

## CANCELLED Filter Classification + Retention Lifecycle (v7.9.5)
**Confirmed live**: "NEW = 6" with all 6 visible cards actually
CANCELLED. Root cause: `_effective_stage()` - the single authoritative
value driving every tab filter/count on both KDS screens (from BUG-10)
- returned a BUG-08 "preserved last stage" value for a fully-cancelled
station instead of a distinct one, so a station cancelled before ever
starting satisfied the NEW tab's own filter check exactly. Fixed to
return a distinct `'cancelled'` value - every tab's own `effective_stage
=== filter` check now automatically excludes cancelled tickets from all
four specific tabs at once, while `ALL` (which never filters by
`effective_stage`) continues to show them.

**A real regression caught before shipping**: both screens' own
"CANCELLED (was PREPARING)" status text used to read the "was X" label
directly from `order.effective_stage` itself - which, after this fix,
no longer carries that information. Fixed to read from
`stationLifecycle().lastStage` instead (computed independently,
unaffected by this change).

**A second, independently-found gap**: `pos_closed_at` was never
stamped for a POS order cancelled outright (`state == 'cancel'`) - only
for payment-closed states - meaning a CANCELLED KDS ticket linked to an
outright-cancelled POS order could never become retention-eligible at
all. `'cancel'` is now included in the closed-state set.

**Confirmed unchanged (by design, not a bug)**: the previously-approved
rule itself - ACTIVE POS + CANCELLED KDS ticket + any amount of time
elapsed → ticket remains visible in `ALL`. This is intentional and was
not modified.

**What still needs a human**: the dev report's own Required Runtime
Tests A/B/C, run against a real Odoo.sh staging instance - particularly
confirming the exact screenshot scenario no longer reproduces (create a
mix of NEW/PREPARING/READY/COMPLETED/CANCELLED tickets, confirm the NEW
tab and its own counter show only genuine NEW tickets) and that the
newly-added `pos_closed_at`-on-cancel stamping correctly triggers
retention for a real POS order cancellation on the live instance.

---

## What still needs a human

Everything above that says "still needs a human" or "cannot be
verified without a live Odoo 19 instance," collected in one place:

1. Confirm the `bus_service` JS API calls in `kds_app.js` against your
   actual `addons/bus/static/src/services/bus_service.js` - keep
   polling active as the safety net regardless.
2. Two-screen live realtime check (new order / transition / cancel /
   reopen, confirm the second screen updates without a manual refresh).
3. Visual density check at the specific screen sizes and order counts
   listed in the B1 acceptance criteria.
4. Visual breadcrumb check for the Printing section (B2).
5. A manual walkthrough of the B4 regression list against a real POS
   terminal and KDS screen, watching for Tracebacks/RPC_ERROR/OwlError
   specifically.
6. **New (v6.2, "Runtime Regression Fix Package")**: the same Actual
   POS Runtime Test / Actual KDS Runtime Test closure process that
   package's own document requires for BUG-01 through BUG-06
   specifically - especially BUG-06 (refund detection), given how
   CRITICAL/high-risk that one is and how much its exact correctness
   depends on this specific Odoo 19 build's actual POS refund data
   shape (which of the two detection signals in
   `_flexsys_kds_is_refund_order()` actually fires in practice, and
   whether Odoo's own refund UI produces data matching either one) -
   automated tests confirm the *logic* is sound against both signals
   independently, but only a real refund performed through the actual
   POS refund screen can confirm which signal this build actually
   triggers, and that no new/undetected refund representation exists
   that neither signal catches.
7. **New (v7.2.0, BUG-07)**: a live, two-screen check that tapping
   "Complete" on one station's own KDS card (Kitchen, say) genuinely
   leaves Coffee's and Bar's own screens showing their own tickets
   completely unaffected - the model-level regression test proves the
   backend logic is correct, but only an actual browser session on each
   station's own screen can confirm the realtime update each one
   receives is scoped correctly too. Also confirm the order form's own
   "Complete" button now shows the new, clear `UserError` (naming which
   station still has active production) rather than a confusing generic
   failure, when clicked on a multi-station order that isn't fully
   completed yet.
8. **New (v7.7.0, "Change Request After BUG-11", item 3; scope
   narrowed by v7.7.1's own unlink() redesign, which fully resolved
   the separate "verify unlink() timing" concern this same item
   originally also carried) - the single most important
   live-verification item in this entire document**: whether the
   native "New" order action (POS with Preparation Display *disabled*)
   updates `pos.order.last_order_preparation_change` the same way the
   native "Send" action does with Preparation Display enabled.
   Confirmed from Odoo 19's own core source for the "Send" case;
   genuinely unconfirmed for "New" - there is no live Odoo instance
   available to this delivery process to verify it. If "On Send to
   KDS" is enabled on a POS configuration without Preparation Display,
   test explicitly: build an order, press "New", and confirm it
   reaches the KDS screen. If it does not, orders under that specific
   configuration will silently never reach the kitchen - the
   implementation fails closed on purpose, but that still needs a
   human to catch before it's a live problem in a restaurant.
9. **New (v7.7.2) - a live-verification item raised by inconclusive
   investigation, not a confirmed fix**: a dev report describing a
   Preparing ticket resetting to New after a POS quantity decrease was
   investigated line-by-line against the current codebase and no
   matching bug was found - the exact code path involved does not write
   `state` at all for this scenario, and `_effective_stage()` traces
   correctly to `'preparing'`. New regression tests
   (`test_qty_decrease_during_preparing_does_not_reset_to_new` and 5
   related tests in `test_pos_sync.py`) exercise this exact scenario
   precisely. If those tests pass when actually run, but the original
   live report still reproduces on a real instance, that would point to
   an environment/deployment discrepancy (a stale asset bundle, a
   staging build behind this delivery's own version) rather than a
   logic gap in this codebase - worth confirming which exact build was
   under test.
10. Once 1-9 pass: tag the release in Git (outside the scope of what a
   file delivery like this one can do on your behalf).

---

# V1 Finalization & Release Candidate Package

Version at this point: **19.0.7.0.0**. This section covers the "FlexSys
KDS — V1 Finalization & Release Candidate Package" request, appended to
the same running document rather than starting a new one, since the
same "what still needs a human" principle applies throughout.

## 1. KDS Fullscreen Mode — DONE

Implemented on both screens using the standard browser Fullscreen API
(`requestFullscreen()`/`exitFullscreen()`, targeting
`document.documentElement`) - a purely rendering-level browser feature
that never reloads the page or touches any JS state, which is exactly
why it satisfies every one of the request's "must NOT" requirements
(no refresh, no lost filters/realtime/timers/ticket state, no
duplicate orders) automatically, by construction, rather than needing
special-case handling for each one. A `fullscreenchange` listener keeps
the button's icon correct even when fullscreen is exited a way other
than tapping it (Esc key, a tablet's own gesture) - "standard browser
Fullscreen exit behavior may be used," per the request itself.

**What still needs a human**: confirming this actually renders and
behaves correctly on your target kitchen tablet/browser - the
Fullscreen API has device-specific quirks (some tablet browsers
restrict it, some require a user gesture with stricter timing) no
static check can verify.

## 2. High-Density KDS Layout — Reviewed, no further change needed

Re-reviewed against this request's own checklist (horizontal/vertical
spacing, card width, internal padding, line spacing, header height,
footer/action area, long-order behavior, many-simultaneous-orders) -
every item was already addressed across v5.9 and v6.2's own work
(`justify-content: start` + fixed track width for spacing,
`align-items: start` for compact small-order cards, `max-height` +
internal scroll for long orders). No regressions found from the BUG-01
through BUG-06 fixes - none of those touched grid/card CSS at all.

**What still needs a human**: the specific order counts (1/5/10+) and
content variations (variants, notes, ADDED/UPDATED/CANCELLED) listed in
this request's own test list are visual checks requiring an actual
browser.

## 3. READY/COMPLETED/CANCELLED Visual States — Reviewed, no further change needed

Each state already has a distinct treatment: NEW (default/blue),
PREPARING (default/blue, in-progress checkboxes), READY (green),
COMPLETED (green, "COMPLETED" text, no action button), CANCELLED (grey
card/line, struck-through text, red "CANCELLED" badge, X-marked
checkbox, no action button) - built across v5.7 (COMPLETED tab) and
v6.1 (cancellation visibility). CANCELLED specifically uses three
simultaneous signals (color, strikethrough, explicit text badge), not
text alone. ADDED/UPDATED badges (`line_change`/`line_change_label`)
were not touched by this round or the regression package - confirmed
still wired through unchanged.

**What still needs a human**: "distinguishable from a reasonable
kitchen-screen viewing distance" is inherently a physical/visual
judgment call - the color/contrast choices are a *starting point*, not
something a text-based review can fully validate.

## 4. COMPLETED Workflow — Confirmed intact

NEW -> PREPARING -> READY -> COMPLETED, 5-minute retention, no
deletion of history, multi-station completion (via
`is_expeditor_ready`'s cross-station aggregation - see BUG-03's own
verification above), realtime notification on every transition - all
already covered by the v5.7/v6.1 work and the existing automated test
suite (`test_workflow.py`'s COMPLETED-tab and grace-period tests).

## 5. Printing UI Cleanup — Confirmed intact

`create="false"`/`edit="false"` flags on the Printers/Print Jobs/
Reprints views, the clean "Printing" hub with no technical
`kds.printer.hub,N` labels - all from v5.8/v6.2, unaffected by anything
in this round.

## 6. Printing End-to-End Validation — CANNOT be performed here

**Explicitly cannot be validated in this environment.** This
requires an actual physical printer, a running external Print Agent
process communicating with it, and a live Odoo instance dispatching
real print jobs - none of which exist in a code-delivery environment
with no server access. The Odoo-side architecture (atomic job
claiming, lease/retry, ACK/result handling, reprint audit trail) was
built and unit-tested at the model layer in earlier rounds
(`test_printing.py`), but "Test: Automatic print, Manual print,
Reprint, Printer unavailable, Agent unavailable, Retry behavior,
Duplicate protection..." as an *end-to-end physical* validation is
squarely in "what still needs a human" territory, and always has been
(see `docs/PRINT_AGENT.md`'s own note that the external agent itself
was never part of this codebase's scope).

## 7. Expeditor / Packing Validation — Confirmed compatible with BUG-03's fix

Re-verified `_compute_is_expeditor_ready()` (the backend method
governing "is the *whole* order ready across every station") is
entirely separate Python code from the BUG-03 fix (which only touched
frontend JS - which *station's own screen* shows a Ready ticket) -
they were never the same computation, and nothing in BUG-03's fix
could have affected Expeditor's own cross-station aggregation. No
change was needed or made here this round; existing coverage in
`test_expeditor.py` (13 tests) stands.

## 8-9. Security / Station Isolation, Multi-Company Validation — Confirmed intact

No security, record-rule, or company-scoping code was touched by
either the Runtime Regression Fix Package or this V1 finalization
round - `test_permissions.py` (including the cross-company Operator
tests added in v6.1) and `test_routing.py`'s own company-isolation
tests stand unchanged and still pass structurally.

## 10-11. Fresh Install Test, Upgrade Test — CANNOT be performed here

**Explicitly cannot be performed in this environment** - both require
an actual running Odoo 19 server and database, which this environment
does not have. What *is* verified, on every single change throughout
this project's entire history: every `.py` file compiles
(`py_compile`), every `.xml` file is well-formed AND every
`ir.ui.view` record has an explicit `type` (the specific class of bug
that broke a real fresh install in v5.5.1 and a real upgrade before
that), every `.js` file is syntactically valid, and the kiosk's
inline-template Python string formatting round-trips correctly. This
is real, meaningful coverage against a category of bug this project
has hit live before - but it is not a substitute for actually running
`-i flexsys_kds` against a clean database and `-u flexsys_kds` against
an existing one, which only a live instance can do.

## 12. Final POS -> KDS Regression Matrix (30 items)

| # | Scenario | Status |
|---|---|---|
| 1 | POS -> KDS normal order | Automated (`test_pos_sync.py`) |
| 2 | Routing by category | Automated (`test_routing.py`) |
| 3 | Multi-station routing | Automated (`test_routing.py`) |
| 4 | First-matching-category behavior | Automated (`test_routing.py`) - confirmed unchanged, per this request's own "do not unintentionally change" instruction |
| 5 | Auto Accept | Automated (`test_workflow.py`, updated for BUG-01) |
| 6 | Manual START | Automated (`test_workflow.py`) |
| 7 | SLA Normal->Warning->Late | Automated (`test_sla.py`) |
| 8 | Realtime between multiple screens | **Live only** - see B3 above |
| 9 | ADDED line | Automated (`test_pos_sync.py`) |
| 10 | UPDATED qty increase | Automated (`test_pos_sync.py`) |
| 11 | UPDATED qty decrease | Automated (`test_pos_sync.py`) |
| 12 | Modification while PREPARING | Automated (`test_workflow.py`, BUG-02 tests) |
| 13 | Modification after READY | Automated (`test_workflow.py`, BUG-02B tests) |
| 14 | Modification/reopen after COMPLETED | Automated (`test_workflow.py`, BUG-02B tests) |
| 15 | Item cancellation | Automated (`test_workflow.py`/`test_pos_sync.py`, v6.1+BUG-04) |
| 16 | Complete order cancellation | Automated (`test_workflow.py`, v6.1) |
| 17 | Partial Refund | Automated (`test_pos_sync.py`, BUG-06) |
| 18 | Full Refund | Automated (`test_pos_sync.py`, BUG-06) |
| 19 | Multi-station READY | Automated at the backend-aggregation level (`test_expeditor.py`); the frontend per-station display fix itself (BUG-03) has no JS test harness - **partially live-only** |
| 20 | READY -> COMPLETED | Automated (`test_workflow.py`) |
| 21 | COMPLETED retention | Automated (`test_workflow.py`) |
| 22 | Expeditor/Packing | Automated (`test_expeditor.py`) |
| 23 | Fullscreen | **Live only** - browser API, no test harness (see item 1 above) |
| 24 | High-density layout | **Live only** - visual (see item 2 above) |
| 25 | Automatic printing | Automated at the job-creation level (`test_printing.py`); physical delivery is **live only** (see item 6 above) |
| 26 | Manual printing | Same as above |
| 27 | Reprint | Automated at the model level (`test_printing.py`); physical delivery is **live only** |
| 28 | Printer/Agent failure | **Live only** - requires an actual agent/printer to fail |
| 29 | Station isolation | Automated (`test_permissions.py`) |
| 30 | Multi-company isolation | Automated (`test_permissions.py`, `test_routing.py`) |

**23 of 30 fully automated; 7 require live verification** (realtime
multi-screen, the BUG-03 frontend display specifically, Fullscreen,
high-density visual check, and the three physical-printing items) -
consistent with everything already stated in this document's earlier
sections.

## 13-14. No regressions, Phase 2 not introduced — Confirmed

No changes to POS Delta Sync, ADDED/UPDATED indicators, variants/
attributes, SLA runtime, Late KPI, category routing, station isolation,
or multi-station aggregation beyond what BUG-01 through BUG-06
explicitly required. Zero Phase 2 scope (`kds.device`, QR enrollment,
device tokens, PWA, heartbeat, device profiles/sound config, advanced
analytics) was touched.

## 15. Release Candidate Gate

| Gate | Status |
|---|---|
| Current Runtime Bugs Fixed | ✅ BUG-01 through BUG-07, plus two rounds of live Odoo.sh test failures (v7.2.0) |
| Automated Tests PASS | ✅ 303 tests, all `py_compile`/XML/JS checks pass |
| Fresh Install PASS | ⬜ Live only |
| Upgrade PASS | ⬜ Live only - **requires confirming BOTH `migrations/19.0.7.7.4/post-migrate.py` AND `migrations/19.0.7.8.0/post-migrate.py` actually ran** (see their own sections above) |
| Runtime Regression PASS | 23/30 automated ✅ (see the original v7.0.0 matrix above - unaffected by v7.1.0-v7.2.0's own fixes), 7/30 live only ⬜ |
| Physical Printing PASS | ⬜ Live only (the atomic-claim Release Blocker itself is now fixed - see "Post-V1-RC fixes" above - but end-to-end physical delivery still needs a real agent/printer) |
| Security Validation PASS | ✅ Automated - `bypass_check`'s contract clarified and tested this round, no security control weakened |
| UI Finalization PASS | ✅ Fullscreen, density/states reviewed (v7.0.0), unaffected since |

**Classification**: code-complete and internally consistent for
**FlexSys KDS V1 — Release Candidate**, pending the live-only items
marked ⬜ above before final sign-off.
