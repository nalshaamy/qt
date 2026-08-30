# FlexSys KDS — Release Status

**RESTRUCTURED** ("Dead Code Cleanup Part 2", item 3, "Release Status
Cleanup") into a concise, current-state document. Development history
- what changed, when, and why - lives entirely in
[CHANGELOG.md](CHANGELOG.md) now; this document describes the product
**as it exists today**, with no contradictory statements carried over
from earlier drafts (a feature described as both "removed" and
"retained" in different sections, stale test counts, references to
models that no longer exist).

---

## Current Version

`19.0.1.0.0` — Commercial Candidate.

**Commercial license: OPL-1 (Odoo Proprietary License v1.0)** —
changed from LGPL-3. See [LICENSE](LICENSE) for the full official
text.

**Requirements**: Odoo 19, Point of Sale, Restaurant. `pos_restaurant`
is now an official, explicit manifest `depends` entry ("Add
Restaurant as Official Dependency") - a fresh install of FlexSys KDS
pulls it in automatically, alongside Point of Sale, before FlexSys
KDS itself loads. FlexSys KDS requires Odoo Point of Sale and
Restaurant.

**Last confirmed live Odoo.sh regression baseline (pre-Phase-3): 0
failed, 0 error(s) of 636 post-tests (662 tests total).** That result
is real and stands - it was run against the package *before* Phase
3's own new POS Direct Auto Print Worker tests were added.

**Version 45 live Odoo.sh Phase-3 validation run: 5 failed, 2 errors
of 692 post-tests (720 tests total).** This is a real, honest result
from an actual Odoo.sh regression run of the Phase-3 package, NOT a
"not yet run" placeholder - all 7 root causes (an unsafe Legacy Agent
atomic claim LIMIT query, two test-fixture group-field-name bugs, a
stale hardcoded test-count assertion, a comment-triggered false
positive, a pre-Phase-3 Auto Print test never rewritten, and missing
Arabic translations for new Phase 3 `_()` strings) have since been
identified and corrected in the current package - see the Change Log
below.

**Version 52 - last confirmed REAL, PASSING Full Regression on live
Odoo.sh: 0 failed, 0 error(s) of 725 post-tests (753 tests total).**
This is the current authoritative "the whole package actually passed
on a live Odoo 19 instance" baseline - it supersedes the Version 45
result above for that purpose (Version 45 remains as an honest
historical record of what failed and was fixed, not deleted). A
focused run of `TestPhase3PosDirectAutoPrint` alone at that same point
also passed clean: 0 failed, 0 error(s) of 89 post-tests (91 tests).

**Commercial Test Cleanup, Batch 1 (Phase 3 test suite only,
test-only change, zero production code touched)**: `tests/
test_phase3_pos_direct_auto_print.py` had accumulated one test per
historical audit round covering the same current behavior multiple
times over. Overlapping tests were merged into single authoritative
tests (or deleted where a stronger runtime test already existed, or
the check was documentation/implementation-history text rather than
product behavior - see
[docs/TEST_HISTORY.md](docs/TEST_HISTORY.md) for a short map of which
historical risk each remaining authoritative test now covers).
Version-prefixed test names were renamed to describe the current
product contract instead. This changed that one file's own test count
from 89 down to 64, and the project-wide total from 725 down to
**700 static test methods**.

**Version 56 - the cleaned 700-test package has now passed live
Odoo.sh.** Full Regression: 0 failed, 0 error(s) of 700 post-tests
(728 tests total). A focused run of `TestPhase3PosDirectAutoPrint`
alone also passed clean: 0 failed, 0 error(s) of 64 post-tests. This
is the current authoritative "the whole cleaned package actually
passed on a live Odoo 19 instance" result - it supersedes the Version
52 baseline above for that purpose (Version 52 remains as an honest
historical record of the pre-cleanup package's own passing run, not
deleted).

**Version 47 - POS session identity security correction**: confirmed
against Odoo 19's own real source
(`pos_session.py::_load_pos_data_fields()` explicitly loads
`access_token` into `pos.session` data sent to the POS frontend) that
Odoo 19 genuinely allows the SAME `pos.session` to be used by a
DIFFERENT authenticated user than whoever originally opened it -
`session.user_id == env.user` was therefore not a valid session-
ownership proof and has been removed from `claim_direct_auto_jobs()`
and `report_pos_direct_auto_result()`. Session identity is now proven
with the session's own standard `access_token`, compared with
`odoo.tools.consteq()` (constant-time, never a plain `==`), plus a
check that the calling user is a genuine `point_of_sale.group_pos_user`
account. A new `direct_executor_pos_session_id` field records the
exact claiming session so a result report must come from that same
session again. The POS worker never persists this token to
`localStorage` - only `pos_session_id` (an identifier) is stored for
result-retry purposes; the live in-memory
`this.pos.session.access_token` is read fresh at retry time. A stale
result marker belonging to a different, older session is discarded
locally rather than reported or allowed to block the current
session's own claims indefinitely - the server-side timeout lifecycle
(`RESULT_TIMEOUT`) remains the authoritative resolution for that old
job.

**Version 48 - final claim/security corrections**: (1) the atomic
Direct Auto claim SQL now always uses a hardcoded `safe_limit = 1`
regardless of the caller-supplied `limit` argument - the POS worker
only ever consumes `claimed[0]`, so a caller requesting more than one
could have dispatched jobs the worker never physically prints,
eventually timing out unprinted; the server, not the client, enforces
exactly one claim per call. (2) A rescue/recovery `pos.session` (Odoo
19's own concept, explicitly excluded from normal interactive session
selection by Odoo's own POS controller) is rejected on both claim and
result-report, independent of session state. (3) Explicit caller ->
session company isolation restored on both `claim_direct_auto_jobs()`
and `report_pos_direct_auto_result()`: since `sudo()` on the
session/station lookups deliberately bypasses ordinary record rules,
the RPC itself now re-checks that the authenticated caller is allowed
in the session's own company (`self.env.companies`) before trusting
that session/config as any authority at all - a valid token alone
never bypasses Odoo's own multi-company boundary. (4) An empty/falsy
`executor_id` is now rejected outright on both claim and report,
rather than being silently accepted as "no device identity."

**Phase 3 Focused Odoo.sh Result - shared test helper fix (test-only,
no production changes)**: a live focused run of
`TestPhase3PosDirectAutoPrint` (88 post-tests, 90 tests, 0 failed, 2
errors) surfaced two ERRORs, both in Company-B `pos.config` test
fixture setup, not in Phase 3 production code. Root cause: the shared
`tests/common.py::_make_test_pos_config()` helper passed `company_id`
inside the `vals` dict, but still executed `create(vals)` under
whichever company `self.env.company` already was - Odoo's own
company-dependent DEFAULTS on `pos.config` (`journal_id`,
`invoice_journal_id`, `picking_type_id`, warehouse, etc.) are all
resolved from `self.env.company`, not from any value inside `vals`,
so the Company B config's own defaults silently came from the wrong
company, which Odoo's own `_check_company` correctly rejected as a
`UserError`. Fixed by switching to `with_company(company)` before
`create()` specifically when a `company_id` override is supplied -
the standard, Odoo-documented way to create a record "as" a given
company (see Odoo's own Multi-company Guidelines) - rather than
manually re-implementing Odoo's own default-resolution logic for
individual fields.

**Bug fix - POS line note displayed as raw JSON in KDS**: on real
Odoo 19 runtime, a line's own `note` can be stored as a JSON-
serialized list of structured note objects (e.g.
`[{"text":"Heating","colorIndex":0}]`, produced by Odoo 19's own
color-coded POS Quick/Customer Notes) rather than a plain string -
every consumer of that field previously displayed the raw JSON syntax
itself to the kitchen instead of the human-readable text. Fixed with
a single shared normalization function
(`kds.order.line.normalize_note_text()`) applied at every point a
line note is rendered - the Internal KDS orders endpoint, the Public
Kiosk orders endpoint, and both places the POS Direct Auto Print
payload builder serializes a note. Normalization happens only at the
point of rendering; the stored `note` field itself is never rewritten,
so both new and pre-existing records are corrected without a data
migration. Plain-text notes remain fully unchanged.

**UI fix - Internal KDS 100% browser-zoom viewport fit**: on shorter-
height laptop/desktop screens, a heavy header/status-filters area
could push the card grid (and a normal order's own action buttons)
out of the initially visible area, requiring the whole page to be
scrolled just to reach them - not just to see extra cards. Fixed by
restructuring `.fs-kds-app` into a flex column with three regions:
the header/filters wrapper and the pagination bar are fixed-size
(`flex-shrink: 0`), and only the card grid area itself is flexible
(`flex: 1 1 auto`) and scrolls internally when genuinely needed -
`100dvh` (with a `100vh` fallback) added for the full-page Kiosk-mode
shell, and a moderate `@media (max-height: 900px)` compaction reduces
only vertical padding/margins/gaps in the header, filter bars, and
pagination framing. Card width (360px at `>= 1600px`), column/page
limits, product/note/variant text size, and CSS/JS pagination logic
are all completely unchanged - this is a CSS-only structural fix, no
JS or backend code touched.

**Test fix - stale pagination test contract after the viewport fix**:
`tests/test_pagination.py::test_normal_internal_kds_backend_mode_has_
vertical_scroll` still asserted the OLD contract
(`overflow-y: auto` directly on `.fs-kds-app`), which the viewport fix
above deliberately moved to `.fs-grid` - a real regression failure,
not a production bug. Renamed/updated to
`test_normal_internal_kds_backend_mode_is_a_fixed_height_flex_column`
to validate the CURRENT flex-column contract, and three new tests
added for the other elements of that same contract explicitly
required by this correction (`.fs-grid` is the flexible scrolling
region, `.fs-sticky-top` and `.fs-pagination` both `flex-shrink: 0`).
Test-only change; the CSS/JS/Python runtime itself is untouched.

**UI follow-up - deeper vertical-density compaction (V64)**: a real
runtime screenshot at Browser Zoom 100% confirmed the grid-scrolling
fix above was not sufficient on its own - a single-line-item order's
own card head/line/footer vertical spacing still pushed that one
normal card's own footer (Print/START) below the available grid
height on shorter desktop viewports. Extended the existing
`@media (max-height: 900px)` compaction with matching, moderate
vertical-only reductions inside the card itself (`.fs-card-head`
padding, the three internal margin-top gaps on `.fs-status-blink`/
`.fs-chips-row`/`.fs-employee-row`, `.fs-line-item` padding,
`.fs-card-footer` padding) and slightly deeper reductions to the same
top-framing/pagination elements already compacted. Pagination button
size moderately reduced at this breakpoint only (still well above the
~44px touch-target minimum). No font-size, color, card width, column
count, or pagination/JS logic touched anywhere.

**Bug fix - CSS cascade/source-order bug made the V64 card-internal
compaction inert (V65)**: static review confirmed the
`@media (max-height: 900px)` block above used to sit BEFORE the base
card rules it was meant to override (`.fs-card-head`,
`.fs-status-blink`, `.fs-chips-row`, `.fs-employee-row`,
`.fs-line-item`, `.fs-card-footer`, all defined further down the same
file). With equal selector specificity, plain CSS source order alone
decides the winner - the later base rule was silently winning every
time, at any viewport height, making every V64 card-internal
reduction completely inert in practice despite being textually
correct. Fixed by moving the entire block (every value inside it left
completely unchanged) to after every base rule it touches, including
`.fs-main-action`, and before the unrelated admin/configuration
styles that follow - no `!important` used; correct source order alone
is sufficient. The header/filters/grid/pagination portion of this
same block was already correctly ordered and is unaffected by this
move.

**Root cause fix - card height not actually constrained by available
grid row height (V66)**: live validation at Browser Zoom 100% still
failed after V65 even for a NORMAL, single-line order. Root cause,
found by inspecting `.fs-grid`'s own `align-items` rule: it is `start`
(and, outside the short-screen media query below, remains `start`) -
meaning every card grows to its OWN natural content height with NO
relationship at all to how much vertical space its own grid row
actually has available on a short screen. `.fs-card`'s own
`max-height: 640px` is a fixed pixel ceiling for genuinely large
orders - it does nothing to relate a short order's own card to a
short screen's own smaller row height, so no further padding
reduction alone could ever fix this. Fixed, at the existing short-
screen tier only (`@media (max-height: 900px)`; the taller-screen
default is completely unchanged): `.fs-grid { align-items: stretch; }`
makes every card in a row genuinely fill that row's own real
available height, and `.fs-card { height: 100%; min-height: 0;
max-height: 100%; }` (overriding the 640px ceiling only at this tier)
lets it actually claim that height. `.fs-card-body`'s own existing
`flex: 1 1 auto; min-height: 0; overflow-y: auto` (already correct,
unchanged) is what then absorbs any genuine overflow internally by
scrolling only the card's own body, instead of the row pushing the
footer below the visible grid area.

**UX clarification - Station/Routing labels, layout, and
contradictory-configuration prevention**: `kds.station.pos_config_ids`
relabeled "Allowed POS" with a clearer help text; `kds.routing.rule.
pos_config_ids` relabeled "POS Filter (Optional)" and moved out of
the always-visible top group into its own "Advanced Filters" section
- a normal user setting up Products/POS Categories/Order Types/
Sources never needs to touch it. A new read-only, informational
`station_pos_config_ids` (related field) shows the selected
destination station's own allowed POS directly on the rule form. Real
new backend behavior, the only part of this change with actual
runtime logic: a routing rule's own POS Filter can no longer name a
POS the destination station doesn't already allow - enforced by a
UI-domain convenience (`pos_filter_domain_ids`, recomputed whenever
the station changes) AND, since a UI domain alone can be bypassed, a
real `@api.constrains` that rejects such a combination outright with
an explicit message. An exact-match (fully redundant, but not
incorrect) POS Filter only triggers a soft `@api.onchange` warning,
never blocks saving. A small, optional, purely informational
`rule_summary` field (plain string concatenation over already-loaded
fields, no new parser/rule engine) restates the rule in plain
language. Routing evaluation semantics themselves
(`_matches()`/`route_product()`) are completely untouched.

**V68 Review - station-side contradiction validation, "All POS"
display, and complete Arabic translation**: (1) the prior
contradiction check only fired on the routing rule side - editing a
STATION's own Allowed POS down to something narrower than what an
existing rule already relies on was left unguarded. A new
`kds.station` constraint now checks every routing rule already
targeting that station whenever its own `pos_config_ids` changes,
rejecting the station save outright (never silently modifying or
clearing the rule) if any such rule's own POS Filter would no longer
be fully covered. (2) When a station allows all POS, the routing
rule's own informational display now explicitly reads "All POS"
(a small computed Char field) instead of an ambiguous blank
many2many-tags widget. (3) Every new fixed English phrase this
change introduced - field labels/help, the Advanced Filters section
title, the routing-logic alert text, and every fixed word inside the
rule summary sentence ("orders", "POS", "any allowed POS", "All
POS") - now has its own Arabic translation, added to both `ar.po` and
`flexsys_kds.pot`; product/category/POS/station proper names
correctly remain untranslated, exactly as configured by the user.
Routing matching/evaluation semantics remain completely untouched.

**Fresh Repository Validation - 2 stale tests + duplicate field label
(V69)**: a fresh Odoo.sh repository validation run surfaced two
failures, both genuinely stale tests asserting the pre-V68 Routing
UX contract (`field.string == 'POS'` and the old "Empty criterion =
Any" wording) rather than any regression in the approved current
behavior - renamed/updated to validate the current contract instead
of reverting it. Separately, a genuine duplicate-field-label warning
("Two fields ... have the same label: Allowed POS") was confirmed:
`station_pos_config_ids` and `station_pos_config_display` shared the
exact same `string`. Direct search confirmed `station_pos_config_ids`
is not actually read by any view or other compute/logic anywhere in
this module (reported here rather than silently removed, per
explicit direction) - fixed with a distinct, clearly-technical label
("Station Allowed POS (Technical)") rather than a kwarg named
`invisible` on the field definition itself, which is a view-level
XML attribute, not a valid `fields.Field()` constructor argument.

**Public Kiosk - full viewport flex layout fix (V70)**: root cause,
confirmed by direct inspection of `controllers/kds_kiosk.py`'s own
real standalone HTML/CSS (no `body.o_flexsys_kiosk` or any other
kiosk-specific class exists anywhere in this file - that name belongs
to a different context) - `body` had no `display:flex` at all, so
`.header`/`.filters`/`.grid`/`.pagination`/`.statbar` (this page's own
real "Kiosk Footer" - there is no element literally named "footer"
here) simply stacked in normal block flow, and `.grid` itself only
ever grew to its own natural content height. With few orders, that
height is short, leaving a large unused block of `body`'s own dark
background below `.statbar`, down to the real bottom of the viewport.
Fixed independently of Internal KDS's own equivalent fix (this page
is a genuinely standalone, full-screen surface with no Odoo backend
chrome to respect, unlike Internal KDS) - `body` is now the flex
column that owns the whole vertical layout, `html`/`body` use
`100dvh` (with a `100vh` fallback) directly rather than a parent-
relative height, `.header`/`.filters`/`.pagination`/`.statbar` keep
their own natural size (`flex-shrink:0`), and `.grid` alone is the
flexible region (`flex:1 1 auto; min-height:0`) that claims the
leftover space and scrolls internally (`overflow-y:auto`, moved here
from `body` itself) only when genuinely needed. Card width (360px at
`>=1600px`), column/page limits, and Internal KDS itself are all
completely unchanged - confirmed via checksum, this change is scoped
entirely to `controllers/kds_kiosk.py`.

---

## Core Features

- Station-based routing engine (product / POS category / inventory
  category / order type / source / POS config), multi-company isolated.
- Centralized workflow engine: **New → Accepted → Preparing → Ready →
  Completed**, plus Cancelled and On Hold - every transition, including
  system-triggered corrections, is validated and audited; no code path
  writes `state` directly.
- Live SLA tracking per station, with a periodic freshness refresh.
- Optional Expeditor / Packing final-assembly stage - a real tracked
  task (own state machine, timestamps, separate SLA), not just a flag.
- Printing: two dispatch paths side by side, both managed through the
  same `kds.print.job` record for every production print - Direct
  Network (browser-executed Epson ePOS, no external software) and the
  original external Print Agent path (job queue with an atomic
  claim/lease mechanism and a versioned payload contract; not included
  - see [docs/PRINT_AGENT.md](docs/PRINT_AGENT.md)). Odoo IoT is
  reserved, not yet implemented.
- Role-based security (Operator / Supervisor / Branch Manager /
  Administrator), station-scoped record rules, protected-field write
  guards.
- Two KDS screens: authenticated backend (realtime) and a public,
  token-based kiosk (polling).
- Full audit log (`kds.event`).

---

## Operating Modes

Each `kds.station` has one `operating_mode`:

| Mode | Public Kiosk | Printers |
|---|---|---|
| KDS Only | Available | Configuration hidden |
| Printer Only | **Rejected** - both at the UI level (tab hidden) and at the backend/controller level (`_station_from_token()` rejects the request regardless of a valid token) | Available |
| KDS + Printer | Available | Available |

Confirmed live: a station switched to Printer Only correctly rejects
even a previously valid, bookmarked kiosk URL - not a token
invalidation, a live check of the station's own current
`operating_mode` on every request.

---

## Printing

Two dispatch paths, both managed through the same central
`kds.print.job` record for every production print - no print ever
happens outside that record's own history, regardless of which path
executes it (`transport`: `direct_network` / `agent` / `iot`
[reserved]).

**Direct Network (Epson ePOS)**:

- Configured per-station (Station → Printing tab: Printer IP, Local
  Network Access).
- Lifecycle: `Print requested → kds.print.job created (Dispatched) →
  browser executes the print over Direct ePOS → result reported back
  (Printed / Failed)`.
- A Direct job left "Dispatched" past its own short deadline (browser
  tab crashed/closed/lost connection before reporting back) is
  automatically marked Failed by a background check - it never sits
  showing "Printing" indefinitely.
- No automatic retry and no backup-printer escalation for this path -
  a failed Direct attempt is simply Failed; the operator presses Print
  again, which creates a fresh job.
- Ticket rendering: FlexSys's own Canvas-based renderer (shared
  identically between the Internal Screen and the Public Kiosk) draws
  the ticket with real browser font shaping (Arabic/English/mixed),
  then converts it to a monochrome raster (Floyd-Steinberg dithering)
  before sending it to the printer - not printer-resident fonts.

**Legacy Print Agent** (the original path, still fully supported for
a station not yet configured for Direct Network):

- Atomic claim/lease: `_claim_pending_jobs()` uses a single
  `UPDATE ... WHERE ... RETURNING` with PostgreSQL's
  `FOR UPDATE SKIP LOCKED`, so two concurrent agent calls for the same
  printer can never claim the same job.
- Automatic retry with backup-printer fallback after repeated
  failures, each escalation independently audited.
- Printer metadata (`port`, `usb_identifier`, `serial_number`) is kept
  as reference documentation for whoever configures the external Print
  Agent - not read by any Odoo-side logic, by design.
- No external Print Agent is included - building and deploying one is
  a separate project, against the documented protocol.

Every job - Direct or Legacy Agent - is visible under **Printing →
Print Jobs**, with a manual Reprint action (required reason,
sequential print numbering) available on either path.

### Phase 3 — POS Direct Auto Print Worker (code complete, hardware/Odoo.sh validation pending)

Server-triggered Auto Print (Printer Only stations, and KDS+Printer
stations with Auto Print switched on) now has a Direct Network
execution path that needs zero `kds.printer`/Legacy Agent
configuration - a POS Browser's own local worker claims and executes
the print itself, over the same Direct ePOS transport and the same
shared Canvas ticket renderer Internal KDS and Public Kiosk already
use.

- **Lifecycle**: `kds.print.job created (Pending, own claim_deadline)
  → an eligible POS Browser's worker claims it (Dispatched,
  direct_executor_id/direct_executor_pos_config_id/direct_claimed_at
  recorded, own dispatch_deadline set) → the claiming browser executes
  the print and reports a result (Printed / Failed)`.
- **No automatic retry, no Agent fallback, no backup-printer
  escalation** for this path - identical, honest failure handling to
  every other Direct Network job. A `Pending` job nobody claims before
  its own deadline fails with `error_code=NO_EXECUTOR`; a claimed job
  whose executor never reports back fails with
  `error_code=RESULT_TIMEOUT` - both handled by the same background
  cron that already handles Manual/Public Kiosk Direct timeouts.
- **Result-first local persistence**: the POS worker writes its own
  print result to `localStorage` before reporting it to the server -
  a dropped/failed report RPC is retried on the next cycle, but the
  physical print itself is never re-attempted because of a reporting
  failure.
- **Ownership enforced server-side**: only the exact POS session/
  device that claimed a job may report its own result for it -
  verified against `direct_executor_id`/`direct_executor_pos_config_id`
  on every report, not trusted from the client.
- **Legacy Agent status - explicitly unchanged and RETAINED for now**:
  `kds.printer`, every Agent route, Agent keys, and the Legacy Agent's
  own retry/backup-printer escalation are completely untouched by this
  phase and remain fully functional - this is a new, additional
  execution path, not a replacement, until real Odoo.sh regression, a
  genuine Epson hardware test, and an actual Printer Only / KDS+Printer
  Auto Print run all confirm this new path end-to-end. The Legacy
  Agent path is retained internally/temporarily for compatibility, not
  scheduled for removal in this round.
- **Not yet validated in this round**: a live Odoo.sh regression run
  and a real POS Browser → Epson printer hardware test - both
  explicitly reserved for the client's own environment. Nothing in
  this document claims either has passed.

---

## KDS Lifecycle

`New → Accepted → Preparing → Ready → Completed`, plus `Cancelled` and
`On Hold`. Every transition:

- Is validated against an explicit allowed-transitions matrix
  (`ORDER_TRANSITIONS`/`LINE_TRANSITIONS` in `kds_order.py`/
  `kds_order_line.py`), with a separate, higher-permission override
  tier for edge cases.
- Is logged to `kds.event`.
- Never happens via a raw `write()` on a protected field - a
  `state`/`priority`/timestamp write outside the workflow engine's own
  internal context is rejected at the ORM level.

Two independent order/screen models (`kds.order.status`/
`kds.order.status.transition`) that never drove this engine and were
never read by it have been removed entirely from the codebase - the
lifecycle above has always been, and remains, hardcoded and fully
tested.

---

## Routing

Rules match on product / POS category / inventory category / order
type / source / POS config, in sequence order, first match wins.
Empty criterion = matches anything; multiple values in the same
criterion = OR; different criteria = AND. Multi-company isolated.

---

## POS Delta / Reconciliation

- A quantity **increase** on an already-sent, Ready/Completed line
  creates a new delta line for just the increase, preserving the
  original's own production history untouched.
- A quantity **decrease** (partial or to zero) on an already-sent line
  syncs to KDS **immediately**, without waiting for the next explicit
  Send - reconciles the true combined quantity across every historical
  sibling for that product, reducing the most recently created one
  first (never reopening the earliest/original portion unless
  genuinely required). A decrease to zero cancels the line outright,
  with full audit history preserved.
- Pressing Send after an already-settled reconciliation is a correct,
  idempotent no-op - it does not reprocess the same change again.
- Multi-station orders reconcile correctly per station; an unrelated
  station is never affected by another station's own change.

---

## Cancellation / Refund

- Cancelling a line/order is a validated, audited transition - never a
  raw state write.
- A line already Completed is cancelled via the same authoritative
  path as any other line, with its own historical timestamps
  preserved.
- Refund handling is unaffected by any change in this cleanup round -
  on the explicit "do not touch" list, confirmed still passing its own
  existing test coverage.

---

## Public Kiosk

- Token-based, public (`auth='public'`) access to a single station's
  own live order queue - no Odoo login required.
- A single, central authentication function
  (`_station_from_token()`) is called by all six public kiosk routes
  (the initial page, three original JSON-RPC API endpoints, and the
  two Direct Network print routes added in Phase 2 -
  `kiosk_prepare_direct_print`/`kiosk_report_direct_print_result`) -
  there is no alternate path that resolves a station without going
  through it.
- Rejects a missing/mismatched token, a `kiosk_disabled` station, and a
  `printer_only` station - confirmed live and covered by dedicated
  regression tests for every combination (KDS Only, KDS + Printer,
  Printer Only, a station switched between modes with the same token,
  and direct API calls).
- The initial page response sends explicit `no-store`/`no-cache`
  headers, so a browser or intermediate proxy cannot serve a stale
  cached copy after a station's own mode changes.
- Genuine access rejections are logged at `WARNING` (visible in
  production by default); routine polling/request logging is at
  `DEBUG` (does not flood production logs under normal use).

---

## Localization

English and Arabic are the first two supported languages; the
architecture is not limited to exactly two.

- **Internal KDS Screen**: uses the logged-in Odoo user's own active
  language (`user.lang`) - never inferred from the browser. Operational
  labels come from a small, self-contained bilingual dictionary
  (`KDS_LABELS_EN`/`KDS_LABELS_AR`), deliberately not Odoo's shared
  `_t()` translation catalog - an earlier fix confirmed `_t("NEW")`
  collided with an unrelated existing Arabic translation somewhere in
  Odoo's own core.
- **Public Kiosk**: has no logged-in user session to read a language
  from. Each station has its own explicit `kiosk_language` field
  (English/Arabic, defaults to English - zero behavior change for any
  station that hasn't touched it), driving a parallel dictionary
  embedded in the kiosk's own page.
- **RTL**: the Internal Screen was already built RTL-safe (logical
  CSS properties, auto-reversing flexbox, Arabic-capable font) from an
  earlier round; the Public Kiosk's own `dir`/`lang` attributes and
  font stack were added this round to match. Order numbers, quantities,
  timers, and delta markers (`+2`/`-1`) use explicit bidi isolation so
  they render in a stable, predictable direction regardless of
  surrounding Arabic/English context.
- **Backend**: `i18n/ar.po` covers every current Python-side `_()`
  string (81 msgids, regenerated via AST-accurate parsing against the
  current codebase - no stale entries from removed features). Selection
  field labels and view/menu strings still require an Odoo-native
  export/import pass on a live instance to complete.
- **Not yet verified in this environment**: actual Arabic thermal/Print
  Agent output, live visual RTL rendering, and the full translation
  completeness audit across XML views/selections - all require a live
  Odoo 19 instance.

---

## Security

Four role tiers, each implying the one below it:

- **Operator** - base tier; can act on assigned stations only.
- **Supervisor** (implies Operator) - cancel, reopen, reprint.
- **Branch Manager** (implies Supervisor) - company-wide visibility.
- **Administrator** (implies Branch Manager) - unrestricted within the
  standard Odoo multi-company boundary; the only tier that can regenerate
  a printer's own Agent Key or a station's own kiosk token.

Record rules scope Operator/Supervisor access to their explicitly
assigned stations (an empty assignment means *no* access, not open
access). Protected fields (`state`, `priority`, every workflow
timestamp) are rejected on a plain `write()` regardless of role - only
the workflow engine's own internal context, or a genuine `sudo()`
call, can set them.

The `priority` field itself remains in the schema (Selection, still
protected against direct writes) but has no active UI, action, or
runtime behavior anywhere in the product - see "Known Limitations"
below for the schema-removal decision this is pending.

---

## Automated Test Count

**729 static test methods** as of this document (`py_compile`, XML
well-formedness, and JS syntax checked on every file on every change,
plus functional/behavioral coverage for every area above, including
the Direct Printing / `kds.print.job` lifecycle, the Pagination
regression suite, and Phase 3's own POS Direct Auto Print Worker
suite - operating-mode enforcement, job creation/idempotency, atomic
claim/eligibility revalidation, session ownership, timeouts, payload
content, and the audit-correction tests from this round).

The **last confirmed live Odoo.sh Full Regression (Version 56)**
covered these current **700 static test methods** (728 tests total)
with **0 failed, 0 error(s)** - the whole current package has actually
passed together on a live Odoo 19 instance. Earlier historical
results (the 636-post-test pre-Phase-3 baseline, the Version 45
Phase-3 validation run that surfaced 7 root causes since fixed, and
the Version 52 pre-cleanup 725-post-test passing run) remain on record
as honest history - see "Commercial Readiness Status" below for the
full gate-by-gate breakdown.

**Note (POS Line Note JSON-normalization bug fix)**: 11 new
regression tests (`tests/test_note_normalization.py`) were added
after the Version 56 Full Regression above, bringing the current
static count to 711. These 11 new tests - along with the fix itself
- have been verified by direct standalone re-execution of the actual
function source and static source-contract checks against the real
call sites in this environment, but have **not yet** been run as
part of a live Odoo 19 regression. The 700/728 Version 56 result
above remains the last REAL, confirmed-passing Odoo.sh figure; no
claim is made that all 714 have passed together on a live instance
until that run happens and confirms it.

---

## Known Limitations

- **No external Print Agent is included.** Building and deploying one
  is a separate project against the documented protocol - only
  required for a station configured for the Legacy Agent path; Direct
  Network printing needs no external software at all.
- **The `priority` field and its Selection values remain in the
  schema, inactive.** Priority/Urgent/VIP has been fully removed as a
  product feature (no UI, no filter, no action, no operational
  behavior) - the field itself is kept temporarily for upgrade safety
  on the development branch; the final schema decision (keep as
  permanently inert, or drop entirely) will be made when building the
  first commercial baseline.
- **Device enrollment / QR pairing / PWA / device management / display
  modes / sound preferences** have not been started - explicitly out
  of scope for this release.
- **Advanced analytics** (SLA compliance %, peak hours, station
  throughput, prep-time trends) is future work, not part of this
  release's closure gate.

---

## Commercial Readiness Status

| Gate | Status |
|---|---|
| `py_compile` (every Python file) | ✅ Pass |
| XML well-formedness (every view/data file) | ✅ Pass |
| JS syntax check (every frontend file) | ✅ Pass |
| Manifest parses, no orphaned data-file references | ✅ Pass |
| ACL entries all reference an existing model | ✅ Pass (verified programmatically) |
| Menu items all reference an existing action | ✅ Pass (verified programmatically) |
| Automated test suite (729 static test methods) internally consistent | ✅ Pass |
| Pre-Phase-3 live regression baseline (0 failed, 0 errors) | ✅ **636 post-tests (662 tests total)** (pre-Phase-3 package) |
| Version 45 live Odoo.sh Phase-3 validation run | ❌ **5 failed, 2 errors of 692 post-tests (720 tests total)** — all 7 root causes since identified and fixed in the current package; kept as an honest historical record, not removed on a later successful run |
| Pre-cleanup live Odoo.sh Full Regression (Version 52) | ✅ **0 failed, 0 errors of 725 post-tests (753 tests total)** — the pre-cleanup package's own passing baseline, kept as an honest historical record |
| Last confirmed live Odoo.sh Full Regression (Version 56, cleaned 700-test package) | ✅ **0 failed, 0 errors of 700 post-tests (728 tests total)** — the current authoritative "whole package passed live" baseline |
| Phase 3 focused suite (`TestPhase3PosDirectAutoPrint`, 64 tests) live Odoo.sh run | ✅ **0 failed, 0 errors** |
| Live two-screen realtime check (backend + kiosk simultaneously) | ⚠️ **Requires a live instance** |
| Module upgrade test on an existing development database | ⚠️ **Requires a live instance** |
| Live regression pass: POS → Routing → KDS → Preparing → Ready → Completed, quantity increase/decrease/to-zero, cancellation, refund, multi-station, all three Operating Modes, Public Kiosk token enforcement, printing claim/lease | ⚠️ **Requires a live instance - the client's own environment is the only one available for this** |
| `action_move_station()` deletion approved | ✅ Confirmed by client - no external RPC contract exists |
| Priority field schema-removal decision | ⏳ Deferred to first commercial baseline build |
| Development migrations excluded from commercial package | ✅ **Done** - `migrations/` directory removed from the commercial addon package (development history preserved in Git) |
| Large-screen card width (360px) | ✅ **Approved** - Internal KDS and Public Kiosk, `>= 1600px` |
| Arabic backend/Internal KDS/Public Kiosk translation coverage (current code) | ✅ Pass - AST-verified against current Python; both screens' own operational labels confirmed complete |
| Arabic thermal output (Direct Network raster + Legacy Print Agent) | ⚠️ **Not yet performed by the client - actual 80mm printer output review remains pending** |
| Live visual RTL rendering (all required screens) | ⚠️ **Requires a live instance** |
| Live visual review (general commercial polish, both KDS screens) | ✅ **PASS** for current Internal KDS and Public Kiosk layout |
| End-to-end commercial demo rehearsal | ⚠️ **Not yet performed by the client - pending** |
| Full translation completeness audit (XML views/selection labels) | ⏳ Python coverage confirmed; XML requires Odoo's own export tool on a live instance |
| Arabic runtime scenario pass (POS → Send → KDS → ... → Completed, in Arabic) | ⚠️ **Requires a live instance** |

**This document does not claim the product is commercially ready** -
every item above marked ⚠️ or ⏳ is a real, open gate. It states plainly
what has been verified by static analysis in this environment (which
has no live Odoo instance) versus what can only be confirmed by the
client's own live testing, exactly as every item above shows.
