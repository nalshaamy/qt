# FlexSys KDS — Manual QA Regression Scenarios

**Status**: Written QA Regression Plan. Replaces the automated test
suite as the release-verification method for this build. The 558
automated tests this document was distilled from are preserved
separately as a development/archive reference (see the module's own
delivery notes for the archive location) — they are **not** part of
this runtime package and are **not** executed by Odoo.

**How to use this document**: each scenario is a self-contained manual
procedure a QA tester runs against a real (or staging) Odoo 19
instance with this module installed. Record the result in the
**PASS/FAIL** column and any observation in **Notes**. A scenario that
fails should be reported with the exact `Actual Result` observed,
matched against its own `Expected Result` here — do not modify
Production to make a scenario pass without review.

**Source of truth**: every scenario below reflects the product
contracts documented in `tests/TEST_CONTRACTS.md` (development
archive) and the actual, current Production code at the time this
document was written — not historical assumptions.

---

## Table of Contents

1. [POS / Quantity](#1-pos--quantity) (14 scenarios)
2. [Workflow](#2-workflow) (10 scenarios)
3. [Routing](#3-routing) (8 scenarios)
4. [Expeditor / Packing](#4-expeditor--packing) (9 scenarios)
5. [Printing](#5-printing) (11 scenarios)
6. [Security / Kiosk](#6-security--kiosk) (12 scenarios)
7. [SLA](#7-sla) (7 scenarios)
8. [Arabic / RTL](#8-arabic--rtl) (8 scenarios)
9. [Outstanding Items — Do Not Fix Now](#9-outstanding-items--do-not-fix-now)

**Total: 79 scenarios.**

---

## 1. POS / Quantity

### POS-01 — First Send creates one KDS order
**Preconditions**: A KDS station is configured and eligible for the
POS in use. No prior order sent.
**Steps**: Add 1 product to a new POS order → press Send (or complete
payment, depending on the configured `kds_send_trigger`).
**Expected Result**: Exactly one `kds.order` is created with one line
matching the sent product/quantity.
**PASS/FAIL**: ___
**Notes**: ___

### POS-02 — Quantity increase does not create a delta until Send
**Preconditions**: Order already sent once (KDS ticket exists),
`kds_send_trigger = 'send'`.
**Steps**: Increase a product's quantity (e.g. 1 → 3) on the POS
without pressing Send again.
**Expected Result**: KDS ticket is unchanged — still shows the
original quantity (1), no delta line yet.
**PASS/FAIL**: ___
**Notes**: ___

### POS-03 — Quantity increase applies only after explicit Send
**Preconditions**: Continue from POS-02.
**Steps**: Press Send.
**Expected Result**: A new delta appears showing **+2** (the increase
only, not the new total of 3). The kitchen sees "UPDATED (+2)", not a
full re-print of 3.
**PASS/FAIL**: ___
**Notes**: ___

### POS-04 — Quantity decrease reconciles immediately
**Preconditions**: Order already sent, ticket exists.
**Steps**: Decrease a product's quantity on the POS (e.g. 3 → 2)
**without** pressing Send.
**Expected Result**: The KDS ticket updates immediately to reflect the
decrease — no Send required.
**PASS/FAIL**: ___
**Notes**: ___

### POS-05 — Quantity → 0 cancels the line immediately
**Preconditions**: Order already sent, line is Ready or Preparing.
**Steps**: Reduce that product's quantity to 0 on the POS.
**Expected Result**: The corresponding KDS line becomes CANCELLED
immediately, without needing a Send.
**PASS/FAIL**: ___
**Notes**: ___

### POS-06 — Sequential 1→3→2 reconciles to the correct final state
**Preconditions**: Order already sent, single line, Ready.
**Steps**: On the POS: change quantity 1→3, then 3→2, in quick
succession, without an intervening Send for the increase step.
**Expected Result**: Final KDS state shows quantity effectively
reconciled to 2 (the true final POS quantity) once fully settled — no
negative quantity anywhere, no duplicate lines.
**PASS/FAIL**: ___
**Notes**: ___

### POS-07 — Repeated Send with no change does not duplicate
**Preconditions**: Order already sent and fully reconciled.
**Steps**: Press Send again with no changes made since the last Send.
**Expected Result**: No new delta line, no duplicate audit event — a
true no-op.
**PASS/FAIL**: ___
**Notes**: ___

### POS-08 — Historical READY lines are preserved on later increase
**Preconditions**: A line has reached READY.
**Steps**: Increase the quantity of that same product on the POS,
then Send.
**Expected Result**: The original READY line's own quantity/state is
**unchanged** — a separate new delta line appears for the increase
only. The kitchen never sees the already-prepared quantity reset to
"New".
**PASS/FAIL**: ___
**Notes**: ___

### POS-09 — Zero-out cancels the entire historical family
**Preconditions**: A product has both an original line (READY) and a
later delta line (also READY or Preparing) from an earlier increase.
**Steps**: Reduce that product's quantity to 0 on the POS.
**Expected Result**: **Both** the original and the delta line become
CANCELLED — not just the most recently created one. No residual
active quantity remains for that product.
**PASS/FAIL**: ___
**Notes**: ___

### POS-10 — Partial refund reduces quantity in place (Preparing)
**Preconditions**: Paid order, line in Preparing.
**Steps**: Process a partial refund for part of that product's
quantity.
**Expected Result**: The KDS line's quantity reduces accordingly and
stays operational (Preparing) — not reset or reopened.
**PASS/FAIL**: ___
**Notes**: ___

### POS-11 — Full refund after Completed is informational only
**Preconditions**: Line already Completed, POS order closed (paid).
**Steps**: Process a full refund for that product.
**Expected Result**: The completed line's own history is **not**
rewritten — the refund is recorded for audit purposes without
altering the finished production record.
**PASS/FAIL**: ___
**Notes**: ___

### POS-12 — Refund never creates a new KDS ticket
**Preconditions**: A closed POS order with no existing KDS order (or
one that's already Completed).
**Steps**: Process a refund against that order.
**Expected Result**: No new `kds.order` is ever created purely by a
refund action.
**PASS/FAIL**: ___
**Notes**: ___

### POS-13 — Item cancellation
**Preconditions**: A line is active (any pre-terminal state).
**Steps**: Cancel that single item from the KDS/backend with a reason.
**Expected Result**: The line becomes CANCELLED with the reason
recorded; other lines on the same order are unaffected.
**PASS/FAIL**: ___
**Notes**: ___

### POS-14 — Full order cancellation cascades correctly
**Preconditions**: A multi-line order, mixed states (some Preparing,
some Ready).
**Steps**: Cancel the entire POS order.
**Expected Result**: Every active line on the KDS ticket becomes
CANCELLED; any already-Completed line's own history remains
untouched/visible per the retention rules.
**PASS/FAIL**: ___
**Notes**: ___

---

## 2. Workflow

### WF-01 — Full happy path: New → Accepted → Preparing → Ready → Completed
**Preconditions**: A freshly sent order, single line.
**Steps**: Accept → Start → Ready → Complete, in order, via the
normal KDS screen actions.
**Expected Result**: Each transition succeeds and is reflected on
screen; final state is Completed with a completion timestamp.
**PASS/FAIL**: ___
**Notes**: ___

### WF-02 — Cannot skip states forward
**Preconditions**: A line in New.
**Steps**: Attempt to mark it Ready directly, skipping Accept/Start.
**Expected Result**: The action is rejected — states cannot be
skipped.
**PASS/FAIL**: ___
**Notes**: ___

### WF-03 — Cannot act on a terminal Cancelled order
**Preconditions**: An order already Cancelled.
**Steps**: Attempt any workflow action (Accept, Start, etc.) on it.
**Expected Result**: Rejected — a Cancelled order/line is terminal.
**PASS/FAIL**: ___
**Notes**: ___

### WF-04 — Hold and resume
**Preconditions**: An active order.
**Steps**: Put the order On Hold, then resume it.
**Expected Result**: The order correctly returns to its prior
in-progress state, production continues normally.
**PASS/FAIL**: ___
**Notes**: ___

### WF-05 — Reopen from Ready lands on Preparing, not New
**Preconditions**: An order at Ready.
**Steps**: Reopen it (e.g. via a genuine production change).
**Expected Result**: The order lands on Preparing — never resets all
the way back to New, preserving whatever production history already
existed.
**PASS/FAIL**: ___
**Notes**: ___

### WF-06 — Reopen from Completed preserves previously completed lines
**Preconditions**: An order fully Completed, then a new line is added
(e.g. via a POS delta).
**Steps**: Observe the reopen that follows the new line's arrival.
**Expected Result**: The order reopens to accommodate the new work,
but every previously-Completed line's own state/timestamps remain
exactly as they were — never rewritten.
**PASS/FAIL**: ___
**Notes**: ___

### WF-07 — Multi-station: each station completes independently
**Preconditions**: An order with lines routed to at least 2 different
stations (e.g. Kitchen + Coffee), all reaching Ready.
**Steps**: Complete Kitchen's line first, observe; then complete
Coffee's line.
**Expected Result**: Completing one station's line does not affect
the other station's own line state. The overall order only reaches
Completed once **every** required station has independently
completed its own portion.
**PASS/FAIL**: ___
**Notes**: ___

### WF-08 — A station can only complete its own routed lines
**Preconditions**: An operator assigned only to Kitchen; an order with
a line at a different station (e.g. Bar).
**Steps**: As that Kitchen-only operator, attempt to complete the Bar
line.
**Expected Result**: Rejected — an operator/station may only act on
lines actually routed to their own station.
**PASS/FAIL**: ___
**Notes**: ___

### WF-09 — Cancelled lines do not block station readiness
**Preconditions**: A multi-line order at one station; one line gets
cancelled (e.g. out of stock) before the rest reach Ready.
**Steps**: Bring the remaining active line(s) to Ready.
**Expected Result**: The station correctly reads Ready with only the
cancelled line excluded from the requirement — it does not wait
indefinitely on a line that will never complete.
**PASS/FAIL**: ___
**Notes**: ___

### WF-10 — Completed/Ready history remains visible after retention window logic
**Preconditions**: A Completed order, POS order still open (active).
**Steps**: Wait past what would normally be a retention/expiry window
for a closed order.
**Expected Result**: A Completed ticket whose own POS order is still
active/open must **not** expire/disappear — retention is tied to POS
closure, not merely completion time.
**PASS/FAIL**: ___
**Notes**: ___

---

## 3. Routing

### RT-01 — Explicit rule wins over every fallback
**Preconditions**: A product has both a product-level default station
AND a category-level default station configured; an explicit routing
rule for that exact product points to a third, different station.
**Steps**: Send an order containing that product.
**Expected Result**: The line routes to the station named by the
**explicit rule** — not either fallback default.
**PASS/FAIL**: ___
**Notes**: ___

### RT-02 — Product-level default fallback
**Preconditions**: No explicit rule matches; the product has its own
default station set.
**Steps**: Send an order with that product.
**Expected Result**: Routes to the product's own default station.
**PASS/FAIL**: ___
**Notes**: ___

### RT-03 — Category-level (inventory category) fallback
**Preconditions**: No explicit rule, no product-level default; the
product's own inventory category has a default station set.
**Steps**: Send an order with that product.
**Expected Result**: Routes to the category's own default station.
**PASS/FAIL**: ___
**Notes**: ___

### RT-04 — Routing Rule sequence ("Priority" label) controls ordering
**Preconditions**: Two explicit rules both match the same product,
with different `sequence`/"Priority" values.
**Steps**: Send an order with that product.
**Expected Result**: The rule with the **lower sequence value** wins
and its station is used — regardless of creation order. **Note**: this
"Priority" label refers only to routing rule ordering (`sequence`) —
it is unrelated to the removed Order Priority/VIP feature.
**PASS/FAIL**: ___
**Notes**: ___

### RT-05 — POS Config isolation
**Preconditions**: A routing rule scoped to a specific POS
configuration only.
**Steps**: Send the same product from a **different** POS
configuration not covered by that rule.
**Expected Result**: That rule does not match; resolution falls
through to the next eligible rule/fallback (or no match).
**PASS/FAIL**: ___
**Notes**: ___

### RT-06 — Company isolation
**Preconditions**: A routing rule and its destination station both
belong to Company A.
**Steps**: Attempt to route a product for a Company B order.
**Expected Result**: The Company-A-specific rule never matches a
Company B order — no cross-company leakage.
**PASS/FAIL**: ___
**Notes**: ___

### RT-07 — Inactive/archived rules are excluded
**Preconditions**: A routing rule that would otherwise match is
archived (set inactive).
**Steps**: Send an order for the matching product.
**Expected Result**: The archived rule is completely ignored —
resolution proceeds as if it didn't exist (falls through to the next
level).
**PASS/FAIL**: ___
**Notes**: ___

### RT-08 — No duplicate KDS lines from multiple potentially-matching rules
**Preconditions**: Two active rules could both plausibly match the
same product (e.g. one by product, one by category), pointing to
different stations.
**Steps**: Send an order with that product.
**Expected Result**: Exactly **one** KDS line is created for that
product, routed per the correct resolution order (RT-01 through
RT-04) — never two lines from two "matching" rules.
**PASS/FAIL**: ___
**Notes**: ___

---

## 4. Expeditor / Packing

### EXP-01 — Expeditor activates only when configured
**Preconditions**: Company has at least one station marked as
Expeditor.
**Steps**: Send an order and bring its only production line to Ready.
**Expected Result**: A Packing/Expeditor task is created and becomes
available; the order itself does **not** auto-complete at this point.
**PASS/FAIL**: ___
**Notes**: ___

### EXP-02 — Packing waits for ALL required production stations
**Preconditions**: A multi-station order (e.g. Kitchen + Coffee),
Expeditor enabled.
**Steps**: Bring only Kitchen's line to Ready; observe. Then bring
Coffee's line to Ready too.
**Expected Result**: No Packing task appears while Coffee is still
Preparing. Once **both** are Ready, exactly one Packing task becomes
available.
**PASS/FAIL**: ___
**Notes**: ___

### EXP-03 — Packing lifecycle: Waiting → Packing → Ready → Completed
**Preconditions**: A Packing task exists (Waiting).
**Steps**: Start it (→ Packing), mark it Ready, then Complete it.
**Expected Result**: Each transition succeeds; completing the
Expeditor task finalizes the **whole order** to Completed. Production
lines themselves remain at Ready — they are never force-rewritten to
Completed by the Expeditor's own completion.
**PASS/FAIL**: ___
**Notes**: ___

### EXP-04 — Reopening a production line cancels the active Packing task
**Preconditions**: A Packing task is Waiting or already started
(Packing).
**Steps**: Reopen the underlying production line back to Preparing
(e.g. a genuine correction).
**Expected Result**: The active Packing task is cancelled; the order
is pulled back out of Ready — it does not stay Ready while production
is active again.
**PASS/FAIL**: ___
**Notes**: ___

### EXP-05 — Cancellation during Packing cancels the task cleanly
**Preconditions**: A Packing task is actively in progress.
**Steps**: Cancel the entire POS order.
**Expected Result**: The order and the Packing task both become
Cancelled — no orphaned/active Packing task remains.
**PASS/FAIL**: ___
**Notes**: ___

### EXP-06 — POS delta during/after Packing availability cancels the stale task
**Preconditions**: A Packing task is Waiting (production already at
Ready).
**Steps**: A new production line arrives (e.g. a POS delta-sync adds a
product).
**Expected Result**: The old Packing task is cancelled — it must not
be finalized while new, un-prepared work has just arrived.
**PASS/FAIL**: ___
**Notes**: ___

### EXP-07 — Completion is rejected if production reopened just before finalizing
**Preconditions**: A Packing task reaches Ready.
**Steps**: Simulate a last-moment reopening of the underlying
production line (a race condition), then attempt to complete the
Packing task.
**Expected Result**: The completion is rejected with a clear error —
the server-side safety check catches the stale state even this late.
**PASS/FAIL**: ___
**Notes**: ___

### EXP-08 — Expeditor-disabled orders fall back to direct completion
**Preconditions**: No active Expeditor station for the company.
**Steps**: Bring a single-station order to Ready, then Complete it
directly.
**Expected Result**: No Packing task is ever created; a plain Complete
action finalizes the order normally.
**PASS/FAIL**: ___
**Notes**: ___

### EXP-09 — Expeditor permissions
**Preconditions**: An operator assigned to the Expeditor station; a
different operator not assigned there.
**Steps**: Each attempts to start/act on a Packing task.
**Expected Result**: The assigned operator succeeds; the unassigned
one is denied.
**PASS/FAIL**: ___
**Notes**: ___

---

## 5. Printing

### PRT-01 — Auto Print creates a job only where a printer exists
**Preconditions**: One station has a printer configured, another
routed station does not.
**Steps**: Send/complete an order touching both stations, triggering
auto-print.
**Expected Result**: Exactly one print job is created for the station
WITH a printer; the station without one gets **no job at all** (never
a broken job with no printer assigned).
**PASS/FAIL**: ___
**Notes**: ___

### PRT-02 — Manual print (full order)
**Preconditions**: An order with lines at a station with a configured
printer.
**Steps**: Trigger a manual "Print Full Order" action.
**Expected Result**: A print job is created and queued correctly for
that station/printer.
**PASS/FAIL**: ___
**Notes**: ___

### PRT-03 — Reprint requires a reason and numbers sequentially
**Preconditions**: A station already has one printed job (print
number 1) for an order.
**Steps**: Trigger a reprint without a reason (expect rejection), then
trigger it again with a reason (e.g. "kitchen_request").
**Expected Result**: Without a reason: rejected. With a reason: a new
job is created with **print number 2**, `display_job_type = reprint`;
the original job's own print number 1 is unaffected.
**PASS/FAIL**: ___
**Notes**: ___

### PRT-04 — Print numbering is independent per order and per station
**Preconditions**: Two different orders (or the same order at two
different stations).
**Steps**: Print/auto-print each independently.
**Expected Result**: Each (order, station) pair starts its own
sequence at 1 — never continuing another pair's own numbering.
**PASS/FAIL**: ___
**Notes**: ___

### PRT-05 — Retry does not increment print number
**Preconditions**: A pending/dispatched job that fails.
**Steps**: Mark it failed (simulating a printer error, below the
auto-retry threshold), observe the retry.
**Expected Result**: The **same** job record retries (retry_count
increments) — no new print number, no new job row, no reprint
counted.
**PASS/FAIL**: ___
**Notes**: ___

### PRT-06 — Fallback to backup printer after repeated failures
**Preconditions**: A station has both a primary and a backup printer
configured.
**Steps**: Cause a job to fail repeatedly (exceeding the auto-retry
threshold).
**Expected Result**: A **new**, separate print job is created on the
backup printer; the original job is marked failed/escalated. A
manager-alert-style audit event is logged.
**PASS/FAIL**: ___
**Notes**: ___

### PRT-07 — Escalation with no backup printer configured
**Preconditions**: A station has only one printer, no backup.
**Steps**: Cause repeated failures past the retry threshold.
**Expected Result**: The job is marked failed/escalated; a manager
alert is logged explicitly noting no backup printer was available —
no phantom job is created on a nonexistent backup.
**PASS/FAIL**: ___
**Notes**: ___

### PRT-08 — Atomic claim: two agents never claim the same job
**Preconditions**: One pending print job for a given printer.
**Steps**: Simulate two near-simultaneous claim requests from two
different agent identities for the same printer.
**Expected Result**: Only one of the two claims succeeds for that job
— never both.
**PASS/FAIL**: ___
**Notes**: ___

### PRT-09 — Expired lease becomes claimable again
**Preconditions**: A job was claimed (dispatched) by an agent, but its
lease has since expired (agent crashed/lost connection) without a
result being reported.
**Steps**: Have a (possibly different) agent attempt to claim jobs for
that same printer again.
**Expected Result**: The stale-leased job becomes claimable again and
is reassigned to whichever agent claims it now.
**PASS/FAIL**: ___
**Notes**: ___

### PRT-10 — Newest order sorts first in the Print Jobs list
**Preconditions**: Print jobs exist for at least two different orders,
one older, one newer.
**Steps**: Open the Print Jobs list (default view, no manual sort
applied).
**Expected Result**: The newer order's own jobs appear before the
older order's own jobs; within any one order, jobs read 1, 2, 3 top to
bottom.
**PASS/FAIL**: ___
**Notes**: ___

### PRT-11 — Printer Only station blocks Auto/Manual Print via Kiosk, allows it via backend
**Preconditions**: A station's Operating Mode is set to Printer Only.
**Steps**: Confirm printing still works from the normal backend
Printers screen/print actions for that station.
**Expected Result**: Printing itself remains fully functional for a
Printer Only station via the supported backend paths (Printer Only
specifically restricts **Kiosk** access — see SEC scenarios — not
printing capability itself).
**PASS/FAIL**: ___
**Notes**: ___

---

## 6. Security / Kiosk

### SEC-01 — Valid Kiosk token grants access
**Preconditions**: A station with a valid, active `kiosk_token`;
Operating Mode not Printer Only; `kiosk_disabled = False`.
**Steps**: Open the Public Kiosk URL for that station with the correct
token.
**Expected Result**: The Kiosk page loads and shows that station's own
orders.
**PASS/FAIL**: ___
**Notes**: ___

### SEC-02 — Invalid/wrong token is rejected
**Preconditions**: Same station as SEC-01.
**Steps**: Open the Kiosk URL with an incorrect or fabricated token.
**Expected Result**: Access is rejected — no station data is exposed.
**PASS/FAIL**: ___
**Notes**: ___

### SEC-03 — Disabled Kiosk rejects even a correct token
**Preconditions**: A station with `kiosk_disabled = True`.
**Steps**: Open the Kiosk URL with the station's own genuinely correct
token.
**Expected Result**: Access is still rejected — disabling overrides a
valid token without needing to regenerate it.
**PASS/FAIL**: ___
**Notes**: ___

### SEC-04 — Re-enabling Kiosk restores access with the same token
**Preconditions**: Continue from SEC-03.
**Steps**: Set `kiosk_disabled = False` again; retry the same
(unchanged) token.
**Expected Result**: Access is restored immediately — the token itself
was never invalidated.
**PASS/FAIL**: ___
**Notes**: ___

### SEC-05 — Printer Only station rejects Kiosk access, even with an old bookmarked URL
**Preconditions**: A station previously KDS-capable (with a
functioning, bookmarked Kiosk URL), now reconfigured to Printer Only.
**Steps**: Revisit the old, previously-working Kiosk URL.
**Expected Result**: Rejected at the backend — not merely a hidden UI
tab; the same URL that worked before now genuinely fails
authentication.
**PASS/FAIL**: ___
**Notes**: ___

### SEC-06 — KDS Only station allows Kiosk access (printing unavailable within it)
**Preconditions**: A station's Operating Mode is KDS Only.
**Steps**: Open its Kiosk URL with a valid token; attempt to trigger a
print action from within that Kiosk session.
**Expected Result**: The Kiosk session itself loads normally
(orders/actions work); print-specific actions from that session are
correctly unavailable/rejected — distinct from the full Printer Only
rejection in SEC-05.
**PASS/FAIL**: ___
**Notes**: ___

### SEC-07 — KDS + Printer station allows full Kiosk access including printing
**Preconditions**: A station's Operating Mode is "KDS + Printer".
**Steps**: Open its Kiosk URL; use both KDS actions and a print
action.
**Expected Result**: Both fully work.
**PASS/FAIL**: ___
**Notes**: ___

### SEC-08 — Switching modes restores/revokes access live, without token regeneration
**Preconditions**: A station currently KDS Only (Kiosk works).
**Steps**: Change to Printer Only (Kiosk should now fail), then back
to KDS Only (Kiosk should work again) — using the exact same token
throughout.
**Expected Result**: Access follows the station's own **current**
Operating Mode at request time; never a one-way, permanent lock — and
the token itself is never touched by this.
**PASS/FAIL**: ___
**Notes**: ___

### SEC-09 — Company/station isolation for backend Operator access
**Preconditions**: An Operator assigned to a station in Company B; an
order belongs to Company A.
**Steps**: Attempt to view/act on the Company A order as that
Operator.
**Expected Result**: Denied and not visible in search results — no
cross-company leakage, even by direct id.
**PASS/FAIL**: ___
**Notes**: ___

### SEC-10 — Operator station scoping
**Preconditions**: An Operator assigned only to Kitchen.
**Steps**: Attempt to act on a line routed to a different station
(e.g. Coffee).
**Expected Result**: Denied — station assignment is enforced
independently of having the general Operator role.
**PASS/FAIL**: ___
**Notes**: ___

### SEC-11 — Supervisor/Administrator permission tiers
**Preconditions**: A Supervisor and an Administrator user, each with
appropriate/no station assignment as applicable.
**Steps**: Attempt actions reserved for Supervisor+ (e.g. cancel,
reprint) as an Operator (should fail), then as a Supervisor (should
succeed); confirm an Administrator bypasses station assignment
entirely.
**Expected Result**: Permission tiers behave as designed — Operator
denied for Supervisor-only actions, Supervisor succeeds within their
own station, Administrator unrestricted.
**PASS/FAIL**: ___
**Notes**: ___

### SEC-12 — Public Kiosk cannot reach internal/administrative actions
**Preconditions**: A valid Kiosk session for an eligible station.
**Steps**: Confirm the Kiosk UI/API surface exposes only the intended
customer/kitchen-facing actions (accept/start/ready/complete/print as
applicable) — no access to Administrator-only actions (e.g. printer
key management, permission configuration).
**Expected Result**: No such actions are reachable from the Kiosk
surface.
**PASS/FAIL**: ___
**Notes**: ___

---

## 7. SLA

### SLA-01 — Normal status shortly after arrival
**Preconditions**: A station with `target_prep_time` configured (e.g.
10 minutes).
**Steps**: Check a line's SLA status shortly (e.g. 1 minute) after it
arrives at the station.
**Expected Result**: Status reads Normal.
**PASS/FAIL**: ___
**Notes**: ___

### SLA-02 — Warning threshold crossing
**Preconditions**: Same station/target as SLA-01.
**Steps**: Check status once elapsed time crosses the configured
Warning threshold percentage (e.g. ~80% of target).
**Expected Result**: Status reads Warning.
**PASS/FAIL**: ___
**Notes**: ___

### SLA-03 — Late threshold crossing, even if never started
**Preconditions**: A line still sitting in New (never Accepted or
Started).
**Steps**: Wait past the target time from arrival.
**Expected Result**: Status reads Late — the SLA clock starts at
arrival, not at active prep start; queue time counts.
**PASS/FAIL**: ___
**Notes**: ___

### SLA-04 — Ready freezes the timer at the correct value
**Preconditions**: A line finishes (reaches Ready) within its own
target time.
**Steps**: Leave it sitting in Ready for a while afterward; re-check
its status.
**Expected Result**: Status stays Normal — it does not keep climbing
toward Late just because it's still visually sitting in the Ready
column.
**PASS/FAIL**: ___
**Notes**: ___

### SLA-05 — A line that finished late stays Late permanently
**Preconditions**: A line took longer than target before reaching
Ready.
**Steps**: Re-check its status well after it reached Ready.
**Expected Result**: Status remains Late — it does not silently reset
to Normal once no longer actively timed.
**PASS/FAIL**: ___
**Notes**: ___

### SLA-06 — Order-level SLA reflects the worst line
**Preconditions**: A multi-line order where one line is Normal and
another is Late.
**Steps**: Check the order-level SLA status.
**Expected Result**: Reads Late — the order-level status always
reflects the worst-case line, never the first/average one.
**PASS/FAIL**: ___
**Notes**: ___

### SLA-07 — Completed/Cancelled orders are not recomputed as Late by the freshness cron
**Preconditions**: A Completed order whose stored SLA status is
already frozen (e.g. Normal, from before completion).
**Steps**: Wait, then let the periodic SLA-refresh cron run.
**Expected Result**: The stored status is left exactly as it was —
never recomputed as if the order were still open and ticking.
**PASS/FAIL**: ___
**Notes**: ___

---

## 8. Arabic / RTL

### AR-01 — Internal KDS screen displays Arabic when the user's language is Arabic
**Preconditions**: A logged-in Odoo user with Arabic set as their own
active language.
**Steps**: Open the Internal KDS screen.
**Expected Result**: Labels/text render in Arabic, using the logged-in
user's own Odoo language — never inferred from the browser alone.
**PASS/FAIL**: ___
**Notes**: ___

### AR-02 — Public Kiosk displays Arabic per the station's own language setting
**Preconditions**: A station's own kiosk language field set to
Arabic.
**Steps**: Open that station's Public Kiosk URL.
**Expected Result**: The Kiosk page renders in Arabic — labels,
status names, filter text.
**PASS/FAIL**: ___
**Notes**: ___

### AR-03 — RTL layout is functional, not just translated text
**Preconditions**: Same Arabic Kiosk/KDS session as AR-01/AR-02.
**Steps**: Visually inspect layout direction — card order, alignment,
navigation.
**Expected Result**: The layout genuinely flows right-to-left (`dir`
attribute correctly applied), not merely Arabic words inside an
LTR-arranged layout.
**PASS/FAIL**: ___
**Notes**: ___

### AR-04 — Order numbers and quantities render as stable, correctly-directioned numerals
**Preconditions**: An Arabic-language KDS/Kiosk session with an order
containing a multi-digit order number and quantity.
**Steps**: Inspect how the order number and quantities are displayed
within Arabic RTL text.
**Expected Result**: Numbers remain visually stable and correctly
ordered (bidi isolation) — never visually scrambled by surrounding
RTL text.
**PASS/FAIL**: ___
**Notes**: ___

### AR-05 — Backend (Odoo admin screens) Arabic translation coverage
**Preconditions**: An Administrator user with Arabic as their active
language.
**Steps**: Browse the module's own backend screens (Stations,
Printers, Routing Rules, Print Jobs).
**Expected Result**: Field labels and standard UI text appear in
Arabic; no obviously untranslated English fragments in core screens.
**PASS/FAIL**: ___
**Notes**: ___

### AR-06 — Printed tickets render Arabic product names/notes correctly
**Preconditions**: A product with an Arabic name and/or an Arabic
customer note on an order line.
**Steps**: Trigger a print (auto or manual) for that line's station.
**Expected Result**: The printed ticket payload/preview correctly
displays the Arabic text without corruption or reversed character
order.
**PASS/FAIL**: ___
**Notes**: ___

### AR-07 — Arabic font rendering has no disconnected/broken characters
**Preconditions**: Arabic Kiosk session, a variety of Arabic text
(labels, product names).
**Steps**: Visually inspect character connectivity across the Kiosk's
own font stack.
**Expected Result**: Arabic letters render properly connected (no
character-disconnection artifacts) on the devices/browsers targeted
for kiosk deployment.
**PASS/FAIL**: ___
**Notes**: ___

### AR-08 — Arabic label parity with English (no missing/placeholder text)
**Preconditions**: Switch between English and Arabic on the same
Kiosk/KDS screen.
**Steps**: Compare the same set of labels (status names, filter
names, action buttons) across both languages.
**Expected Result**: Every label that exists in English has a genuine
Arabic counterpart — no blank space, no raw translation key, no
leftover English fallback text on a screen otherwise in Arabic.
**PASS/FAIL**: ___
**Notes**: ___

---

## 9. Outstanding Items — Do Not Fix Now

The following items are recorded here for the **Arabic Finalization
pass before commercial sale** — they are explicitly **not** to be
addressed as part of any test-suite cleanup or the current release
cycle.

### 9.1 — Six Python audit/log messages currently without Arabic translation

The following six user-facing strings (all `note`/`reason` text on
audit events and cancellation reasons, in `models/pos_order.py`) were
found, during recent reconciliation-logic work, to have no
corresponding entry in the Arabic translation file (`i18n/ar.po`) at
the time of this document. They are functionally correct and safe —
this is a translation-completeness gap only, not a behavioral defect:

1. `"Quantity reduced in POS, cascading into this historical portion after the more recent line was fully absorbed"`
2. `"%(product)s reduced to zero in POS (quantity: %(qty)s -> 0, cancelled_qty: %(qty)s)"`
3. `"%(product)s (qty %(old_qty)s, previously %(state)s) fully cancelled - POS quantity decrease cascaded into and absorbed this entire portion"`
4. `"%(product)s reduced after original line was already %(state)s (qty %(old_qty)s -> %(new_qty)s) - decrease cascaded into this portion, no production reopened"`
5. `"%(product)s (qty %(old_qty)s) fully cancelled - POS quantity decrease exceeded this line's own full share, cascading into earlier production history"`
6. `"Quantity reduced in POS below this line's own share"`

**Action required at Arabic Finalization time**: add these six msgids
to `i18n/ar.po` with accurate Arabic translations, then re-verify
`i18n/ar.po`'s own structural validity and msgid coverage against the
current Python source (this was previously covered by two automated
tests — `test_localization_ar_po_is_structurally_valid` and
`test_localization_every_current_python_msgid_has_a_translation` — in
the archived automated suite; re-run that check manually or
re-introduce it in whatever verification method is active at that
time).

### 9.2 — Manual Print success audit per station

Add as a manual QA scenario to verify (not yet formalized above as a
numbered scenario — tracked here for inclusion at the next revision of
this document): after a successful manual print action at a given
station, confirm a corresponding audit event is recorded and
attributable to that specific station, distinguishable from other
stations' own print activity on the same order. Do not modify
Production based on the current automated test's own coverage of this
alone — verify manually first.
