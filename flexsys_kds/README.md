# FlexSys KDS

**Professional Multi-Station Kitchen Display & Production Management
for Odoo POS.**

FlexSys KDS routes every order from Odoo Point of Sale to the correct
kitchen or production station in real time, tracks preparation against
each station's own SLA, and gives every role — from a line cook to a
branch manager — exactly the visibility and control they need. Built
for multi-branch, multi-station restaurant and café operations.

For technical/integration detail, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

**Requirements:**
- Odoo 19
- Point of Sale
- Restaurant

FlexSys KDS requires Odoo Point of Sale and Restaurant.

---

## 1. What is FlexSys KDS

FlexSys KDS is a Kitchen Display System built directly on Odoo Point of
Sale. It replaces paper tickets and shouted orders with a live,
station-aware screen (or a printed ticket, or both) — so every station
in a multi-station kitchen sees exactly the items it needs to prepare,
the moment an order requires it, with no manual re-entry.

## 2. Key Benefits

- **Faster, more accurate service** — orders reach the right station
  automatically; nothing is re-typed or miscommunicated between the
  POS and the kitchen.
- **Full visibility across every station and branch** — managers see
  live status, SLA compliance, and a complete audit trail.
- **Scales with the business** — from a single-station café to a
  multi-branch, multi-station kitchen with a dedicated
  expeditor/packing stage.
- **Works the way the kitchen already does** — flexible per-station
  Operating Modes mean a screen, a printer, or both, per station.
- **Bilingual out of the box** — Arabic and English, with RTL-aware
  layouts for Arabic-speaking staff.

## 3. Key Features

- Multi-station Kitchen Display (authenticated backend screen +
  Public Kiosk)
- Intelligent, rule-based order routing
- Flexible station Operating Modes
- Automatic POS quantity reconciliation
- Live SLA monitoring per station
- Optional Expeditor / Packing final-assembly stage
- Kitchen printing: Direct Network (Epson ePOS), with Manual Direct
  Print and POS Direct Auto Print
- Role- and station-based security
- Multi-company support
- Arabic / English localization with RTL support
- Complete audit log

## 4. Operating Modes

Every station has one of three Operating Modes, set independently:

| Mode | Screen | Printing | Public Kiosk |
|---|---|---|---|
| **KDS Only** | Yes | — | Available |
| **Printer Only** | — | Yes | **Not available** |
| **KDS + Printer** (default) | Yes | Yes | Available |

**Printer Only stations do not allow Public Kiosk access.** This is
enforced at the backend, not only hidden in the interface — an old
Kiosk link for a station later switched to Printer Only stops working
immediately, even if bookmarked. Switching the station back to a
screen-capable mode restores Kiosk access with the same URL, with no
token regeneration needed.

## 5. POS → KDS

Each Point of Sale is configured with when an order should reach the
kitchen:

- **After Payment** (default) — the safest, simplest behavior: the
  order reaches the kitchen once payment/order completion goes
  through.
- **When Sent from POS** — uses Odoo's own native POS Send/New action,
  letting an order reach the kitchen before payment (e.g. for dine-in
  service).

**POS Quantity Reconciliation**: quantity increases are reconciled
when the POS sends the updated preparation change (the next explicit
Send), while decreases and zero-quantity cancellations are reflected
on the kitchen ticket immediately. Historical production already in
progress or completed is preserved — a later change never overwrites
or duplicates what a station has already started or finished, and a
repeated Send with no actual change never creates a duplicate update.

## 6. Routing

Orders are routed to a station using, in order:

1. An explicit **Routing Rule** (matching by product, POS category,
   inventory category, order type, source, and/or POS configuration).
2. The product's own default station, if set.
3. The product's inventory category's own default station, if set.

Routing Rules are checked in priority order (lower sequence number
first); the first matching rule wins. Every level — rules and both
fallbacks — independently respects company and POS-configuration
boundaries, so a rule or station never routes an order to the wrong
branch or an ineligible POS. Inactive (archived) rules never
participate in matching.

## 7. Workflow

Every order and order line follows one workflow: **New → Accepted →
Preparing → Ready → Completed**, with **Cancelled** and **On Hold**
reachable from active states.

- **Ready and Complete are separate, deliberate steps.** Reaching
  Ready never auto-completes an order — a dedicated Complete action
  appears once every line is Ready, and the order waits there until
  someone takes it.
- **Reopen** (returning a Ready or Completed order to Preparing) is
  available to **Supervisor and above**. It is a different action from
  the general workflow override, which is Administrator-only —
  Reopen itself does not require Administrator access.
- **Completed orders remain visible for a short grace period** on both
  screens before rolling off, so a just-completed order isn't
  instantly gone — this affects only what the live screens display;
  the full order record and its audit trail always remain available in
  the backend.
- **Multi-station orders** complete station by station — see below.

## 8. Multi-Station

An order touching more than one station (e.g. Kitchen and Bar)
completes independently at each one. Completing one station's portion
never affects another station's own progress, and each station can
only act on the lines actually routed to it. The overall order reaches
Completed only once every required station has finished its own part.

## 9. Expeditor / Packing

An optional final-assembly stage for kitchens where someone plates,
boxes, or otherwise assembles a multi-station order before it's ready
for pickup or delivery. Enable it by marking one station as the
Expeditor/Packing station.

When enabled, an order activates the Expeditor task only once every
required production station is Ready. The task has its own state
(Waiting → Packing → Ready → Completed) and its own SLA, tracked
separately from production SLA. If production work reopens (a
correction, or new items arriving), an active Expeditor task is
automatically cancelled and the order returns to Preparing. With no
Expeditor station configured, orders complete directly once Ready — no
extra step.

## 10. Printing

FlexSys KDS's commercial printing method is **Direct Network (Epson
ePOS)** — a browser-executed path with no external software required
on the client machine, managed entirely through the central
`kds.print.job` record for every production print.

Configured per-station (Station → Printing tab: Printer IP, Local
Network Access). The KDS screen's own browser talks directly to the
Epson printer over the local network. Lifecycle:

```
Print requested → kds.print.job created (Dispatched)
→ browser executes the print over Direct ePOS
→ result reported back (Printed / Failed)
```

A Direct job left "Dispatched" past its own short deadline (the
browser tab crashed, was closed, or lost its connection before
reporting back) is automatically marked Failed by a background check
— it never sits showing "Printing" indefinitely.

**POS Direct Auto Print** — server-triggered Auto Print (Printer Only
stations, and KDS+Printer stations with Auto Print switched on) prints
automatically over the same Direct Network transport: the POS
Browser's own worker claims and executes the print itself, no manual
action needed. A job created this way starts `Pending` (waiting for an
eligible POS Browser to claim it) rather than `Dispatched`
immediately. An unclaimed job fails with `NO_EXECUTOR`, a
claimed-but-unreported one fails with `RESULT_TIMEOUT`, exactly like
any other Direct Network failure.

**Odoo IoT** — reserved for a future release; not implemented in this
version. A station cannot be configured for it yet.

Every print job is visible under **Printing → Print Jobs**, showing
its own transport, target, status, and timestamps.

Legacy / Internal Compatibility Reference: an older external Print
Agent execution path is retained internally for compatibility during
this release's hardware validation window - it is not part of the
normal commercial setup flow and is not documented here; see
[docs/PRINT_AGENT.md](docs/PRINT_AGENT.md) if this applies to your
deployment.

## 11. SLA

Each station has its own target preparation time and Warning/Late
percentage thresholds. Status is computed live and refreshed
periodically, so it always reflects true elapsed time — including time
an order spent simply waiting before anyone started it. Once an order
reaches Ready, its SLA reading is fixed at that point rather than
continuing to climb while it waits for pickup or packing.

The Expeditor/Packing stage, where enabled, has its own separate SLA —
never blended with production SLA — so reporting can distinguish
production time from packing wait time and active packing time.

## 12. Security & Roles

Four permission tiers, each including the one below it:

- **Operator** — accept, start, and complete work at their own
  assigned station(s) only.
- **Supervisor** — everything an Operator can do, plus cancel, reopen,
  reprint, and print a full order.
- **Branch Manager** — full visibility and action across their entire
  company, regardless of individual station assignment.
- **Administrator** — unrestricted within the standard Odoo
  multi-company boundary, including the general workflow override.

Operators and Supervisors only see and act on the stations they're
explicitly assigned to — no assignment means no access, not open
access. Workflow-critical fields (state, timestamps) are protected
against direct edits at the database level; they can only change
through the normal workflow actions, regardless of role.

## 13. Public Kiosk

A secure, token-based screen requiring no Odoo login — suitable for a
dedicated kitchen display device. Each station has its own token and
URL; a station can be individually disabled (rejecting even a correct
token, with no need to regenerate it) and re-enabled at any time. Kiosk
access additionally follows the station's own Operating Mode (see
Section 4) — Printer Only stations are never reachable via Kiosk, even
with a valid, previously-working link. Each station's Kiosk language
is set independently of any backend user's own language.

## 14. Multi-Company

Every model, permission tier, and routing rule is scoped to company
boundaries. Stations, routing rules, and access are never
inadvertently shared across companies (branches) — a rule or station
explicitly marked to apply company-wide is the only exception, and
remains under full administrator control.

## 15. Arabic / RTL

Arabic and English localization with RTL support. Arabic localization
is provided for the Odoo backend, the Internal KDS screen, and the
Public Kiosk, with RTL-aware layouts. Printed tickets support Arabic
product names and notes; FlexSys's own Canvas-based renderer draws the
ticket using the browser's own font shaping before rasterizing it for
Direct Network printing.

## 16. Installation

1. Copy the module into your Odoo 19 `custom_addons/` directory.
2. **Apps → Update Apps List** (Developer Mode required).
3. Find "FlexSys KDS" and click **Install**.
4. Hard-refresh your browser (Ctrl+Shift+R) after installing or
   upgrading.

## 17. Initial Configuration

1. **FlexSys KDS → Configuration → Stations**: create one station per
   physical prep area. Set target preparation time and
   Warning/Late thresholds. Assign the users who work that station —
   this scopes what they can see and act on.
2. **Routing**: configure explicit Routing Rules, or rely on the
   simpler per-product/per-category default station fields.
3. **Printing** (optional): under each station's own **Printing** tab,
   choose **Direct Network** and enter the printer's IP address — the
   station's own browser talks to the Epson printer directly, no extra
   software needed.
4. **POS Send-to-KDS Settings**: per point of sale, choose when an
   order reaches the kitchen (see Section 5).
5. **Expeditor/Packing** (optional): mark one station as the
   Expeditor/Packing station to enable the final-assembly stage.

## 18. Manual QA / Acceptance

A written manual regression scenario set covering every core area of
the product — POS/Quantity, Workflow, Routing, Expeditor/Packing,
Printing, Security/Kiosk, SLA, and Arabic/RTL — is provided in
[docs/QA_TEST_SCENARIOS.md](docs/QA_TEST_SCENARIOS.md), for use when
verifying a deployment.

## 19. Known Limitations

- **Direct Network printing** requires the station's browser to reach
  the Epson printer's IP over the local network — no external software
  needed.
- **Odoo IoT** is reserved for a future release — not selectable yet.
- **Printer hardware/encoding compatibility** (including for Arabic
  text) is handled by FlexSys's own Canvas-based renderer for Direct
  Network printing.
- **Station, order-type, and source names** entered as operational
  business data (e.g. a station's own display name) are user-maintained
  data, not static translated UI labels — they display exactly as
  entered, regardless of the viewing user's own language.

## 20. Support / Technical Information

- **Technical module name**: `flexsys_kds`
- **Architecture reference**: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **Website**: https://flexsyssa.com
