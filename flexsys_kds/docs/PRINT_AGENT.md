# FlexSys KDS — Print Agent Protocol

**Legacy / Internal Compatibility Reference.** This document is not
part of the current commercial setup flow. **Direct Network (Epson
ePOS)** is the current commercial printing method — see the main
[README.md](../README.md), Section 10 ("Printing"). The Print Agent
runtime described below is retained internally, temporarily, for
compatibility pending final Epson hardware validation on the Direct
Network path; it is not offered as a customer-selectable setup option.

**No Print Agent is included in this module.** Odoo manages the print
job queue, an atomic claim mechanism, and a versioned payload contract -
actually talking to a physical printer (ESC/POS, network socket, IoT
box, etc.) is the job of a separate process you build and deploy
against the protocol below.

## Architecture at a glance

UI/DATA FIX ("Master Change Request", item 14, "Printer Form Cleanup"):
moved here from the Printer form's own long-form on-screen explanation,
which is now a short, purely operational note instead - this document
is the right place for the full technical picture, not a form an
administrator opens dozens of times a day just to configure a printer's
IP address.

Odoo's role is limited to managing Print Jobs, the atomic Claim/Lease
queue, and the versioned print payload contract (see
`kds.print.job._claim_pending_jobs()`/`._print_payload()`) - it does
not talk to a physical printer directly at any point. Actual printer
communication happens entirely in your own external Print Agent
process, which polls `/flexsys_kds/print/agent/*` on this printer's
own behalf, using its own `agent_key` to authenticate (see
"Authentication" below).

### What "Status: Online" actually means

UI/DATA FIX ("Master Change Request", item 13, "Printers List
Naming"): `kds.printer.status` reflects your own agent's own heartbeat
- specifically, it is set to `online` by `/flexsys_kds/print/agent/result`
whenever your agent successfully reports a completed print job for
this printer. It has never verified, and does not verify, that the
physical printer itself is powered on, has paper, or is genuinely
reachable at this exact moment - only that your agent process was
recently able to talk to Odoo about this printer. An earlier on-screen
"Mark as Online" button let anyone flip this to `online` manually,
with no connectivity check of any kind - that button, and the
underlying method it called, are both fully removed as of this fix,
precisely because it made `status` an unreliable mix of "a real agent
genuinely reported success" and "someone clicked a button."

## Why a separate agent

Odoo's web server process has no direct line to a physical printer
sitting on a kitchen's local network - a small bridge process, running
on a machine that *can* reach the printer, is the standard way to close
that gap. This also means printing keeps working even if Odoo is
temporarily unreachable from the printer's own network segment, as long
as the agent can still reach both.

## Authentication

Each `kds.printer` has its own `agent_key` (a random secret, visible
only to Administrators, rotatable from the printer's form). Every route
below takes `printer_id` + `agent_key`; a wrong key returns
`{'ok': False, 'error': ...}` rather than raising, so a misconfigured
agent fails safely rather than crashing.

## Claim (atomic)

```
POST /flexsys_kds/print/agent/claim
{"printer_id": <int>, "agent_key": "<secret>", "agent_id": "<your agent's own identifier>", "limit": 20}
```

Atomically claims up to `limit` pending jobs for this printer via a
single `UPDATE ... FOR UPDATE SKIP LOCKED ... RETURNING id` - two
concurrent agents (or one agent retrying after a timeout) calling this
for the same printer are guaranteed by PostgreSQL's own row-level
locking to never both come away with the same job. `agent_id` is your
own agent process's identifier (not the printer's), recorded on each
claimed job.

A claimed job holds a **lease** (default 90 seconds, `lease_seconds`
override supported) - if your agent doesn't call `ack` or `result`
within that window, the job automatically becomes claimable again by
any agent. Design your agent to call `ack` promptly after claiming, and
`result` once printing actually finishes or fails - don't hold a job
claimed indefinitely while doing slow work before acknowledging it.

Response:
```json
{"ok": true, "jobs": [ /* array of payload objects, see below */ ]}
```

## Payload contract (versioned)

Each claimed job includes everything needed to print a complete ticket
- `contract_version` is bumped whenever this shape changes in a way
that isn't purely additive; **your agent should check this field and
refuse to trust a payload shape it wasn't built against**, rather than
silently producing a malformed ticket.

```json
{
  "contract_version": 1,
  "job_id": 123,
  "job_type": "auto",
  "print_scope": "station_items",
  "copies": 1,
  "order_number": "2635-3-000028",
  "order_reference": "KDS/26/0028",
  "station": "Kitchen",
  "order_type": "dine_in",
  "order_type_label": "Dine In",
  "table": "Main Floor / 7",
  "customer_name": "Ahmed",
  "created_at": "2026-08-13T05:53:00Z",
  "items": [
    {
      "qty": 1,
      "product": "Halloumi Sandwich",
      "variant_info": "",
      "note": "",
      "station": "Kitchen",
      "line_change": "added"
    }
  ]
}
```

`print_scope` is `"station_items"` (only this printer's own station's
lines) or `"full_order"` (every station's lines, grouped) - your agent's
ticket layout should branch on this. `line_change` (`added` / `updated`
/ `removed` semantics) tells you whether an item is new since the order
was first sent, useful for flagging it visually on the ticket (e.g. an
"ADDED" badge).

## Acknowledge

```
POST /flexsys_kds/print/agent/ack
{"printer_id": <int>, "agent_key": "<secret>", "job_id": <int>}
```

Call this as soon as your agent has genuinely received the job and
intends to print it - before the physical printing itself completes.

## Result

```
POST /flexsys_kds/print/agent/result
{"printer_id": <int>, "agent_key": "<secret>", "job_id": <int>, "success": true, "error": null}
```

Call this once printing actually finishes (`success: true`) or fails
(`success: false`, with `error` describing why). A job that repeatedly
fails escalates to a backup printer if one is configured on the same
station (see `kds.print.job`'s own escalation logic in
`models/kds_print_job.py`).

## Retry behavior your agent should implement

- If a claim call fails (network error, Odoo temporarily unreachable),
  back off and retry - claimed-but-unacknowledged jobs will simply
  become reclaimable once their lease expires, so a retry-from-scratch
  is always safe.
- If printing itself fails (paper jam, offline printer), call `result`
  with `success: false` promptly rather than holding the job silently -
  this lets Odoo's own escalation/backup-printer logic react.
- Don't claim more jobs than you can realistically process before their
  lease expires - use the `limit` parameter to match your agent's actual
  throughput.

## Verification status

This protocol is exercised by automated tests
(`tests/test_printing.py`) at the Odoo/model level - the claim
atomicity, lease expiry, and payload contents. It has not been
exercised against a real external agent implementation or a live
printer, since no such agent exists yet in this project. `FOR UPDATE
SKIP LOCKED` and `make_interval()` (used internally for the lease) are
long-standing PostgreSQL features, not Odoo-version-specific, but the
whole chain has not been run end-to-end against a live Odoo 19 instance.
