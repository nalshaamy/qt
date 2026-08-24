# FlexSys KDS — Architecture

Technical reference for the current implementation. For product-level
documentation see [../README.md](../README.md); for the print protocol
specifically see [PRINT_AGENT.md](PRINT_AGENT.md); for development
history see [../CHANGELOG.md](../CHANGELOG.md).

## POS → KDS data flow

1. A `pos.order`/`pos.order.line` is created or changed in the standard
   POS flow.
2. `pos.order.write()`/`create()` (in `models/pos_order.py`) call
   `_flexsys_kds_sync()`, gated by `pos.config.kds_send_trigger`
   (`payment` / `validation` / `submit` - see `models/pos_config.py`).
3. First sync creates a `kds.order` + one `kds.order.line` per
   POS line (`_flexsys_kds_create`); every later sync runs a delta diff
   (`_flexsys_kds_diff_lines`) that emits added/updated/removed lines
   rather than resending the whole order.
4. `kds.order.line.create()` routes each new line via
   `kds.routing.rule.route_product()`, stamps its arrival timestamp,
   applies Auto Accept if the destination station has it on, and
   reconciles any stale Expeditor task.
5. Both KDS screens (backend OWL app, public kiosk) poll
   `/flexsys_kds/orders` (or the kiosk's own equivalent route) and
   render the live order/line state.

## The centralized workflow engine

`kds.order`/`kds.order.line` each have their own transition matrix
(`ORDER_TRANSITIONS`/`LINE_TRANSITIONS` in `models/kds_order.py`/
`models/kds_order_line.py`) plus an override set for edge-case moves
(reopening Ready/Completed) requiring the Administrator-tier permission.
Every transition - whether triggered by a direct user action, a POS
delta sync correction, or a system-triggered cancellation - goes through
one of:

- `kds.order._wf_transition()` / `kds.order.line._line_transition()` -
  the normal, permission-checked path for user-facing actions.
- `kds.order._force_state()` - an internal-only helper for a
  side-effect state bump (e.g. a line starting pushes the order from New
  to Preparing) that skips re-checking a permission already checked for
  the action that triggered it.
- `kds.order._system_reopen_if_production_incomplete()` /
  `kds.order.line._system_reset_for_delta_sync()` - internal-only
  methods for system-triggered corrections (POS delta sync, a reopened
  production line) that don't correspond to any user-facing button at
  all, but still carry the full event/notification/timestamp discipline
  every other transition gets.

**No code path writes `state` (or `priority`, or any workflow timestamp)
directly** - both models override `write()` to reject a raw write to
those fields unless it carries an internal `kds_workflow_write` context
marker (set by the methods above) or runs under a genuine `sudo()`
context. This is enforced at the ORM level, not just in the controllers,
so any future entry point inherits it automatically.

## Models

| Model | Purpose |
|---|---|
| `kds.order` | One per POS order synced to the kitchen. Aggregate state, computed SLA status, computed Expeditor-enabled flag. |
| `kds.order.line` | One per product line. Own state, own SLA, routed station. |
| `kds.station` | A physical prep station or the Expeditor/Packing stage (`is_expeditor=True`). SLA config, assigned users, printers. |
| `kds.routing.rule` | Product/category/order-type/source/POS-config → station matching rules. |
| `kds.expeditor.task` | The optional final-assembly stage - own state machine, timestamps, SLA. |
| `kds.printer` | A physical printer tied to a station; holds the shared secret an external Print Agent authenticates with. |
| `kds.print.job` | The print queue - see [PRINT_AGENT.md](PRINT_AGENT.md). |
| `kds.event` | The audit log - every transition, override, and system correction. |
| `kds.access.mixin` | Shared station-scope and action-tier permission checks, inherited by every model that needs them. |

## Controllers

- `controllers/kds.py` - authenticated backend JSON API (`auth='user'`),
  used by the OWL backend screen. Also hosts the print agent's own
  routes (`auth='none'`, secured by a per-printer shared key - see
  [PRINT_AGENT.md](PRINT_AGENT.md)).
- `controllers/kds_kiosk.py` - the public, token-secured kiosk: a
  self-contained HTML/CSS/JS page served server-side, no Odoo session
  required. The token is the credential; regenerate it from a station's
  "Public Kiosk" tab if it leaks.

## Frontend

- **Backend screen**: an OWL app (`static/src/js/`) - `kds_store.js`
  (reactive state + polling/bus subscription), `kds_app.js` (top-level
  component, filters), `kds_order_card.js` (per-order card), plus
  `kds_i18n.js` (static UI strings - deliberately plain literals, not
  `_t()`-wrapped, after a real translation-collision bug; see the
  file's own docstring) and `kds_audio.js` (the new-order beep, a
  Web Audio API oscillator tone - no external sound file).
- **Public kiosk**: a single self-contained HTML page with inline
  CSS/JS, rendered server-side by `controllers/kds_kiosk.py` -
  deliberately not sharing code with the backend OWL app, since it has
  no Odoo session/asset bundle to draw on.

## Security model

Four groups (`group_kds_operator` < `group_kds_supervisor` <
`group_kds_branch_manager` < `group_kds_administrator`, each implying
the ones before it via `implied_ids`). Two enforcement layers:

1. **Action-tier checks** (`kds.access.mixin._kds_check_action`): each
   action (`accept`, `start`, `cancel`, `override`, etc.) has a minimum
   required group in `ACTION_MIN_GROUP` (`models/kds_access.py`).
2. **Record rules** (`security/kds_security.xml`): three tiers per
   model that needs station scoping (`kds.order`, `kds.order.line`,
   `kds.expeditor.task`) - Operator/Supervisor scoped to their assigned
   stations (an empty assignment means *no* access, not open access),
   Branch Manager scoped to company, Administrator unrestricted.
   Multiple group-scoped rules on the same model OR-combine in Odoo, and
   the group implication chain means a higher tier automatically
   inherits the lower tiers' rules too.

Multi-company isolation is enforced independently at the routing layer
(`kds.routing.rule.route_product()` checks company at every fallback
level, not just on explicit rule matches) and via the standard Odoo
multi-company record rules on `kds.order`/`kds.station`.

## Realtime notifications

`models/kds_notify.py` pushes to `bus.bus` on a per-station channel
(`flexsys_kds-station-<id>`) whenever something on that station changes
- the payload carries no order data, only a "please refetch" signal, so
a leaked channel name reveals only that *something* changed, never order
content. The backend OWL screen subscribes to this; the public kiosk
does not (no Odoo session to subscribe through) and instead polls every
4 seconds. See the README's "Current realtime behavior" section for the
verification caveat on the exact `bus_service` JS API used here.

## Testing

161 test methods across `tests/`, one file per concern
(`test_workflow.py`, `test_permissions.py`, `test_routing.py`,
`test_sla.py`, `test_printing.py`, `test_pos_sync.py`,
`test_station_kpi.py`, `test_expeditor.py`). `test_pos_sync.py` is
explicitly marked as the highest-risk file in its own module docstring,
since it has to construct real `pos.session`/`pos.order` fixtures and
`point_of_sale`'s exact required fields have shifted across Odoo
versions. None of this has been executed against a live Odoo 19
instance - see the README's "Known current limitations."
