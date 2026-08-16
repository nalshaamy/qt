# -*- coding: utf-8 -*-
import hmac
from datetime import timedelta

from odoo import _, fields, http
from odoo.exceptions import AccessError
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
        # completed, not cancelled), OR its order completed within the
        # completed grace window, OR the line itself was cancelled within
        # the cancelled grace window. The line's own cancelled_at (not the
        # order's) is checked here deliberately - a single cancelled item
        # on an otherwise-active order, and a fully cancelled order (whose
        # cascade sets cancelled_at on every affected line individually -
        # see kds_order.py::action_cancel(), kds_order_line.py::
        # action_cancel()) both correctly fall under this same check,
        # without needing a separate order-level clause here.
        completed_cutoff = fields.Datetime.now() - timedelta(minutes=COMPLETED_GRACE_MINUTES)
        cancelled_cutoff = fields.Datetime.now() - timedelta(minutes=CANCELLED_GRACE_MINUTES)
        lines = request.env['kds.order.line'].search([
            ('station_id', '=', station.id),
            '|', '|',
                ('state', 'not in', ('completed', 'cancelled')),
                '&', ('state', '=', 'completed'), ('order_id.completion_time', '>=', completed_cutoff),
                '&', ('state', '=', 'cancelled'), ('cancelled_at', '>=', cancelled_cutoff),
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
            # payload - cancelled-within-grace included, matching the
            # search's own condition exactly) and `active_line_sla`
            # (still correctly excludes cancelled entirely - a cancelled
            # line's SLA status is not a meaningful input to the order's
            # own late/warning/normal badge).
            display_lines = order.line_ids.filtered(
                lambda l, sid=station.id, cc=cancelled_cutoff: l.station_id.id == sid and (
                    l.state != 'cancelled' or (l.cancelled_at and l.cancelled_at >= cc)
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
            method = {
                'accept': line.action_accept,
                'start': line.action_start,
                'ready': line.action_ready,
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
