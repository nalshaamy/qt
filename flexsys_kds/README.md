# FlexSys KDS

A multi-station Kitchen Display System module for Odoo 19, built for the
FlexSys restaurant/café POS platform. Routes POS orders to the right
production stations in real time, tracks preparation SLA, optionally
runs an Expeditor/Packing final-assembly stage, and manages kitchen
receipt printing through an external Print Agent.

For the full round-by-round development history, see
[CHANGELOG.md](CHANGELOG.md). For deeper technical detail, see
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and
[docs/PRINT_AGENT.md](docs/PRINT_AGENT.md).

## Current status

**Release 19.0.6.0.0 — code-complete against the "Final Master Gap
Analysis & Release Closure" request's Sections A-B; not yet signed
off.** See [RELEASE_STATUS.md](RELEASE_STATUS.md) for the full
item-by-item mapping of that request's own structure to what's actually
verified versus what still needs a human on a live Odoo 19 instance
before this release can be tagged - in short: every automatable check
(546 tests, `py_compile`/XML well-formedness/JS syntax on every file)
passes, and every known live-runtime bug found so far has been fixed
(see CHANGELOG.md's v5.2.1 through v5.5.1 entries for that history) -
but a live two-screen realtime check, a visual density/breadcrumb
check, and a manual walkthrough watching for Tracebacks/RPC_ERROR/
OwlError have not been performed in this environment, which has no
running Odoo instance to perform them against. Phase 2 (device
enrollment, QR pairing, PWA) has not been started, per that same
request's explicit instruction not to.

## Features

- **Two KDS screens**: an authenticated backend screen (Odoo login) and
  a public kiosk screen (per-station token, no Odoo session needed) -
  functionally and visually equivalent.
- **Station-based routing** with a rule engine (product / POS category /
  inventory category / order type / source / POS config), multi-company
  isolated, with a product/category-level fallback chain.
- **Configurable POS→KDS send trigger** per point of sale - After
  Payment (default), or On Send to KDS (uses Odoo's own native POS
  Send/New action - not a custom button - so a dine-in order can reach
  the kitchen before payment when configured).
- **Full order lifecycle**: New → Accepted → Preparing → Ready →
  (Expeditor/Packing, if enabled) → Completed, plus Cancel/Hold and an
  Administrator-tier override for reopening.
- **Live SLA tracking** per station (target time + warning/late
  thresholds, validated at configuration time), with its own separate
  SLA for the Expeditor/Packing stage.
- **Printing**: a print job queue with an atomic claim/lease mechanism
  and a versioned JSON payload contract for an external Print Agent
  process (see [docs/PRINT_AGENT.md](docs/PRINT_AGENT.md) - Odoo does
  not talk to a physical printer directly).
- **Role-based security**: Operator / Supervisor / Branch Manager /
  Administrator tiers, station-scoped record rules, and write-guards on
  every workflow-significant field (state, priority, timestamps) so they
  can only change through the workflow engine, never a raw write.
- **Full audit trail**: every state transition, override, and system
  correction is logged to `kds.event`.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full breakdown
(models, controllers, data flow). In brief:

- **`kds.order` / `kds.order.line`**: the core workflow models, driven
  by a centralized transition engine (`_wf_transition`/
  `_line_transition`) - every state change goes through it, including
  system-triggered corrections (POS delta sync, cancellation
  propagation), never a raw `write()`.
- **`kds.station`**: a physical prep station (or the Expeditor/Packing
  stage, marked via `is_expeditor`), with its own SLA config, printers,
  and assigned users.
- **`kds.routing.rule`**: matches an incoming product to a station.
- **`kds.expeditor.task`**: the optional final-assembly/handoff stage,
  independently tracked (own state machine, timestamps, SLA).
- **`kds.print.job`**: the print queue an external Print Agent polls.
- **`kds.event`**: the audit log.
- **`pos.order`/`pos.order.line`/`pos.config` extensions**: the POS-side
  integration (sync trigger, delta updates, cancellation propagation).

## Installation

1. Copy the module into your Odoo 19 `custom_addons/` directory.
2. **Apps → Update Apps List** (Developer Mode required).
3. Find "FlexSys KDS" and click **Install** (or **Upgrade** if updating
   an existing install).
4. Hard-refresh your browser (Ctrl+Shift+R) after any upgrade that
   touches frontend assets.

## Initial configuration

1. **FlexSys KDS → Configuration → Stations**: create one station per
   physical prep area (Kitchen, Bar, Coffee, etc.). Set target
   preparation time and warning/late thresholds (validated - Late must
   exceed Warning, both must be positive). Assign the users who work
   that station under its "Assigned Users" field - this is what scopes
   what they can see/act on.
2. **Routing**: either configure explicit **Routing Rules** (matching by
   product, POS category, order type, source, or POS config), or rely on
   the simpler per-product/per-category default station fields on the
   product/category form - the rule engine tries rules first, then falls
   back to those defaults.
3. **Printing** (optional): create **Printers** under a station, then
   set up an external Print Agent process to poll for jobs - see
   [docs/PRINT_AGENT.md](docs/PRINT_AGENT.md). No agent is included in
   this module.
4. **POS Send-to-KDS Settings** (FlexSys KDS → Configuration): per POS,
   choose when an order reaches the kitchen - defaults to **Payment**
   (safest, matches a quick-service flow); **Order Validation** or **POS
   Submit** let a dine-in order reach the kitchen before payment.
5. **Expeditor/Packing** (optional): mark one station `is_expeditor` per
   company to enable the final-assembly stage - see below. Leave every
   station's `is_expeditor` off to keep the simpler direct-to-Completed
   flow (the default, and the only behavior that existed before this
   feature).

## Workflow

`kds.order`/`kds.order.line` share one state machine: **New → Accepted →
Preparing → Ready → Completed**, with **Cancelled** and **On Hold**
reachable from most active states. Reopening a Ready or Completed
record back to Preparing requires the Administrator-tier override
permission for a *manual* action - but the same correction happens
automatically, through the same centralized engine, for system-triggered
cases (see below), without needing a human to hold that permission.

**Ready and Complete are two separate, deliberate steps** - reaching
Ready never auto-completes an order, with or without Expeditor/Packing
enabled. An order sits at Ready indefinitely, with no time limit, until
someone actually taps **Complete** on it - a dedicated button that
appears on both KDS screens once every line is Ready (the public kiosk
gained order-level completion specifically for this; it previously only
supported line-level actions). With Expeditor/Packing enabled, Ready
instead activates the packing task first, and completion happens once
that task's own Complete step finishes (see below) - Expeditor's own
completion step was always separate from Ready and is unaffected by
this.

**Both KDS screens have a real, dedicated COMPLETED tab** - `ALL | NEW |
PREPARING | READY | COMPLETED` - not a Ready order displayed
differently. READY means the order is sitting there waiting for someone
to tap Complete; COMPLETED means someone already did. A completed order
stays visible under COMPLETED (and under ALL) for a grace period **(5
minutes, `COMPLETED_GRACE_MINUTES` in both controllers)** before
disappearing from either screen, rather than vanishing the instant
someone taps Complete - server-enforced (the query domain itself, not a
frontend filter), so a page refresh can never bring an expired order
back, and no cron is needed to hide it - the screens' own existing
poll/realtime refresh naturally stops including it once the window
closes. This is display retention only: the order record, its lines,
and its full audit trail are never touched by expiring from these two
screens - it remains permanently available in the backend Order
History/Analytics. A completed order's card shows no action button at
all (previously a disabled "DONE" one) and its status text reads
"COMPLETED" rather than reusing "READY".

**System-triggered corrections** (POS delta sync changing an
already-Ready line, a reopened production line, POS-side cancellation)
all route through the same internal methods every user-facing action
uses (`_system_reset_for_delta_sync`, `_system_reopen_if_production_incomplete`)
- never a raw `write()` - so every correction gets the same audit
event, realtime notification, and Expeditor reconciliation a normal
action would.

## Routing

`kds.routing.rule` records are matched in sequence order (first match
wins) against product, POS category, inventory category, order type,
source, and POS config. Both the matched rule *and* its destination
station are checked for company and POS-config eligibility before being
selected - a rule or station belonging to a different company, or scoped
to a different POS config, is never returned. With no matching rule,
routing falls back to the product's own default station, then its POS
category's default, then its inventory category's default - each level
checked the same way.

## SLA

Each station has its own target preparation time and warning/late
percentage thresholds (validated: both must be positive, Late must
exceed Warning). Both KDS screens compute SLA status live on every poll,
so it's always current there; the backend's own stored `sla_status`
field is kept fresh by a **1-minute scheduled job**
(`_cron_refresh_sla_status`) rather than only updating when something
happens to write to the record.

**Expeditor/Packing has its own, separate SLA** - never blended with
production SLA. Two distinct measurements: **Packing SLA** (wait time +
active work combined, from `available_time` to `ready_time`) and
**Packing Duration** (active work only, from `start_time` to
`ready_time`) - `packing_duration ≠ packing SLA elapsed time`; the
difference is however long the order sat waiting before someone
actually started packing it. Analytics reading this data should use
whichever of the two actually answers the question being asked, not
treat them as interchangeable.

## Printing

Odoo's role is managing the print job queue, an atomic claim/lease
mechanism (`FOR UPDATE SKIP LOCKED`, safe against concurrent/retrying
agents), and a versioned JSON payload contract. **Odoo does not talk to
a physical printer directly** - an external Print Agent process (not
included in this module) polls `/flexsys_kds/print/agent/claim`,
prints, then reports back via `/ack` and `/result`. See
[docs/PRINT_AGENT.md](docs/PRINT_AGENT.md) for the full protocol. The
printer form's "Mark as Online" button is exactly what it says - it does
not verify a real physical connection, only the agent can do that.

## Expeditor/Packing

An optional final-assembly/handoff stage between production finishing
and the order actually being marked done - useful for a kitchen where
someone (an expeditor) plates, boxes, or otherwise assembles a
multi-station order before it's truly ready for pickup/delivery.

Enabled per-company by marking exactly one station `is_expeditor=True`
(more than one is allowed but only the first active one is used). When
enabled, an order only creates/activates the Expeditor task once *every*
production line is Ready (cancelled lines don't block this); the task
has its own state (Waiting → Packing → Ready → Completed), responsible
user, and timestamps. A production line reopening, or new production
work arriving via POS delta sync, automatically cancels an active task
and pulls the order back to Preparing - even if packing had already
started. Completing the task includes a server-side guard confirming
production is *still* genuinely ready at that exact moment, protecting
against a stale UI or a concurrent request.

With no `is_expeditor` station configured anywhere in a company (the
default), none of this applies - an order just goes straight from Ready
to a manual Complete tap, with no intermediate Packing stage.

## Security overview

Four role tiers (Operator, Supervisor, Branch Manager, Administrator),
each implying the one below it. Record rules scope what Operators/
Supervisors can see and act on to their explicitly assigned stations (an
empty assignment means *no* access, not open access); Branch Managers
see their whole company; Administrators are unrestricted within the
standard Odoo multi-company boundary. Every workflow-significant field
(`state`, `priority`, and every timestamp) is protected against direct
writes at the ORM level - only the workflow engine's own internal
context, or a genuine `sudo()` call, can write them; a plain user-level
`write()` is rejected regardless of role.

## Current realtime behavior

The two screens use different mechanisms, accurately reflecting their
different authentication models:

- **Backend screen** (authenticated): subscribes to Odoo's `bus.bus` for
  push-based updates, scoped per-station (a leaked channel name reveals
  only that *something* changed, never order content - actual data
  still requires passing the normal access checks on the RPC that
  fetches it). **The exact `bus_service` JS API used here has not been
  verified against this specific Odoo 19 build** - it's written against
  the pattern used in recent Odoo versions, but a live check is still
  needed.
- **Public kiosk** (unauthenticated, token-based): plain 4-second
  polling - deliberately simpler, since the kiosk has no Odoo session to
  subscribe a bus channel through.

## Known current limitations

- **A full, deliberate live-runtime regression pass has not been
  performed in this environment**, because this environment has no
  running Odoo 19 instance to perform it against. Live usage on the
  developer's own instance did begin partway through this project and
  already caught and fixed several real bugs static checks couldn't
  (see CHANGELOG.md's v5.2.1 through v5.5.1 entries) - a useful
  reminder that static verification and an actual running instance
  catch genuinely different classes of problems. 546 automated test
  methods exist and are known to be internally consistent
  (`py_compile`/XML well-formedness/JS syntax checked on every file on
  every change), but actually *running* the suite
  (`--test-enable --test-tags flexsys_kds`) against a live registry, and
  the specific manual regression items listed in
  [RELEASE_STATUS.md](RELEASE_STATUS.md)'s "What still needs a human"
  section, are outstanding. Treat any version-specific assumption called
  out elsewhere in this README or in code comments (the bus API, the
  exact `bus_service` JS method signatures, `ir.cron`'s field shape,
  PostgreSQL's `FOR UPDATE SKIP LOCKED`/`make_interval`, POS's exact
  `state` values) as unverified until that pass happens.
- **No external Print Agent is included.** Physical printing requires
  building and deploying a separate process against the documented
  protocol - see [docs/PRINT_AGENT.md](docs/PRINT_AGENT.md). Explicitly
  out of scope for this release's closure, per its own gap analysis.
- **Device enrollment / QR pairing / PWA / device management / display
  modes / sound preferences (Phase 2) have not been started**, per
  explicit instruction that these must not delay this release.
- **Advanced analytics (SLA compliance %, peak hours, station
  throughput, prep-time-per-product, fulfillment trends) is future
  work**, not part of this release's closure gate.

