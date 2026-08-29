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

`19.0.1.0.0` — the first Commercial Demo Candidate baseline.

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
below. This corrected package (724 static test methods as of this
document) has **not yet** been re-run against a live Odoo 19 instance
- see "Commercial Readiness Status" below for the exact, current gate
status; no PASS is claimed for this package until that re-run happens
and actually confirms it.

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

**724 static test methods** as of this document (`py_compile`, XML
well-formedness, and JS syntax checked on every file on every change,
plus functional/behavioral coverage for every area above, including
the Direct Printing / `kds.print.job` lifecycle, the Pagination
regression suite, and Phase 3's own POS Direct Auto Print Worker
suite - operating-mode enforcement, job creation/idempotency, atomic
claim/eligibility revalidation, session ownership, timeouts, payload
content, and the audit-correction tests from this round).

The **last confirmed live Odoo.sh run with 0 failed, 0 error(s)**
covered **636 post-tests (662 tests total)** - the package as it
stood *before* Phase 3. The Phase-3 package was subsequently run live
on Odoo.sh (Version 45): **5 failed, 2 errors of 692 post-tests (720
tests total)** - a real result, not a placeholder. Every one of the 7
root causes behind those failures has since been identified and fixed
in this current package (see the Change Log). This corrected package
has been verified by direct static execution in this environment
(real, standalone `unittest` runs, or direct source-contract checks
against the actual files - see each suite's own HONEST SCOPE NOTE for
what that does and does not prove) but **not yet** re-run as part of a
live Odoo 19 regression. No claim is made here that all 724 have
passed together against a live
instance - that run is still pending (see "Commercial Readiness
Status" below).

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
- **Development migrations** (`19.0.7.7.4`, `19.0.7.8.0`,
  `19.0.7.9.2`, `19.0.7.22.0`) remain in Git for the development
  branch, classified development-history-only - none apply to a fresh
  commercial install and are planned for exclusion from the commercial
  package.
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
| Automated test suite (724 static test methods) internally consistent | ✅ Pass |
| Last confirmed live Odoo.sh regression baseline (0 failed, 0 errors) | ✅ **636 post-tests (662 tests total)** (pre-Phase-3 package) |
| Version 45 live Odoo.sh Phase-3 validation run | ❌ **5 failed, 2 errors of 692 post-tests (720 tests total)** — all 7 root causes since identified and fixed in the current package; kept as an honest historical record, not removed on a later successful run |
| Corrected package (this document's own current test count) re-run against live Odoo 19 | ⚠️ **Not yet run - awaiting a fresh Odoo.sh regression** |
| Live two-screen realtime check (backend + kiosk simultaneously) | ⚠️ **Requires a live instance** |
| Module upgrade test on an existing development database | ⚠️ **Requires a live instance** |
| Live regression pass: POS → Routing → KDS → Preparing → Ready → Completed, quantity increase/decrease/to-zero, cancellation, refund, multi-station, all three Operating Modes, Public Kiosk token enforcement, printing claim/lease | ⚠️ **Requires a live instance - the client's own environment is the only one available for this** |
| `action_move_station()` deletion approved | ✅ Confirmed by client - no external RPC contract exists |
| Priority field schema-removal decision | ⏳ Deferred to first commercial baseline build |
| Development migrations excluded from commercial package | ⏳ Classified, not yet executed - pending approval |
| Arabic backend/Internal KDS/Public Kiosk translation coverage (current code) | ✅ Pass - AST-verified against current Python; both screens' own operational labels confirmed complete |
| Arabic thermal output (Direct Network raster + Legacy Print Agent) | ⚠️ **Not yet performed by the client - actual 80mm printer output review remains pending** |
| Live visual RTL rendering (all required screens) | ⚠️ **Requires a live instance** |
| Live visual review (general commercial polish, both KDS screens) | ⚠️ **Not yet performed by the client - pending** |
| End-to-end commercial demo rehearsal | ⚠️ **Not yet performed by the client - pending** |
| Full translation completeness audit (XML views/selection labels) | ⏳ Python coverage confirmed; XML requires Odoo's own export tool on a live instance |
| Arabic runtime scenario pass (POS → Send → KDS → ... → Completed, in Arabic) | ⚠️ **Requires a live instance** |

**This document does not claim the product is commercially ready** -
every item above marked ⚠️ or ⏳ is a real, open gate. It states plainly
what has been verified by static analysis in this environment (which
has no live Odoo instance) versus what can only be confirmed by the
client's own live testing, exactly as every item above shows.
