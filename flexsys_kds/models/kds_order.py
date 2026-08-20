# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .kds_notify import notify_stations

# Point 2: explicit order-level state transition matrix.
ORDER_TRANSITIONS = {
    'new': {'accepted', 'cancelled', 'on_hold'},
    'accepted': {'preparing', 'cancelled', 'on_hold'},
    'preparing': {'ready', 'cancelled', 'on_hold'},
    'ready': {'completed', 'cancelled'},
    'on_hold': {'new', 'accepted', 'preparing', 'cancelled'},
    'completed': set(),
    'cancelled': set(),
}
ORDER_OVERRIDE_TRANSITIONS = {
    ('ready', 'preparing'),
    ('completed', 'preparing'),
}

# SECURITY FIX (audit finding 02, CRITICAL): ir.model.access.csv grants
# Operators write=1 on kds.order (needed for legitimate fields like the
# free-text Notes tab), which also meant nothing stopped a direct
# write({'state': 'completed'}) or write({'priority': 'vip'}) via RPC/
# backend, completely bypassing ORDER_TRANSITIONS validation, permission
# checks, and timestamp/audit-event logging. These specific fields may
# now ONLY be written by the workflow engine itself (which marks its own
# writes with the kds_workflow_write context key below) or by a genuine
# sudo() context (system/internal flows, e.g. the POS sync path) - never
# by a plain user-level write(), regardless of that user's KDS role.
KDS_ORDER_PROTECTED_FIELDS = {
    'state', 'priority',
    'created_time', 'accepted_time', 'preparation_start_time',
    'ready_time', 'packing_time', 'completion_time',
}
# Note on a deliberate asymmetry: action_reopen() below is the intended,
# documented API for moving a Ready/Completed order back to Preparing
# (matches the spec's "Supervisor can Reopen Order") and only requires the
# 'reopen' permission (Supervisor+). Reaching the same state transition by
# calling action_start_preparing() directly instead goes through
# ORDER_OVERRIDE_TRANSITIONS above and requires 'override' (Administrator).
# This is intentional - action_reopen is the routine path, the generic
# action is the exceptional one - but it means the same transition has two
# different minimum permissions depending on which method reaches it. If
# that's ever surprising in practice, unify them rather than leaving it
# implicit.


class KdsOrder(models.Model):
    _name = 'kds.order'
    _inherit = ['kds.access.mixin']
    _description = 'FlexSys KDS Order'
    _order = 'create_date desc'
    _rec_name = 'name'

    name = fields.Char(required=True, copy=False, default='New')
    pos_order_id = fields.Many2one('pos.order', string='POS Order', ondelete='set null')
    pos_config_id = fields.Many2one('pos.config', string='POS')
    company_id = fields.Many2one('res.company', string='Branch', default=lambda self: self.env.company)

    source = fields.Selection([
        ('pos', 'Odoo POS'),
        ('qr', 'QR Order'),
        ('web', 'Web Order'),
        ('call_center', 'Call Center'),
        ('delivery_app', 'Delivery Application'),
        ('api', 'API'),
        ('flexsys', 'FlexSys Orders'),
    ], default='pos', required=True)

    order_type = fields.Selection([
        ('dine_in', 'Dine In'),
        ('take_away', 'Take Away'),
        ('delivery', 'Delivery'),
        ('pickup', 'Pickup'),
        ('drive_thru', 'Drive Thru'),
    ], default='dine_in', required=True)

    priority = fields.Selection([
        ('normal', 'Normal'),
        ('priority', 'Priority'),
        ('urgent', 'Urgent'),
        ('vip', 'VIP'),
    ], default='normal', required=True)

    state = fields.Selection([
        ('new', 'New'),
        ('accepted', 'Accepted'),
        ('preparing', 'Preparing'),
        ('ready', 'Ready'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('on_hold', 'On Hold'),
    ], string='Status', default='new', required=True)

    customer_name = fields.Char()
    # UI/DATA FIX ("UI / DATA IMPROVEMENT REQUEST - KDS Active Orders &
    # Order History"), confirmed live: the "Customer Name" field/label
    # was misleading - it's populated (pos_order.py::_flexsys_kds_create())
    # as `self.partner_id.name or self.pos_reference or ''`, meaning
    # for the overwhelming majority of walk-up POS orders (no partner
    # set at all), it silently falls back to the POS order's own
    # reference/number instead - "Customer Name: 2629-3-000036" is not
    # a customer name at all. customer_name itself is left exactly as
    # it was (unchanged data, unchanged fallback behavior - a real
    # customer name genuinely does show here when a partner IS set,
    # so removing the field entirely would be a real regression for
    # that case) - only the VIEW no longer labels or leads with it as
    # the primary POS-order reference; see kds_order_views.xml's own
    # comment for the actual fix (pos_order_id, labeled "POS Order",
    # now the first, prominent header field instead).
    table_number = fields.Char()
    note = fields.Text()

    # UI/DATA FIX ("UI / DATA IMPROVEMENT REQUEST"), items 3 and 4:
    # "add POS Status... Do NOT confuse KDS Status with POS Status -
    # both represent different lifecycles" and "add Payment Method...
    # if the POS order can contain more than one payment method, do
    # not silently display only one arbitrary method." Both computed
    # here, once per kds.order (not per line), and exposed to
    # kds.order.line via a plain `related` field for the Lines tab -
    # see that model's own matching fields for the full explanation.
    #
    # A plain `related='pos_order_id.state'` (not a hand-defined
    # Selection here) deliberately inherits pos.order.state's own type
    # and selection values directly from Odoo core - safer than
    # hardcoding a copy of that list, which could silently drift out
    # of sync with a different Odoo build or a state added by another
    # installed module.
    pos_order_state = fields.Selection(related='pos_order_id.state', string='POS Status', readonly=True)
    pos_payment_methods = fields.Char(
        compute='_compute_pos_payment_methods', string='Payment Method')

    line_ids = fields.One2many('kds.order.line', 'order_id', string='Order Lines')
    station_ids = fields.Many2many(
        'kds.station', compute='_compute_station_ids', store=True, string='Stations Involved')
    event_ids = fields.One2many('kds.event', 'order_id', string='Audit Log')
    print_job_ids = fields.One2many('kds.print.job', 'order_id', string='Print Jobs')
    expeditor_task_ids = fields.One2many(
        'kds.expeditor.task', 'order_id', string='Expeditor / Packing Tasks')

    created_time = fields.Datetime(default=fields.Datetime.now)
    accepted_time = fields.Datetime()
    preparation_start_time = fields.Datetime()
    ready_time = fields.Datetime()
    packing_time = fields.Datetime()
    completion_time = fields.Datetime()
    # NEW (dev request "Cancellation Visibility Improvement", point 3:
    # "Temporary Visibility... similar to the current COMPLETED retention
    # behavior"): the order-level counterpart to completion_time above -
    # needed so the KDS screens' own grace-period query (see
    # CANCELLED_GRACE_MINUTES in both controllers) has an authoritative
    # server-side timestamp to check for a fully-cancelled order, exactly
    # the same pattern already established for Completed orders.
    cancelled_at = fields.Datetime()
    # REAL BUG FIX ("BUG-14 - COMPLETED Retention Must Depend on POS
    # Closure"), confirmed live as an explicit new business rule: the
    # 5-minute Completed retention timer used to start counting from
    # completion_time above (this station/order's own kitchen-side
    # completion) unconditionally - "if KDS starts the retention timer
    # immediately when the KDS ticket reaches COMPLETED, the ticket may
    # disappear while the corresponding POS order is still active. That
    # is operationally unsafe" - a cashier could still be mid-edit on a
    # dine-in order (adding/removing/changing quantities) long after the
    # kitchen finished cooking, and the ticket would vanish from the
    # kitchen's own screen before the sale itself was ever settled.
    #
    # Stamped (pos_order.py's own write() override) the moment the
    # linked pos.order's own `state` is observed transitioning into a
    # closed state ('paid'/'done'/'invoiced') - deliberately its own
    # explicit timestamp, not a reuse of pos.order.write_date (which
    # updates on ANY field change to the order, including ones long
    # after closure - e.g. a later refund - and would therefore be an
    # unreliable, drifting anchor for "when did this order actually
    # close"). NULL for as long as the POS order remains 'draft' (still
    # active/open) - both KDS screens' own retention query (see
    # COMPLETED_GRACE_MINUTES in both controllers) now checks this
    # field, not completion_time/completed_at, to decide whether a
    # Completed ticket's grace window has even started yet: NULL means
    # "not started - stay visible unconditionally", matching the
    # required rule exactly ("the ticket must remain visible under
    # COMPLETED regardless of how long it remains open... no KDS
    # completion timeout may hide it").
    pos_closed_at = fields.Datetime()
    total_fulfillment_minutes = fields.Float(compute='_compute_total_fulfillment', store=True)

    sla_status = fields.Selection([
        ('normal', 'Normal'),
        ('warning', 'Warning'),
        ('late', 'Late'),
    ], compute='_compute_sla_status', store=True)

    is_expeditor_ready = fields.Boolean(compute='_compute_is_expeditor_ready')

    # BUG-07 FIX ("Station COMPLETE does not transition from READY"):
    # the per-station counterpart to is_expeditor_ready above, one level
    # further along - "every non-cancelled line has reached its own
    # final Completed state" (not just Ready), across every station
    # involved, not just the one that just completed its own portion.
    # See kds_order_line.py's own new action_complete() for the full
    # explanation of what this drives.
    is_fully_completed = fields.Boolean(compute='_compute_is_fully_completed')

    # AUDIT FIX ("Expeditor/Packing Workflow", the final Phase 1 item):
    # an order requires the Expeditor/Packing stage only if its own
    # company has at least one active is_expeditor station configured -
    # "Expeditor Disabled: continue using the existing normal flow" and
    # "do not force every installation to configure an Expeditor
    # Station" are both satisfied automatically: with zero is_expeditor
    # stations anywhere in the company, expeditor_enabled is always
    # False for every order there, meaning zero behavior change from
    # before this feature existed.
    expeditor_enabled = fields.Boolean(compute='_compute_expeditor_enabled')

    active = fields.Boolean(default=True)

    # ODOO 19 API MIGRATION: _sql_constraints (the old list-of-tuples
    # form) is deprecated in favor of models.Constraint as a class
    # attribute - each constraint becomes its own named attribute
    # (the attribute name replaces the old tuple's first element, the
    # constraint name) rather than an entry in a shared list. Same SQL
    # definition and error message as before, purely a declaration-
    # syntax change with no behavioral difference.
    _name_uniq = models.Constraint(
        'unique(name)', 'FlexSys KDS order reference must be unique.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('kds.order') or 'KDS/0001'
        orders = super().create(vals_list)
        for order in orders:
            self.env['kds.event'].log(order, event_type='order_created',
                                       note=_("Order created from %s") % order.source)
        return orders

    def write(self, vals):
        # SECURITY FIX (audit finding 02, CRITICAL) - see
        # KDS_ORDER_PROTECTED_FIELDS above for the full rationale.
        touched = KDS_ORDER_PROTECTED_FIELDS & set(vals.keys())
        if touched and not self.env.context.get('kds_workflow_write') and not self.env.su:
            raise AccessError(_(
                "FlexSys KDS: %s cannot be changed by writing directly - use the "
                "Accept/Start/Ready/Cancel/Hold/Reopen actions (or, for priority, "
                "action_change_priority) instead."
            ) % ', '.join(sorted(touched)))
        return super().write(vals)

    def action_change_priority(self, priority, bypass_check=False):
        self.ensure_one()
        valid_values = dict(self._fields['priority'].selection)
        if priority not in valid_values:
            raise UserError(_("Invalid priority value: %s") % priority)
        self._kds_check_order_access(bypass=bypass_check)
        self._kds_check_action('change_priority', bypass=bypass_check)
        old_priority = self.priority
        if old_priority == priority:
            return
        self.with_context(kds_workflow_write=True).write({'priority': priority})
        self.env['kds.event'].log(
            self, event_type='priority_changed', old_value=old_priority, new_value=priority)

    @api.depends('line_ids.station_id')
    def _compute_station_ids(self):
        for order in self:
            order.station_ids = order.line_ids.mapped('station_id')

    @api.depends('pos_order_id.payment_ids.payment_method_id.name')
    def _compute_pos_payment_methods(self):
        # UI/DATA FIX ("UI / DATA IMPROVEMENT REQUEST"), item 4:
        # "If the POS order can contain more than one payment method,
        # do not silently display only one arbitrary method... display
        # all applicable payment methods." pos.order.payment_ids is a
        # standard Odoo core One2many to pos.payment (split-payment
        # orders genuinely have more than one row here) - joins every
        # distinct method name with a comma rather than picking one
        # arbitrarily. Empty string, not False, for an order with no
        # payments yet (unpaid/still-open order) - a plain Char field
        # displays either the same way in a list view, but an empty
        # string reads more clearly than "False" if ever inspected via
        # a raw field export/API response.
        for order in self:
            methods = order.pos_order_id.payment_ids.payment_method_id.mapped('name')
            # dict.fromkeys(...) dedupes while preserving encounter
            # order - two cash payments (e.g. a partial refund handled
            # as a second cash line) should not read as "Cash, Cash".
            order.pos_payment_methods = ', '.join(dict.fromkeys(m for m in methods if m))

    @api.depends('line_ids.state')
    def _compute_is_expeditor_ready(self):
        # Note: this intentionally checks *all* non-cancelled lines across
        # every station, not just is_expeditor-flagged stations - matching
        # the spec's "not Ready until every required station is done"
        # rule without needing a special case for which station is the
        # packing/expeditor stage.
        for order in self:
            required_lines = order.line_ids.filtered(lambda l: l.state != 'cancelled')
            order.is_expeditor_ready = bool(required_lines) and all(
                l.state in ('ready', 'completed') for l in required_lines
            )

    @api.depends('line_ids.state')
    def _compute_is_fully_completed(self):
        # BUG-07 FIX: same shape as _compute_is_expeditor_ready above,
        # one state further - every non-cancelled line, across every
        # station, has reached 'completed' specifically (not merely
        # 'ready').
        for order in self:
            required_lines = order.line_ids.filtered(lambda l: l.state != 'cancelled')
            order.is_fully_completed = bool(required_lines) and all(
                l.state == 'completed' for l in required_lines
            )

    @api.depends('company_id')
    def _compute_expeditor_enabled(self):
        for order in self:
            order.expeditor_enabled = bool(self.env['kds.station'].search_count([
                ('company_id', '=', order.company_id.id),
                ('is_expeditor', '=', True),
                ('active', '=', True),
            ]))

    @api.depends('created_time', 'completion_time')
    def _compute_total_fulfillment(self):
        for order in self:
            if order.created_time and order.completion_time:
                delta = order.completion_time - order.created_time
                order.total_fulfillment_minutes = round(delta.total_seconds() / 60.0, 1)
            else:
                order.total_fulfillment_minutes = 0.0

    @api.depends('line_ids.sla_status')
    def _compute_sla_status(self):
        for order in self:
            statuses = order.line_ids.filtered(
                lambda l: l.state not in ('completed', 'cancelled')).mapped('sla_status')
            if 'late' in statuses:
                order.sla_status = 'late'
            elif 'warning' in statuses:
                order.sla_status = 'warning'
            else:
                order.sla_status = 'normal'

    @api.model
    def _cron_refresh_sla_status(self):
        """SLA FRESHNESS FIX (audit finding, HIGH): sla_status is
        store=True (required so the backend list view's "Late" filter can
        search on it - see kds_order_views.xml), but a store=True computed
        field only recomputes when one of its dependency *fields* gets an
        explicit write - never purely because time has passed. An order
        sitting untouched past its target time would never actually flip
        to Late in the database (though it always read correctly through
        the two custom controllers, which recompute live from the
        non-stored line-level sla_status - see v3.2's changelog entry -
        that fix only covered those two JSON endpoints, not the field
        itself, so the backend's own list/kanban/analytics views, direct
        RPC reads, and anything else reading kds.order.sla_status directly
        could still see a stale value).

        This cron periodically forces every active order to actually
        recompute, so the stored value stays genuinely fresh (bounded by
        the cron interval, not "until something unrelated happens to
        write to it") for every consumer, not just the two controllers -
        satisfying "Backend, KDS Screen and Analytics must use consistent
        SLA results" directly rather than by convention.
        """
        active_orders = self.search([('state', 'not in', ('completed', 'cancelled'))])
        if not active_orders:
            return
        # Reading .sla_status after invalidating forces Odoo to actually
        # re-run _compute_sla_status and persist the result, exactly the
        # same as any other store=True computed field recompute - no
        # explicit .write() call needed (and using one here would
        # unnecessarily re-trigger this model's own write() guard/
        # workflow-audit machinery for a field that isn't really "being
        # written" so much as "being kept fresh").
        active_orders.invalidate_recordset(['sla_status'])
        active_orders.mapped('sla_status')  # forces recompute + store across the whole batch

    @api.model
    def _cron_reconcile_stuck_orders(self):
        """SAFETY NET, found via a live pilot report: an order can end up
        with every one of its lines genuinely Ready (is_expeditor_ready
        True) while its own aggregate state never advanced past New/
        Accepted/Preparing - confirmed live (a 5-line order showing all
        5 lines Ready, "Is Expeditor Ready" checked, yet still sitting at
        "Preparing"). The normal cascade
        (kds.order.line.action_ready() -> checks is_expeditor_ready ->
        calls kds.order.action_ready()) relies entirely on whichever
        line happens to be the *last* one marked Ready correctly
        observing every sibling line's write at that exact moment - a
        plausible race if several lines are marked Ready in quick
        succession (near-simultaneous requests), and nothing else
        re-checks this after the fact if that one critical moment is
        ever missed.

        This cron is a self-healing safety net, independent of pinning
        down the exact root cause: periodically re-checks every
        non-terminal order, and if it's genuinely ready but hasn't
        advanced, pushes it through the real action_ready() (same method
        every other path uses - full audit event, notification,
        Expeditor activation if enabled, timestamp - not a raw write).
        Bounded by the cron interval, so a stuck order self-corrects
        within a couple of minutes even if this exact scenario recurs,
        rather than sitting stuck indefinitely with nothing to notice.

        REAL BUG FIX, confirmed live on Odoo.sh ("Reconciliation Cron
        Leaves Ready Order Stuck", expected 'completed' got 'ready'):
        this used to stop at action_ready(). That's correct as far as it
        goes, but leaves a genuinely-stuck order only *half* recovered -
        still sitting at Ready, needing yet another manual Complete tap
        that staff have no particular reason to know is needed for an
        order they never even knew was stuck in the first place. This is
        deliberately NOT a contradiction of the v5.4 design reversal
        ("Complete is always a deliberate action, never automatic") -
        that principle governs a *normal*, healthy order that correctly
        reached Ready through the real workflow, which this cron never
        touches at all (a healthy order is never in the New/Accepted/
        Preparing search domain below by the time it's genuinely Ready).
        This is specifically a *data-consistency recovery* path for an
        order that a race condition left stranded - the reconciliation
        cron's whole purpose is to finish correcting exactly that
        anomaly, all the way to where the order should already be, not
        stop one step short of it.

        REAL BUG FIX, confirmed live on Odoo.sh a second time ("BUG-07
        guard correctly rejecting the cron's own recovery attempt"):
        the completion step above originally called the order-level
        action_complete() directly - correct back when it unconditionally
        cascaded 'completed' to every line, but exactly the architecture
        BUG-07 replaced. action_complete() now requires
        is_fully_completed (every line already individually
        'completed'), which a just-recovered order's lines never are
        yet (they're 'ready', having just been confirmed by
        is_expeditor_ready above) - so the guard correctly refused,
        leaving the order recovered only as far as 'ready'. Fixed by
        routing through the same authoritative, station-level lifecycle
        the runtime UI itself uses, split by whether Expeditor governs
        this order - never a second, alternate completion path:

          (A) Expeditor DISABLED: completes through the real per-line
              action_complete() (the same one every station's own
              "Complete" button on both KDS screens already calls) on
              every remaining Ready line at once - its own aggregation
              (is_fully_completed) then correctly finalizes the order
              via action_complete() only once every line, across every
              station, is done.
          (B) Expeditor ENABLED: action_ready() above already activated
              the Packing task if one didn't already exist - and
              deliberately stops there. Packing is a genuine, multi-step
              MANUAL process (Start -> Mark Ready -> Complete); a task
              still sitting at 'waiting' represents real physical work
              that hasn't happened yet, which this cron has no business
              simulating or force-completing - production lines and
              Expeditor's own task history are never rewritten merely to
              reach a tidier end state. Only if the task itself
              independently got stuck already sitting at 'ready' (the
              same class of race this whole cron recovers from, one
              level down) does its own action_complete() get called -
              which correctly routes through _finalize_via_expeditor()
              internally, the exact same Expeditor-aware path the
              runtime UI uses, never an invented shortcut around it.

        Idempotent either way, by construction: re-running this cron
        against an order it already fully recovered is a no-op (nothing
        left in New/Accepted/Preparing to find, or nothing left at
        'ready' to act on) - safe to run on every cron tick regardless
        of whether the previous tick already found and fixed something.
        """
        stuck_orders = self.search([('state', 'in', ('new', 'accepted', 'preparing'))])
        for order in stuck_orders:
            if order.is_expeditor_ready:
                order.action_ready(bypass_check=True)
                # REAL BUG FIX, confirmed live on Odoo.sh (BUG-07's own
                # order-level guard correctly rejecting this): calling
                # the order-level action_complete() directly used to
                # work here, back when it unconditionally cascaded
                # 'completed' to every line - but that's exactly the
                # architecture BUG-07 replaced. action_complete() now
                # requires is_fully_completed (every line already
                # individually 'completed'), which a just-recovered
                # order's lines never are yet (they're 'ready', having
                # just been pushed there by action_ready() above) - so
                # the guard correctly refused, leaving the order
                # recovered only as far as 'ready', one step short of
                # where the (non-Expeditor) case should finish.
                #
                # Fixed by routing through the SAME authoritative,
                # station-level lifecycle the runtime UI itself uses -
                # never inventing a second, alternate completion path:
                #
                #   (A) Expeditor DISABLED: complete through the real
                #       per-line action_complete() (the same one every
                #       station's own "Complete" button on both KDS
                #       screens already calls) on every remaining Ready
                #       line at once - its own aggregation cascade
                #       (is_fully_completed) then correctly finalizes
                #       the order via action_complete() only once every
                #       line, across every station, is done.
                #   (B) Expeditor ENABLED: action_ready() above already
                #       activated the Packing task if one didn't already
                #       exist - deliberately stops there. Packing is a
                #       genuine, multi-step MANUAL process (Start ->
                #       Mark Ready -> Complete); a task that's still
                #       'waiting' represents real physical work that
                #       hasn't happened yet, which this cron has no
                #       business simulating or force-completing. If the
                #       task itself independently got stuck already
                #       sitting at 'ready' (the same class of race this
                #       whole cron exists to recover from, one level
                #       down), its own action_complete() is called -
                #       which correctly routes through
                #       _finalize_via_expeditor() internally, the same
                #       Expeditor-aware path the runtime UI uses.
                #
                # Idempotent either way: re-running this cron against an
                # order it already fully recovered is a no-op (nothing
                # left in New/Accepted/Preparing to find, or nothing
                # left at 'ready' to act on).
                if order.expeditor_enabled:
                    stuck_task = order.expeditor_task_ids.filtered(lambda t: t.state == 'ready')
                    if stuck_task:
                        stuck_task.action_complete(bypass_check=True)
                else:
                    stuck_lines = order.line_ids.filtered(lambda l: l.state == 'ready')
                    if stuck_lines:
                        stuck_lines.action_complete(bypass_check=True)

    # ---------------------------------------------------------------
    # Access: order-level actions may touch several stations at once,
    # so we require the user to be assigned to at least one station
    # involved in the order (or be a branch manager/admin).
    # ---------------------------------------------------------------
    def _kds_check_order_access(self, bypass=False):
        if bypass:
            return
        user = self.env.user
        for order in self:
            if user.has_group('flexsys_kds.group_kds_administrator'):
                continue
            if user.has_group('flexsys_kds.group_kds_branch_manager') and order.company_id in user.company_ids:
                continue
            # SECURITY FIX (audit finding 01, CRITICAL): this used to
            # `continue` here instead of raising, which meant an
            # Operator/Supervisor with NO assigned stations silently
            # skipped the station-scope check entirely - they could
            # Accept/Start/Ready/Complete/Cancel/Reopen ANY order
            # company-wide, exactly the access the station assignment is
            # supposed to prevent. Only Administrator and
            # company-scoped Branch Manager may legitimately bypass
            # station scope (handled by the two branches above); everyone
            # else with zero station assignments is now explicitly denied.
            if not user.kds_station_ids:
                raise AccessError(
                    _("Your user is not assigned to any FlexSys KDS station. "
                      "Ask an administrator to assign you to a station before "
                      "you can act on order %s.") % order.name
                )
            if not (set(order.station_ids.ids) & set(user.kds_station_ids.ids)):
                raise AccessError(
                    _("You are not assigned to any station involved in order %s.") % order.name)

    # ---------------------------------------------------------------
    # Workflow engine (point 2): every public action funnels through
    # _wf_transition, which enforces ORDER_TRANSITIONS. Edge-case moves
    # in ORDER_OVERRIDE_TRANSITIONS additionally require 'override'.
    # ---------------------------------------------------------------
    def _wf_transition(self, new_state, action, time_field=False, bypass_check=False):
        # Same fix as kds_order_line.py's own _line_transition() - see
        # that method's own detailed comment for the full explanation.
        # bypass_check=True clarified to mean "trusted internal call,
        # operate with a trusted environment" throughout this module,
        # not just at the line level.
        orders = self.sudo() if bypass_check else self
        for order in orders:
            old_state = order.state
            allowed = ORDER_TRANSITIONS.get(old_state, set())
            is_override = (old_state, new_state) in ORDER_OVERRIDE_TRANSITIONS
            if new_state not in allowed and not is_override:
                raise UserError(
                    _("FlexSys KDS: cannot move order %(name)s from '%(old)s' to '%(new)s'.")
                    % {'name': order.name, 'old': old_state, 'new': new_state})
            order._kds_check_order_access(bypass=bypass_check)
            order._kds_check_action('override' if is_override else action, bypass=bypass_check)
            vals = {'state': new_state}
            if time_field:
                vals[time_field] = fields.Datetime.now()
            order.with_context(kds_workflow_write=True).write(vals)
            event_type = 'override' if is_override else 'status_changed'
            order.env['kds.event'].log(
                order, event_type=event_type, old_value=old_state, new_value=new_state)
            notify_stations(order.env, order.station_ids)

    def _force_state(self, new_state, time_field=False):
        """Internal-only helper for the workflow engine to move an order's
        aggregate state as a *side effect* of a line-level action (e.g.
        the order becomes 'preparing' once its first line starts), without
        re-checking user permissions that were already checked for the
        line action that triggered it. Not exposed to the controller.

        Real bug this `time_field` param fixes: unlike _wf_transition()
        (used by the explicit action_accept/action_ready/etc. buttons),
        this side-effect path never stamped the matching Timing-tab
        timestamp - an order that reached 'preparing' purely because a
        line was Started (the normal KDS-screen flow, not the order
        form's own "Start Preparing" button) ended up with a permanently
        blank Preparation Start Time, even though it clearly did start
        preparing at that exact moment.
        """
        for order in self:
            if new_state in ORDER_TRANSITIONS.get(order.state, set()):
                vals = {'state': new_state}
                if time_field and not order[time_field]:
                    vals[time_field] = fields.Datetime.now()
                order.with_context(kds_workflow_write=True).write(vals)

    def action_accept(self, bypass_check=False):
        self._wf_transition('accepted', 'accept', time_field='accepted_time', bypass_check=bypass_check)

    def action_start_preparing(self, bypass_check=False):
        self._wf_transition('preparing', 'start', time_field='preparation_start_time', bypass_check=bypass_check)

    def action_ready(self, bypass_check=False):
        self._wf_transition('ready', 'ready', time_field='ready_time', bypass_check=bypass_check)
        # DESIGN REVERSAL (explicit pilot request, v5.4): v4.1's
        # unconditional auto-complete-on-Ready, then v5.1's gating it
        # behind Expeditor, are both superseded here. Reaching Ready no
        # longer auto-completes at all, even without Expeditor - a live
        # pilot found the auto-complete behavior (even with v5.3's
        # 2-minute grace period) still didn't give staff a reliable
        # window to notice and physically hand off a finished order.
        # Completion is now always a deliberate action - either the
        # Expeditor task's own completion (if enabled), or a manual
        # "Complete" button on the order itself once it reaches Ready
        # (see the new action_complete route wiring in both
        # controllers/kds.py and controllers/kds_kiosk.py). An order now
        # sits at Ready indefinitely - no time limit - until someone
        # actually completes it; only once completed does the (now
        # 10-minute, COMPLETED_GRACE_MINUTES) on-screen grace period
        # apply before it disappears.
        for order in self:
            if order.expeditor_enabled:
                order._activate_expeditor_task(bypass_check=bypass_check)

    def _activate_expeditor_task(self, bypass_check=False):
        """Creates (or reuses, idempotently) the Expeditor/Packing task
        once every production line is Ready. Lazy creation - not up
        front when the order is created - so an order that never
        finishes production, or gets cancelled first, never accumulates
        a meaningless idle task record."""
        self.ensure_one()
        active_task = self.expeditor_task_ids.filtered(lambda t: t.state not in ('cancelled',))
        if active_task:
            # Idempotent: don't create a second task if one's already
            # active (e.g. this got called again without the task ever
            # actually having gone stale in between).
            return active_task
        expeditor_station = self.env['kds.station'].search([
            ('company_id', '=', self.company_id.id),
            ('is_expeditor', '=', True),
            ('active', '=', True),
        ], limit=1)
        if not expeditor_station:
            # expeditor_enabled already confirmed one exists - this is
            # only reachable if it got deactivated in the narrow window
            # between that check and this one. Fail safe: complete
            # normally rather than leaving the order stuck at 'ready'
            # forever with no task and no path forward.
            #
            # REAL BUG FIX, found via a proactive sweep for regressions
            # (not a reported failure): this called the order-level
            # action_complete() directly - correct before BUG-07, but
            # that method now requires is_fully_completed (every line
            # already individually 'completed') via its own guard. This
            # exact call site is reached right after action_ready()'s
            # own flow, when lines are freshly 'ready', never yet
            # individually completed - the guard would have correctly
            # rejected this fail-safe's own call, leaving the order
            # stuck exactly where this code was written to prevent it
            # getting stuck. Fixed by routing through the real, per-line
            # action_complete() (the same one every station's own
            # "Complete" button already calls) instead - its own
            # aggregation then correctly finalizes the order via
            # action_complete() once every line is done, matching how
            # every other completion path in this module already works.
            self.line_ids.filtered(lambda l: l.state != 'cancelled').action_complete(bypass_check=bypass_check)
            return self.env['kds.expeditor.task']
        task = self.env['kds.expeditor.task'].create({
            'order_id': self.id,
            'station_id': expeditor_station.id,
            'available_time': fields.Datetime.now(),
        })
        self.env['kds.event'].log(
            self, event_type='status_changed', station=expeditor_station,
            note=_('Expeditor/Packing task created - all production lines Ready'))
        notify_stations(self.env, expeditor_station)
        return task

    def _reconcile_expeditor_on_production_change(self):
        """DEPRECATED as of the Final Phase 1 Audit fix - kept as a thin
        alias for _system_reopen_if_production_incomplete() below, which
        generalizes this to also cover the case that predates Expeditor
        entirely (an order stuck at Ready/Completed with no Expeditor
        task at all). Existing call sites throughout this module were
        updated to call the new method directly; this alias exists only
        in case something outside this module still references the old
        name."""
        return self._system_reopen_if_production_incomplete()

    def _system_reopen_if_production_incomplete(self, reason=False):
        """Internal-only workflow method (NOT a raw write): if this order
        is sitting at Ready or Completed but production is no longer
        fully ready - a POS Delta Sync added/changed a line, or a
        production line was reopened via override - pulls it back to
        'preparing' through a proper, audited, notified path.

        AUDIT FIX ("POS Delta Sync Still Bypasses The Central Workflow",
        HIGH/FINAL BLOCKER): replaces the previous raw
        `kds_order.write({'state': 'preparing'})` in
        pos_order.py's _flexsys_kds_diff_lines() - that write bypassed
        ORDER_TRANSITIONS validation entirely (ready/completed -> 
        preparing isn't even in the normal allowed set, only reachable
        via the override tier), logged no audit event, sent no
        notification, and never reconciled an active Expeditor task -
        exactly the class of bug this method eliminates by being the one
        authoritative place this specific correction happens.

        Also cancels any active Expeditor/Packing task - a stale task is
        exactly as invalid as a stale order.state once production work
        is active again. This single method now covers both the
        Expeditor-specific case (previously handled by the now-deprecated
        alias above) and the general case that predates Expeditor
        entirely, from every call site: POS Delta Sync (both a changed
        line resetting via
        kds.order.line._system_reset_for_delta_sync(), and a brand new
        line via create()), and a manual line reopen via the override
        path (kds_order_line.py's action_start()).

        AUDIT ENHANCEMENT (dev request "Runtime Regression Fix Package",
        BUG-02B: "Record at minimum: previous state, reopening
        timestamp, modification source, added/updated lines, user/POS
        source"): `reason` lets each call site describe *why* this
        specific reopen happened (a new line arriving, an existing
        line's qty/note changing, a manual override) - folded into the
        audit event's own note alongside the already-captured previous
        state (old_value), reopening timestamp (the event's own
        create_date), and user (the event's own user_id, defaulted to
        self.env.user - correctly reflects the actual POS/system user
        under whose context the sync ran, not a hardcoded value).
        Falls back to a generic description if a call site doesn't pass
        one, rather than requiring every caller to be updated at once.

        Idempotent by construction: a no-op if state is already outside
        ('ready', 'completed'), or if production is genuinely still all
        Ready (order.is_expeditor_ready True) - safe to call
        unconditionally from every relevant hook rather than needing
        each caller to pre-check whether it's actually necessary.
        """
        for order in self:
            if order.state not in ('ready', 'completed'):
                continue
            if order.is_expeditor_ready:
                continue
            old_state = order.state
            order.with_context(kds_workflow_write=True).write({'state': 'preparing'})
            self.env['kds.event'].log(
                order, event_type='status_changed', old_value=old_state, new_value='preparing',
                note=_('Order reopened - production work is active again (%s). '
                       'Previously completed lines retain their own history unchanged.')
                % (reason or _('POS Delta Sync or a production line was reopened')))
            notify_stations(self.env, order.station_ids)
            active_task = order.expeditor_task_ids.filtered(
                lambda t: t.state not in ('cancelled', 'completed'))
            if active_task:
                active_task.action_cancel(bypass_check=True)

    def action_complete(self, bypass_check=False):
        """REAL BUG FIX, confirmed still outstanding on review ("BUG-07 is
        still not implemented as requested" - Kitchen READY -> Kitchen
        COMPLETED while Coffee/Bar stay unaffected, only the *final*
        required station completing should complete the overall order):
        this method itself - independent of which caller reaches it -
        still unconditionally cascaded 'completed' to every non-
        cancelled line across every station in one shot. The KDS
        screens' own "Complete" button was already correctly rewired
        (kds_order_line.py's own action_complete(), a genuine per-line
        action, added specifically for this) to call this method only
        as the tail end of its own is_fully_completed aggregation cascade
        - by which point every line really is already done, so the
        write below was already a harmless no-op in that one path. But
        this order-level method remained independently reachable and
        genuinely destructive from two other places that were never
        updated: the order form's own "Complete" button
        (views/kds_order_views.xml), and controllers/kds.py's own
        order_action route ('complete' in its allowed_actions) - either
        one could still force-complete Coffee's and Bar's still-active
        production the instant Kitchen's own portion finished, exactly
        the bug this was supposed to have already fixed.

        Real fix, at the workflow layer, not a frontend filter: this
        method now refuses to run at all unless is_fully_completed is
        already true - every non-cancelled line across every station
        must have *already*, independently reached 'completed' first.
        That makes every remaining caller correct by construction rather
        than by convention: the line-level aggregation cascade always
        satisfies this (it only calls in after confirming
        is_fully_completed itself), a single-station order's own last
        line reaching Ready-then-Complete naturally satisfies it too,
        and the order form's "Complete" button / the controller's
        'complete' action now correctly refuse - with a clear, honest
        error - to force-complete an order that still has real,
        outstanding production or packing work at another station,
        rather than silently doing it anyway.
        """
        for order in self:
            if not order.is_fully_completed:
                not_done = order.line_ids.filtered(lambda l: l.state not in ('completed', 'cancelled'))
                stations = ', '.join(not_done.mapped('station_id.name')) or _('another station')
                raise UserError(_(
                    "FlexSys KDS: cannot complete order %(name)s yet - %(stations)s still has "
                    "active production. Each station must reach Ready and Complete "
                    "independently; the overall order only completes once every station has."
                ) % {'name': order.name, 'stations': stations})
        self._wf_transition('completed', 'complete', time_field='completion_time', bypass_check=bypass_check)
        self.line_ids.filtered(lambda l: l.state != 'cancelled')\
            .with_context(kds_workflow_write=True).write({'state': 'completed'})

    def _finalize_via_expeditor(self, bypass_check=False):
        """REAL BUG FIX, confirmed live on Odoo.sh (BUG-07 integration
        with Expeditor - "Expeditor completion fails even when
        production is legitimately ready for final packing completion"):
        dedicated, authoritative finalization path for an Expeditor-
        enabled order, called ONLY by
        kds.expeditor.task.action_complete() once the Packing task
        itself has genuinely finished - never called directly from a
        controller or the order form.

        Deliberately distinct from action_complete()'s own guard just
        above (is_fully_completed, which requires every production
        LINE, across every station, to have *individually* reached
        'completed'): that's the correct criterion for the general,
        non-Expeditor station-scoped completion flow this order-level
        guard exists for, but it is the WRONG criterion here. An
        Expeditor-enabled order's production lines are only ever
        expected to reach 'Ready' and stop there - final completion is
        the Packing task's own responsibility, never each individual
        production station's, and "do not force every production
        station line to become COMPLETED merely to satisfy the final
        order guard unless that is the intended lifecycle" (it
        genuinely isn't, for this lifecycle specifically). Uses
        is_expeditor_ready (every non-cancelled line Ready-or-Completed
        - the same criterion the Expeditor task's own action_complete()
        already checks immediately before calling this) as its own
        correct, appropriate criterion instead.

        Still routes through the exact same authoritative
        _wf_transition() as action_complete() above and every other
        transition in this module - full audit trail, notification,
        timestamp - not a second, parallel, unauthoritative mechanism;
        only the *precondition check* differs, matching each lifecycle's
        own actual requirements:

            Production Stations READY
            -> Expeditor/Packing
            -> Expeditor COMPLETED
            -> _finalize_via_expeditor() (this method)
            -> Overall Order COMPLETED

        versus action_complete()'s own (non-Expeditor):

            Station READY -> Station COMPLETE (per station, independently)
            -> action_complete() (once every station has)
            -> Overall Order COMPLETED
        """
        for order in self:
            if not order.expeditor_enabled:
                raise UserError(_(
                    "FlexSys KDS: order %s has no active Expeditor/Packing station - "
                    "use the normal per-station Complete action instead."
                ) % order.name)
            if not order.is_expeditor_ready:
                raise UserError(_(
                    "FlexSys KDS: cannot finalize order %s via Expeditor - a required "
                    "production line is not yet Ready."
                ) % order.name)
        self._wf_transition('completed', 'complete', time_field='completion_time', bypass_check=bypass_check)

    def action_cancel(self, bypass_check=False):
        self._wf_transition('cancelled', 'cancel', time_field='cancelled_at', bypass_check=bypass_check)
        # FIX (audit finding "POS Cancellation Propagation", IMPORTANT -
        # surfaced this same gap in the *existing* manual Cancel button
        # too, not just the new POS-cancellation path below): this used
        # to only move the order itself to 'cancelled', leaving its
        # lines in whatever state they were already in (e.g. a line
        # stuck showing 'preparing' forever on an order that's actually
        # cancelled) - inconsistent, and meant a cancelled order could
        # still show up as "active" on the KDS screens via its lines.
        # Only ACTIVE lines are touched - a line that's already
        # Completed keeps its history rather than being retroactively
        # cancelled, matching "preserve completed/production history".
        # bypass_check=True: the order-level 'cancel' permission was
        # already checked above by _wf_transition - this is a side
        # effect of that already-authorized action, not an independent
        # per-line decision needing its own re-check (same pattern as
        # action_complete's line cascade just below).
        active_lines = self.line_ids.filtered(lambda l: l.state not in ('completed', 'cancelled'))
        for line in active_lines:
            line.action_cancel(reason=_('Order cancelled'), bypass_check=True)
        # AUDIT FIX ("Expeditor/Packing Workflow" point 10, "POS
        # Cancellation" during Packing): same reasoning as the line
        # cascade just above - an active Expeditor/Packing task must not
        # remain a ghost task on a now-cancelled order.
        active_tasks = self.expeditor_task_ids.filtered(lambda t: t.state not in ('cancelled', 'completed'))
        for task in active_tasks:
            task.action_cancel(bypass_check=True)

    def action_hold(self, bypass_check=False):
        self._wf_transition('on_hold', 'hold', bypass_check=bypass_check)

    def action_reopen(self, bypass_check=False):
        self.ensure_one()
        if self.state not in ('ready', 'completed'):
            raise UserError(_("Only Ready or Completed orders can be reopened."))
        self._kds_check_order_access(bypass=bypass_check)
        self._kds_check_action('reopen', bypass=bypass_check)
        old_state = self.state
        self.with_context(kds_workflow_write=True).write({'state': 'preparing'})
        self.env['kds.event'].log(self, event_type='order_reopened',
                                   note=_("Reopened from %s") % old_state)
        notify_stations(self.env, self.station_ids)

    def action_print_full_order(self, bypass_check=False):
        """UI/DATA FIX ("Printing Cleanup & Job History - Final
        Request"), item 3: the same confirmed bug as create_reprint()'s
        own matching fix - this used to create a kds.print.job with
        printer_id=False for any station with no configured/eligible
        printer, silently persisting a permanently unexecutable job.

        Fixed the same way, but per-station rather than raising for the
        whole call: this action can cover several stations (e.g. an
        order routed to both Kitchen and Bar), and one station's own
        missing printer must not prevent printing correctly to every
        OTHER station that does have one configured - the exact same
        principle already established, live and unchanged, in
        pos_order.py's own auto-print path for this same scenario. A
        station with no printer is skipped, with a clear audit-log
        event explaining why, rather than either creating a broken job
        or aborting the whole action.
        """
        self.ensure_one()
        self._kds_check_action('print_full_order', bypass=bypass_check)
        self._kds_check_order_access(bypass=bypass_check)
        for station in self.station_ids:
            printer = station.printer_ids.filtered('is_default')[:1] or station.printer_ids[:1]
            if not printer:
                self.env['kds.event'].log(
                    self, event_type='override', station=station,
                    note=_("Printing unavailable: no printer is configured for "
                           "station '%s' - no print job was created.") % station.name
                )
                continue
            self.env['kds.print.job'].create({
                'order_id': self.id,
                'station_id': station.id,
                'printer_id': printer.id,
                'job_type': 'manual',
                'scope': 'full_order',
            })
