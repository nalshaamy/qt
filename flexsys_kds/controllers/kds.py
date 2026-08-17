# -*- coding: utf-8 -*-
import hmac
from datetime import timedelta

from odoo import _, fields, http
from odoo.exceptions import AccessError, UserError
from odoo.http import request

# UX DECISION, per the formal dev request "Add COMPLETED Tab to KDS
# Screen" (point 9, "Completed Display Duration = 5 minutes" as the
# initial default): how long a Completed order stays visible on the
# operational KDS screens (both this one and the public kiosk) before
# disappearing - server-enforced (the actual query domain below, not
# just a frontend filter), so a page refresh can never bring an expired
# order back into the operational view. This is display retention only
# - the underlying kds.order record, its lines, and all audit/KPI/
# history data are never touched; only what these two screens choose to
# still show. Kept as a plain module-level constant rather than a
# database field, deliberately - per that same dev request point 9,
# "implement cleanly so the retention duration can later become
# configurable without rewriting the workflow... do not add unnecessary
# configuration UI... unless one already exists naturally" - no such UI
# exists yet, and a single well-named constant is already a one-line
# change to promote to a real field later if that's ever wanted, without
# touching the actual query logic that uses it.
COMPLETED_GRACE_MINUTES = 5

# UX DECISION, per the formal dev request "Cancellation Visibility
# Improvement" (point 3, "Temporary Visibility... Recommended initial
# behavior: 5 minutes, similar to the current COMPLETED retention
# behavior"): the same idea as COMPLETED_GRACE_MINUTES above, applied to
# a cancelled line or order instead of a completed one - previously,
# cancellation removed a line/order from the KDS screens the *instant*
# it was cancelled (the query below used to just exclude state=
# 'cancelled' outright), which meant kitchen staff who had already
# started preparing an item could lose all visibility of the
# cancellation before ever seeing it. A separate constant from
# COMPLETED_GRACE_MINUTES (even though both currently default to the
# same 5 minutes) so the two retention windows can be tuned
# independently later without the name implying they're the same
# setting.
CANCELLED_GRACE_MINUTES = 5


def _kds_error(exc):
    return {'ok': False, 'error': str(exc)}


def _effective_stage(lines):
    """BUG-10 FIX ("Reopened READY Order Appears in Multiple Stage
    Tabs"): the single, authoritative source of truth for which ONE
    workflow tab a station's card belongs to - "separate Ticket/Station
    Aggregate State from Individual Line State... the aggregate-state
    contract should be authoritative in the backend payload/workflow
    layer," per the dev request's own explicit requirement.

    Root cause this replaces: both KDS screens' tab filters used to run
    an INDEPENDENT `.some()` check per tab ("does ANY line match 'new'?"
    / "...'preparing'?" / ...) - each one entirely oblivious to the
    others. A reopened order with one line back at 'new' (freshly
    added/reset by a POS Delta) and another still 'preparing' correctly
    satisfied BOTH independent checks at once, so the same physical
    ticket counted under NEW *and* PREPARING simultaneously - exactly
    "NEW = 1, PREPARING = 1" for one ticket, reported live. Computing
    ONE value here, used identically for both the tab filter/count logic
    AND the card's own displayed status text (previously two separately
    -maintained pieces of logic that happened to mostly agree, per
    BUG-02's own earlier "anyStarted before anyNew" precedence fix -
    this makes that precedence the single, structurally-enforced
    source, not a coincidence of two parallel implementations), makes a
    ticket belonging to more than one tab at once structurally
    impossible rather than something each call site has to
    independently get right.

    Returns exactly one of: 'new', 'preparing', 'ready', 'completed',
    or a BUG-08 "preserved last stage" value ('new'/'preparing'/'ready')
    for a station where every line is cancelled with nothing ever
    completed - that reuses the very same value this function already
    returns for the genuine, non-cancelled case, so a cancelled-while-
    Preparing station and a genuinely-still-preparing station both
    correctly land under the same PREPARING tab, exactly as BUG-08's own
    "the card should remain temporarily visible under PREPARING"
    requires. `lines` here must already be pre-filtered to the display
    grace-period set (this function does not itself apply retention).
    """
    active = [l for l in lines if l.state != 'cancelled']
    if not active:
        if not lines:
            return 'new'
        ever_ready = any(l.ready_time for l in lines)
        ever_preparing = any(l.preparation_start_time for l in lines)
        return 'ready' if ever_ready else 'preparing' if ever_preparing else 'new'
    if all(l.state == 'completed' for l in active):
        return 'completed'
    if all(l.state in ('ready', 'completed') for l in active):
        return 'ready'
    if any(l.state in ('preparing', 'ready', 'completed') for l in active):
        return 'preparing'
    return 'new'


class FlexSysKdsController(http.Controller):
    """
    Point 1 (security hardening): every route below either (a) delegates the
    actual authorization decision to the model layer (kds.access.mixin -
    see models/kds_access.py) and simply reports AccessError back as a
    structured JSON error, or (b) does its own explicit station-membership
    check before touching data, rather than relying on auth='user' alone
    (which only proves the caller is *some* logged-in user, not that they
    are allowed at *this* station or *this* action).
    """

    def _require_kds_user(self):
        """Any FlexSys KDS route requires at least Operator; this stops a
        logged-in user with no FlexSys KDS role at all from calling these
        routes just because they have an Odoo session."""
        if not request.env.user.has_group('flexsys_kds.group_kds_operator'):
            raise AccessError(_("You do not have a FlexSys KDS role."))

    def _user_allowed_stations(self):
        user = request.env.user
        stations = request.env['kds.station'].search([('active', '=', True)])
        if user.has_group('flexsys_kds.group_kds_administrator'):
            return stations
        if user.has_group('flexsys_kds.group_kds_branch_manager'):
            return stations.filtered(lambda s: s.company_id in user.company_ids)
        if user.kds_station_ids:
            return stations.filtered(lambda s: s in user.kds_station_ids)
        return request.env['kds.station']  # unassigned operator: nothing, by design

    @http.route('/flexsyskds/<string:station_code>', type='http', auth='user')
    def kds_standalone_link(self, station_code, **kwargs):
        """Point 5: a short, memorable, per-station URL
        (/flexsyskds/KITCHEN) that a tablet can be pointed at directly,
        instead of the long, DB-specific /odoo/action-<id> URL Odoo
        generates (that numeric action ID differs per database/install,
        so it can't be hard-coded into a tablet's bookmark in advance).

        This still requires an authenticated Odoo session (auth='user') -
        if the tablet isn't logged in yet, Odoo's standard login flow
        kicks in first and redirects back here afterwards, exactly like
        any other backend URL. What this route *does* remove is needing
        to know or navigate through the Odoo backend menu structure at
        all: log in once on the device, bookmark this one URL, and from
        then on it opens straight into a fullscreen KDS screen
        pre-selected to this station.

        A fully unauthenticated public kiosk screen (matching "doesn't
        need to enter Odoo" literally) is a materially different,
        more security-sensitive feature - it would mean exposing live
        order data behind nothing but a guessable URL - and needs a
        deliberate design (e.g. a signed per-station token) rather than
        just dropping auth='user'. Flagging that as a follow-up rather
        than half-building it here.
        """
        action = request.env.ref('flexsys_kds.action_kds_screen', raise_if_not_found=False)
        if not action:
            return request.not_found()
        url = "/odoo/action-%d?station=%s&kiosk=1" % (action.id, station_code)
        return request.redirect(url)

    @http.route('/flexsys_kds/stations', type='jsonrpc', auth='user')
    def get_stations(self):
        try:
            self._require_kds_user()
        except AccessError as e:
            return _kds_error(e)
        stations = self._user_allowed_stations()
        return [{
            'id': s.id,
            'name': s.name,
            'code': s.code,
            'is_expeditor': s.is_expeditor,
            'active_order_count': s.active_order_count,
            'late_order_count': s.late_order_count,
            'company_name': s.company_id.name or '',
            'branch_name': ', '.join(s.pos_config_ids.mapped('name')) or '',
            'printing_enabled': s.operating_mode != 'kds_only',
        } for s in stations]

    def _selection_labels(self, model, field_names):
        """Return {field: {value: translated_label}} using the model's own
        field definitions, so option labels come from the exact same
        source the backend views use - translated per env.context['lang']
        automatically, no separate frontend translation table to keep in
        sync."""
        fields_info = request.env[model].fields_get(field_names)
        return {fn: dict(fields_info[fn]['selection']) for fn in field_names}

    @http.route('/flexsys_kds/orders', type='jsonrpc', auth='user')
    def get_orders(self, station_id):
        try:
            self._require_kds_user()
        except AccessError as e:
            return _kds_error(e)

        station = request.env['kds.station'].browse(station_id).exists()
        if not station or station not in self._user_allowed_stations():
            # Deliberately the same generic error whether the station
            # doesn't exist or the user just isn't allowed to see it -
            # don't leak which stations exist to an unauthorized caller.
            return _kds_error(AccessError(_("Station not available.")))

        order_labels = self._selection_labels('kds.order', ['order_type', 'priority', 'state', 'sla_status'])
        line_labels = self._selection_labels('kds.order.line', ['state', 'sla_status', 'line_change'])

        # UX DECISION (see COMPLETED_GRACE_MINUTES/CANCELLED_GRACE_MINUTES
        # above): a line shows on screen if it's genuinely active (not
        # completed, not cancelled), OR it's terminal (completed or
        # cancelled) but still within its OWN grace window.
        #
        # BUG-08 FIX ("Cancelled Lines Break Station Card Lifecycle /
        # Terminal Cleanup"), confirmed live - a real retention bug, not
        # just a display issue: this used to key the completed-line
        # grace check off order_id.completion_time (an ORDER-wide
        # timestamp, only ever set once EVERY station across the whole
        # order has completed - see kds.order.action_complete()'s own
        # _wf_transition), with an "or unset" fallback meaning a
        # completed line on a still-active multi-station order was
        # ALWAYS shown, indefinitely, for as long as any OTHER station
        # remained active - "the presence of a cancelled [or, as it
        # turned out, ANY still-active-elsewhere] line appears to
        # prevent the normal completed-retention cleanup from
        # considering the station portion fully finished," exactly as
        # reported. completed_at (kds_order_line.py, new field, stamped
        # by this line's own action_complete()) is this station's own
        # completion timestamp, entirely independent of what any other
        # station on the same order is doing - the correct signal for a
        # per-station retention check, now that BUG-07 made completion
        # genuinely per-station. A still-active-elsewhere order's
        # completed line for THIS station now correctly expires from
        # THIS station's own screen after COMPLETED_GRACE_MINUTES,
        # exactly like a single-station order's completed line always
        # has - completion elsewhere on the order no longer keeps a
        # finished station's own card alive indefinitely.
        # REAL BUG FIX ("Retention Must Follow POS Order Lifecycle"),
        # confirmed live as an explicit new business rule, extending
        # BUG-14's own principle (which only fixed the Completed side)
        # to Cancelled too: "A KDS ticket linked to an ACTIVE/OPEN POS
        # order must NEVER be removed from the live KDS by the retention
        # timer. This rule applies regardless of the current KDS
        # terminal state, including COMPLETED [and] CANCELLED." The
        # confirmed runtime scenario: a Cancelled ticket (POS quantity
        # 1 -> 0, order still active/unpaid) disappeared after the
        # ordinary cancelled_at-based grace window, even though the POS
        # order itself was never closed - "if the cashier later adds
        # another item to the same active POS order, the same KDS order/
        # ticket lifecycle must still be available for reconciliation/
        # reopen," which a prematurely-vanished ticket makes impossible.
        # cancelled_at is now gated by order_id.pos_closed_at exactly the
        # same way completed_at already is just above - unset means
        # unconditional visibility, regardless of how long ago the
        # cancellation itself happened.
        pos_closed_cutoff = fields.Datetime.now() - timedelta(minutes=COMPLETED_GRACE_MINUTES)
        cancelled_cutoff = fields.Datetime.now() - timedelta(minutes=CANCELLED_GRACE_MINUTES)
        # REAL BUG FIX (found via this module's own review while
        # implementing "Retention Must Follow POS Order Lifecycle" -
        # caught by an existing test whose own assertion turned out to
        # encode exactly the OLD, now-incorrect behavior, not by any
        # report): the pos_closed_at gate as first written treated "no
        # linked POS order at all" (order_id.pos_order_id unset -
        # entirely possible for a kds.order created directly, outside
        # any POS flow) identically to "linked POS order still active" -
        # both read pos_closed_at as False, so a non-POS ticket would
        # have gained the exact same "never expires" behavior a POS
        # ticket correctly gets while genuinely open. That's wrong: the
        # dev report's own rule is specifically about a ticket "linked
        # to an ACTIVE/OPEN POS order" - it has no bearing on a ticket
        # with no POS order to wait on in the first place, which must
        # keep expiring the original way (its own completed_at/
        # cancelled_at directly). Every completed_at/cancelled_at
        # comparison below is therefore now itself conditioned on
        # order_id.pos_order_id being set, not just on pos_closed_at's
        # own value.
        lines = request.env['kds.order.line'].search([
            ('station_id', '=', station.id),
            '|', '|',
                ('state', 'not in', ('completed', 'cancelled')),
                '&', ('state', '=', 'completed'),
                    '|',
                        '&', ('order_id.pos_order_id', '!=', False),
                            '|', ('order_id.pos_closed_at', '=', False), ('order_id.pos_closed_at', '>=', pos_closed_cutoff),
                        '&', ('order_id.pos_order_id', '=', False), ('completed_at', '>=', pos_closed_cutoff),
                '&', ('state', '=', 'cancelled'),
                    '|',
                        '&', ('order_id.pos_order_id', '!=', False),
                            '|', ('order_id.pos_closed_at', '=', False), ('order_id.pos_closed_at', '>=', cancelled_cutoff),
                        '&', ('order_id.pos_order_id', '=', False), ('cancelled_at', '>=', cancelled_cutoff),
        ])
        orders = lines.mapped('order_id').sorted(
            key=lambda o: (o.priority != 'vip', o.priority != 'urgent',
                            o.priority != 'priority', o.created_time))
        result = []
        for order in orders:
            # REAL BUG FIX, confirmed live (dev request "Remaining Fixes
            # After v19.0.7.0.0 Review", item 1): the search above
            # already correctly includes a cancelled line within its own
            # grace window - but this second, separate filter (rebuilding
            # the station-scoped line list from order.line_ids, not from
            # the already-correct `lines` search result) unconditionally
            # excluded state == 'cancelled' with no grace-period check at
            # all. A fully-cancelled order's only lines for this station
            # all failed this filter, `order_lines` came back empty, and
            # `if not order_lines: continue` skipped the entire order -
            # "Cancel Order -> immediately disappears", even though the
            # grace-period logic upstream was completely correct. Split
            # into two sets: `display_lines` (what actually goes in the
            # payload - terminal-but-within-grace lines included,
            # matching the search's own condition exactly) and
            # `active_line_sla` (still correctly excludes cancelled
            # entirely - a cancelled line's SLA status is not a
            # meaningful input to the order's own late/warning/normal
            # badge).
            #
            # BUG-08 FIX (see the search domain's own detailed comment
            # above for the full root-cause explanation): mirrors that
            # same fix here - completed_at (per-line), not
            # order_id.completion_time, and symmetrically applies the
            # same grace-period condition to a completed line as to a
            # cancelled one, rather than letting every completed line
            # through unconditionally the way an earlier version of
            # this exact filter did.
            #
            # BUG-14 FIX: mirrors the search domain's own change above -
            # order.pos_closed_at (not completed_at) anchors a completed
            # line's own grace check, and an order whose POS side hasn't
            # closed at all is unconditionally kept.
            #
            # REAL BUG FIX ("Retention Must Follow POS Order Lifecycle"):
            # mirrors the search domain's own change above for Cancelled
            # too - order.pos_closed_at gates cancelled_at exactly the
            # same way it already gates completed_at, so a Cancelled
            # line's own retention now also depends on POS closure, not
            # purely on how long ago the cancellation itself occurred.
            # Also mirrors the search domain's own pos_order_id branch -
            # a ticket with no linked POS order at all falls back to the
            # original completed_at/cancelled_at expiry directly, never
            # gaining an unintended "never expires" behavior.
            display_lines = order.line_ids.filtered(
                lambda l, sid=station.id, cc=cancelled_cutoff, pcc=pos_closed_cutoff, o=order: l.station_id.id == sid and (
                    (l.state not in ('completed', 'cancelled'))
                    or (l.state == 'completed' and (
                        (o.pos_order_id and (not o.pos_closed_at or o.pos_closed_at >= pcc))
                        or (not o.pos_order_id and l.completed_at and l.completed_at >= pcc)
                    ))
                    or (l.state == 'cancelled' and (
                        (o.pos_order_id and (not o.pos_closed_at or o.pos_closed_at >= cc))
                        or (not o.pos_order_id and l.cancelled_at and l.cancelled_at >= cc)
                    ))
                ))
            if not display_lines:
                continue
            # Point: order.sla_status is store=True (needed for the
            # backend list view's "Late" filter domain), which means it
            # only recomputes on an explicit write to a dependency field -
            # NOT purely because time has passed. A ticket sitting
            # untouched past its target time would show stale ('normal')
            # on screen until something else happened to write to it.
            # kds.order.line.sla_status is non-stored (always fresh on
            # read), so recompute the *live* order-level status here from
            # the lines actually being sent to this screen, instead of
            # trusting the potentially-stale stored field. The stored
            # field is left as-is for the backend list's own filter.
            active_line_sla = display_lines.filtered(lambda l: l.state != 'cancelled').mapped('sla_status')
            if 'late' in active_line_sla:
                live_sla_status = 'late'
            elif 'warning' in active_line_sla:
                live_sla_status = 'warning'
            else:
                live_sla_status = 'normal'
            # Same defensive, best-effort table lookup as the public
            # kiosk controller - see kds_kiosk.py for the caveat about
            # unverified restaurant.table field names in this build.
            table_label = ''
            table = getattr(order.pos_order_id, 'table_id', False)
            if table:
                floor_name = getattr(getattr(table, 'floor_id', False), 'name', '') or ''
                table_num = getattr(table, 'table_number', '') or getattr(table, 'name', '') or ''
                table_label = f"{floor_name} / {table_num}" if floor_name and table_num else (table_num or floor_name)
            result.append({
                'id': order.id,
                'name': order.name,
                'pos_reference': getattr(order.pos_order_id, 'pos_reference', '') or '',
                'order_type': order.order_type,
                'order_type_label': order_labels['order_type'].get(order.order_type),
                'priority': order.priority,
                'priority_label': order_labels['priority'].get(order.priority),
                'state': order.state,
                'state_label': order_labels['state'].get(order.state),
                # BUG-10 FIX: see _effective_stage()'s own docstring -
                # the single authoritative value both the tab filters/
                # counts AND the card's own displayed status now use, so
                # a ticket can never belong to more than one workflow
                # tab at once.
                'effective_stage': _effective_stage(display_lines),
                'sla_status': live_sla_status,
                'sla_status_label': order_labels['sla_status'].get(live_sla_status),
                'customer_name': order.customer_name,
                'employee_name': getattr(order.pos_order_id.sudo().user_id, 'name', '') or '',
                'table_label': table_label,
                'company_name': order.company_id.name or '',
                'pos_config_name': order.pos_config_id.name or '',
                'table_number': order.table_number,
                'created_time': order.created_time and order.created_time.isoformat() + 'Z',
                'lines': [{
                    'id': l.id,
                    'product_name': l.product_name,
                    'qty': l.qty,
                    'note': l.note,
                    'variant_info': l.variant_info,
                    'state': l.state,
                    'state_label': line_labels['state'].get(l.state),
                    'sla_status': l.sla_status,
                    'sla_status_label': line_labels['sla_status'].get(l.sla_status),
                    'line_change': l.line_change,
                    'line_change_label': line_labels['line_change'].get(l.line_change),
                    'qty_delta': l.qty_delta,
                    # BUG-08 FIX ("Preserve Last Operational State"): these
                    # two let the frontend determine, for a station whose
                    # every line is now terminal (completed/cancelled)
                    # with none genuinely completed, what tab the card
                    # should still be shown under (NEW/PREPARING/READY) -
                    # whichever operational stage this line actually
                    # reached before being cancelled, not just "it's
                    # gone now". A cancelled line that was never Started
                    # has neither set; one cancelled while Preparing has
                    # preparation_start_time only; one cancelled after
                    # reaching Ready (or genuinely Completed, which
                    # always implies Ready first) has both.
                    'preparation_start_time': l.preparation_start_time and l.preparation_start_time.isoformat() + 'Z',
                    'ready_time': l.ready_time and l.ready_time.isoformat() + 'Z',
                } for l in display_lines],
            })
        return result

    @http.route('/flexsys_kds/line/action', type='jsonrpc', auth='user')
    def line_action(self, line_id, action, reason=False):
        try:
            self._require_kds_user()
            line = request.env['kds.order.line'].browse(line_id).exists()
            if not line:
                return _kds_error(AccessError(_("Order line not found.")))
            # BUG-07 FIX ("Station COMPLETE does not transition from
            # READY"): 'complete' added to this dispatch map - see
            # kds_order_line.py's own new action_complete() for the full
            # explanation of what completing a single line (this
            # station's own portion) now does, independently of every
            # other station on the same order.
            method = {
                'accept': line.action_accept,
                'start': line.action_start,
                'ready': line.action_ready,
                'complete': line.action_complete,
            }.get(action)
            if action == 'cancel':
                line.action_cancel(reason=reason)
            elif method:
                method()
            else:
                return {'ok': False, 'error': str(_('Unknown action'))}
            return {'ok': True, 'state': line.state}
        except AccessError as e:
            return _kds_error(e)
        # REAL BUG FIX, found via a proactive sweep for hidden
        # regressions (not a reported failure): every workflow action
        # method in this module (_line_transition/_wf_transition) has
        # always raised UserError for an invalid transition ("cannot
        # move line from 'X' to 'Y'") - a pre-existing gap, not
        # something this round introduced, but one BUG-07's own
        # action_complete() guard made significantly more likely to be
        # hit in practice (any attempt to complete a station/order that
        # isn't actually eligible now always raises it). Uncaught here,
        # it would have propagated as a raw, unhandled server error
        # instead of the clean {'ok': False, 'error': ...} JSON response
        # the frontend on both KDS screens actually expects and handles
        # gracefully (showing the message to the operator, not crashing
        # the screen).
        except UserError as e:
            return _kds_error(e)

    @http.route('/flexsys_kds/order/action', type='jsonrpc', auth='user')
    def order_action(self, order_id, action):
        try:
            self._require_kds_user()
            order = request.env['kds.order'].browse(order_id).exists()
            if not order:
                return _kds_error(AccessError(_("Order not found.")))
            allowed_actions = {
                'accept', 'start_preparing', 'ready', 'complete',
                'cancel', 'hold', 'reopen', 'print_full_order',
            }
            if action not in allowed_actions:
                return {'ok': False, 'error': str(_('Unknown action'))}
            method = getattr(order, 'action_%s' % action)
            method()
            return {'ok': True, 'state': order.state}
        except AccessError as e:
            return _kds_error(e)
        # Same fix as line_action's own matching comment above - this is
        # specifically the route through which action_complete()'s own
        # new BUG-07 guard ("cannot complete order ... yet - Station X
        # still has active production") is actually reachable from the
        # order form/admin UI, and must surface as a clean error
        # message, not an unhandled crash.
        except UserError as e:
            return _kds_error(e)

    @http.route('/flexsys_kds/print/reprint', type='jsonrpc', auth='user')
    def reprint(self, order_id, station_id, reason, reason_note=False):
        try:
            self._require_kds_user()
            order = request.env['kds.order'].browse(order_id).exists()
            station = request.env['kds.station'].browse(station_id).exists()
            if not order or not station:
                return _kds_error(AccessError(_("Order or station not found.")))
            if station.operating_mode == 'kds_only':
                return _kds_error(AccessError(_("Printing is not enabled for this station.")))
            # Explicit instruction: this button's availability is gated by
            # the station's own printing configuration (operating_mode),
            # not by a per-user Supervisor permission - bypass_check=True
            # skips the normal 'reprint' action-tier check
            # (kds.access.mixin.ACTION_MIN_GROUP) for this specific
            # card-level print button. The permission tier itself is left
            # unchanged for any other future caller of create_reprint that
            # might still want it Supervisor-gated.
            job = request.env['kds.print.job'].create_reprint(
                order, station, reason, reason_note, bypass_check=True)
            return {'ok': True, 'job_id': job.id}
        except AccessError as e:
            return _kds_error(e)
        # Same fix as line_action/order_action's own matching comment
        # above - create_reprint() raises ValidationError (a UserError
        # subclass in Odoo's own exception hierarchy, so this catches it
        # too) when no reason is supplied. Found via the same proactive
        # sweep, not a reported failure - genuinely reachable if this
        # route is ever called with an empty reason.
        except UserError as e:
            return _kds_error(e)


class FlexSysKdsPrintAgentController(http.Controller):
    """
    Point 5 (printing engine): endpoints for an external, unauthenticated
    (from Odoo's session point of view) print agent/bridge process running
    near the physical printers - typically on the same LAN, polling for
    jobs and reporting results back. It authenticates with a per-printer
    `agent_key` instead of an Odoo user session, since it is not a human
    logging in.

    SECURITY NOTE: this is a starting point, not a hardened production
    integration. Before going live, at minimum: serve this over HTTPS only,
    rate-limit these routes, and consider binding the agent_key to a
    specific source IP/subnet if your print bridge runs on a fixed
    network segment.
    """

    def _printer_from_key(self, printer_id, agent_key):
        printer = request.env['kds.printer'].sudo().browse(printer_id).exists()
        if not printer or not agent_key or not printer.agent_key or \
                not hmac.compare_digest(printer.agent_key, agent_key):
            return None
        return printer

    @http.route('/flexsys_kds/print/agent/claim', type='jsonrpc', auth='none', csrf=False)
    def agent_claim_jobs(self, printer_id, agent_key, agent_id, limit=20):
        """Replaces the old two-step pending-list + dispatch-by-id flow
        with a single atomic claim - see
        kds.print.job._claim_pending_jobs()'s own docstring for the full
        race-condition rationale (audit finding, HIGH). `agent_id` is a
        string the print agent process itself supplies to identify
        itself (not the printer's own identity) - stored on each claimed
        job's claimed_by_agent field.

        Response payload is the versioned JSON contract from
        kds.print.job._print_payload() (audit finding "Complete Print
        Payload", HIGH) - everything the agent needs to generate a
        complete ticket without any further, unsafe model access.
        """
        printer = self._printer_from_key(printer_id, agent_key)
        if not printer:
            return {'ok': False, 'error': str(_('Invalid printer or agent key'))}
        if not agent_id:
            return {'ok': False, 'error': str(_('agent_id is required to claim jobs'))}
        jobs = request.env['kds.print.job'].sudo()._claim_pending_jobs(
            printer, agent_id, limit=limit)
        return {'ok': True, 'jobs': [job._print_payload() for job in jobs]}

    @http.route('/flexsys_kds/print/agent/ack', type='jsonrpc', auth='none', csrf=False)
    def agent_ack(self, printer_id, agent_key, job_id):
        printer = self._printer_from_key(printer_id, agent_key)
        if not printer:
            return {'ok': False, 'error': str(_('Invalid printer or agent key'))}
        job = request.env['kds.print.job'].sudo().browse(job_id).exists()
        if not job or job.printer_id != printer:
            return {'ok': False, 'error': str(_('Job not found for this printer'))}
        job.action_acknowledge()
        return {'ok': True}

    @http.route('/flexsys_kds/print/agent/result', type='jsonrpc', auth='none', csrf=False)
    def agent_result(self, printer_id, agent_key, job_id, success, error=False):
        printer = self._printer_from_key(printer_id, agent_key)
        if not printer:
            return {'ok': False, 'error': str(_('Invalid printer or agent key'))}
        job = request.env['kds.print.job'].sudo().browse(job_id).exists()
        if not job or job.printer_id != printer:
            return {'ok': False, 'error': str(_('Job not found for this printer'))}
        if success:
            job.action_mark_printed()
            printer.write({'status': 'online', 'last_seen': fields.Datetime.now()})
        else:
            job.action_mark_failed(error_msg=error or 'Agent reported failure')
        return {'ok': True}
