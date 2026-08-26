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

`19.0.7.29.12` (development baseline). Final renumbering to the first
commercial baseline, `19.0.1.0.0`, happens after all release gates
below pass and the client gives explicit approval - not automatic.

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
- Printing: job queue with an atomic claim/lease mechanism and a
  versioned payload contract for an external Print Agent (not
  included - see [docs/PRINT_AGENT.md](docs/PRINT_AGENT.md)).
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

- One immutable `kds.print.job` record per actual print/reprint
  request.
- Atomic claim/lease: `_claim_pending_jobs()` uses a single
  `UPDATE ... WHERE ... RETURNING` with PostgreSQL's
  `FOR UPDATE SKIP LOCKED`, so two concurrent agent calls for the same
  printer can never claim the same job. This is the only supported
  dispatch path - the legacy `action_dispatch()` method has been
  removed.
- Automatic retry with backup-printer fallback after repeated
  failures, each escalation independently audited.
- Printer metadata (`port`, `usb_identifier`, `serial_number`) is kept
  as reference documentation for whoever configures the external Print
  Agent - not read by any Odoo-side logic, by design (Odoo manages the
  queue; a separate process talks to the physical printer).
- No external Print Agent is included - building and deploying one is
  a separate project, against the documented protocol.

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
  (`_station_from_token()`) is called by all four public kiosk
  routes (the initial page and three JSON-RPC API endpoints) - there is
  no alternate path that resolves a station without going through it.
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

**563 tests** as of this document, covering `py_compile`, XML
well-formedness, and JS syntax on every file on every change, plus
functional/behavioral coverage for every area above. Internally
consistent and known to pass these static checks; **actually running
the full suite against a live Odoo 19 instance is a separate,
required gate** - this environment has no live Odoo instance to run
it against (see "Commercial Readiness Status" below).

---

## Known Limitations

- **No external Print Agent is included.** Building and deploying one
  is a separate project against the documented protocol.
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
| Automated test suite (563 tests) internally consistent | ✅ Pass |
| Automated test suite actually run against live Odoo 19 | ⚠️ **Not verified in this environment - no live instance available** |
| Live two-screen realtime check (backend + kiosk simultaneously) | ⚠️ **Requires a live instance** |
| Module upgrade test on an existing development database | ⚠️ **Requires a live instance** |
| Live regression pass: POS → Routing → KDS → Preparing → Ready → Completed, quantity increase/decrease/to-zero, cancellation, refund, multi-station, all three Operating Modes, Public Kiosk token enforcement, printing claim/lease | ⚠️ **Requires a live instance - the client's own environment is the only one available for this** |
| `action_move_station()` deletion approved | ✅ Confirmed by client - no external RPC contract exists |
| Priority field schema-removal decision | ⏳ Deferred to first commercial baseline build |
| Development migrations excluded from commercial package | ⏳ Classified, not yet executed - pending approval |
| Arabic backend/Internal KDS/Public Kiosk translation coverage (current code) | ✅ Pass - AST-verified against current Python; both screens' own operational labels confirmed complete |
| Arabic thermal/Print Agent output | ⚠️ **Not tested - requires a live Print Agent and physical printer** |
| Live visual RTL rendering (all required screens) | ⚠️ **Requires a live instance** |
| Full translation completeness audit (XML views/selection labels) | ⏳ Python coverage confirmed; XML requires Odoo's own export tool on a live instance |
| Arabic runtime scenario pass (POS → Send → KDS → ... → Completed, in Arabic) | ⚠️ **Requires a live instance** |

**This document does not claim the product is commercially ready** -
every item above marked ⚠️ or ⏳ is a real, open gate. It states plainly
what has been verified by static analysis in this environment (which
has no live Odoo instance) versus what can only be confirmed by the
client's own live testing, exactly as every item above shows.
