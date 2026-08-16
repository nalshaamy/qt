# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .kds_notify import notify_station

# Point 2: real state transition matrix instead of an "accept any state"
# writer. Terminal/edge cases (reopening a Ready/Completed line) require
# the 'override' action permission (Supervisor+) - see kds_access.py.
LINE_TRANSITIONS = {
    'new': {'accepted', 'preparing', 'cancelled', 'on_hold'},
    'accepted': {'preparing', 'cancelled', 'on_hold'},
    'preparing': {'ready', 'cancelled', 'on_hold'},
    'ready': {'completed', 'cancelled'},
    'on_hold': {'new', 'accepted', 'preparing', 'cancelled'},
    'completed': set(),
    'cancelled': set(),
}
LINE_OVERRIDE_TRANSITIONS = {
    ('ready', 'preparing'),
    ('completed', 'preparing'),
}

# SECURITY FIX (audit finding 02, CRITICAL) - same rationale as
# KDS_ORDER_PROTECTED_FIELDS in kds_order.py. station_id is included here
# (unlike on kds.order, which has no directly-writable station field) -
# re-routing a line to a different station is a workflow-significant
# move, not a plain data edit.
KDS_LINE_PROTECTED_FIELDS = {
    'state', 'station_id',
    'station_received_time', 'accepted_time', 'preparation_start_time', 'ready_time',
}


class KdsOrderLine(models.Model):
    _name = 'kds.order.line'
    _inherit = ['kds.access.mixin']
    _description = 'FlexSys KDS Order Line'
    _order = 'sequence, id'

    order_id = fields.Many2one('kds.order', required=True, ondelete='cascade')
    pos_order_line_id = fields.Many2one('pos.order.line', ondelete='set null')
    sequence = fields.Integer(default=10)

    product_id = fields.Many2one('product.product', required=True)
    product_name = fields.Char(related='product_id.display_name', string='Product Name')
    variant_info = fields.Char(
        string='Variant / Attributes',
        help="Selected variant/attribute description for this line (size, "
             "flavor, etc.), captured from the POS line separately from the "
             "free-text customer note."
    )
    qty = fields.Float(default=1.0)
    note = fields.Char(string='Modifiers / Notes')

    station_id = fields.Many2one('kds.station', string='Station')
    company_id = fields.Many2one(related='order_id.company_id', store=True)
    priority = fields.Selection(related='order_id.priority', store=True)

    state = fields.Selection([
        ('new', 'New'),
        ('accepted', 'Accepted'),
        ('preparing', 'Preparing'),
        ('ready', 'Ready'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('on_hold', 'On Hold'),
    ], string='Status', default='new', required=True)

    line_change = fields.Selection([
        ('none', 'None'),
        ('added', 'Added'),
        ('updated', 'Updated'),
        ('removed', 'Removed'),
    ], default='none', string='Post-send Change')

    station_received_time = fields.Datetime()
    # REAL BUG FIX, confirmed live (Odoo Server Error: "Invalid field
    # 'accepted_time' in 'kds.order.line'" during actual POS payment):
    # this field was referenced extensively throughout this file
    # (KDS_LINE_PROTECTED_FIELDS, action_accept()'s extra_vals,
    # _system_reset_for_delta_sync()'s timestamp reset) but never
    # actually declared on the model itself - a real gap that static
    # checks (py_compile, XML well-formedness) can never catch, since
    # nothing about referencing an undeclared field name in a Python
    # dict/string is a syntax error. Only a live Odoo instance loading
    # the model registry and validating field names against it could
    # ever surface this - exactly what happened here.
    accepted_time = fields.Datetime()
    preparation_start_time = fields.Datetime()
    ready_time = fields.Datetime()
    prep_duration = fields.Float(string='Prep Duration (min)', compute='_compute_prep_duration', store=True)

    sla_status = fields.Selection([
        ('normal', 'Normal'),
        ('warning', 'Warning'),
        ('late', 'Late'),
    ], compute='_compute_sla_status')

    cancel_reason = fields.Char()
    cancelled_by = fields.Many2one('res.users')
    cancelled_at = fields.Datetime()

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        for line in lines:
            # Routing/arrival initialization right after create() - always
            # a trusted system flow (this is how every line gets routed
            # and timestamped in the first place), so it explicitly marks
            # itself as such rather than depending on the calling context
            # already being sudo'd.
            line = line.with_context(kds_workflow_write=True)
            if not line.station_id:
                station = self.env['kds.routing.rule'].route_product(
                    line.product_id,
                    order_type=line.order_id.order_type,
                    source=line.order_id.source,
                    pos_config=line.order_id.pos_config_id,
                    company=line.order_id.company_id,
                )
                if station:
                    line.station_id = station.id
            line.station_received_time = fields.Datetime.now()
            self.env['kds.event'].log(
                line.order_id, event_type='order_routed', station=line.station_id,
                note=_("%(qty)s x %(product)s -> %(station)s") % {
                    'qty': line.qty, 'product': line.product_id.display_name,
                    'station': line.station_id.name if line.station_id else _('UNROUTED')})
            notify_station(self.env, line.station_id)
            # AUDIT FIX ("Auto Accept", MEDIUM): runtime behavior for
            # kds.station.auto_accept_orders, which existed as a
            # configuration field with no actual effect until now. Goes
            # through the real action_accept()/action_start() workflow
            # methods (never a direct write) so it gets everything those
            # methods already provide for free - timestamps, audit
            # events, realtime notifications, and transition validation
            # (New->Accepted->Preparing is always legal, so this never
            # raises) - keeping exactly one authoritative answer to "how
            # does a line's state change", not a second ad-hoc
            # implementation for the auto path.
            #
            # REAL BUG FIX, confirmed at runtime (dev request "Runtime
            # Regression Fix Package", BUG-01): this used to call only
            # action_accept(), landing the line at 'accepted' and
            # stopping there - but 'accepted' and 'new' are treated as
            # equivalent everywhere else in this module (the NEW tab
            # groups both together - see v5.2.2's own fix - and both
            # show the same "START" button, since _lineNextAction/
            # lineNextAction on both KDS screens map 'new' and 'accepted'
            # to the identical next action). The ticket looked completely
            # unaffected by Auto Accept - still under NEW, still showing
            # START - even though the field had technically done
            # something. The dev request's own acceptance test settles
            # what "Auto Accept" is actually supposed to mean
            # operationally: NEW -> PREPARING with no manual click at
            # all, not NEW -> a second sub-state that behaves identically
            # to NEW. Chained through to action_start() too, so Auto
            # Accept now lands a line exactly where the request expects.
            # Checked per-line against THAT line's own station, so a
            # multi-station order with mixed Auto Accept settings
            # correctly auto-advances only the lines routed to a station
            # that has it enabled.
            if line.station_id and line.station_id.auto_accept_orders:
                line.action_accept(bypass_check=True)
                line.action_start(bypass_check=True)
            # AUDIT FIX ("POS Delta Sync..." HIGH/FINAL BLOCKER +
            # "Expeditor/Packing Workflow" point 9, "POS Delta Updates"):
            # a new production line arriving after the order was already
            # Ready/Completed (with or without Expeditor involved) must
            # pull it back and invalidate any stale Expeditor task -
            # "Packing readiness must be recalculated... must not
            # finalize the old Packing task while new production work is
            # pending." Called unconditionally now (previously gated on
            # `if line.order_id.expeditor_task_ids`, which meant a
            # non-Expeditor order never got reopened at all for this
            # exact scenario) - the method's own internal early-return
            # makes this a cheap no-op for the overwhelming common case.
            line.order_id._system_reopen_if_production_incomplete(
                reason=_('new item "%s" added after order was already Ready/Completed') % line.product_name)
        return lines

    def write(self, vals):
        # SECURITY FIX (audit finding 02, CRITICAL) - see
        # KDS_LINE_PROTECTED_FIELDS above for the full rationale.
        touched = KDS_LINE_PROTECTED_FIELDS & set(vals.keys())
        if touched and not self.env.context.get('kds_workflow_write') and not self.env.su:
            raise AccessError(_(
                "FlexSys KDS: %s cannot be changed by writing directly - use the "
                "Accept/Start/Ready/Cancel/Hold actions instead."
            ) % ', '.join(sorted(touched)))
        return super().write(vals)

    @api.depends('preparation_start_time', 'ready_time')
    def _compute_prep_duration(self):
        for line in self:
            if line.preparation_start_time and line.ready_time:
                delta = line.ready_time - line.preparation_start_time
                line.prep_duration = round(delta.total_seconds() / 60.0, 1)
            else:
                line.prep_duration = 0.0

    @api.depends('station_received_time', 'ready_time', 'state', 'station_id.target_prep_time',
                 'station_id.warning_threshold_pct', 'station_id.late_threshold_pct')
    def _compute_sla_status(self):
        # Point requested: SLA clock starts the moment the line arrives at
        # the station (station_received_time, stamped at create() while
        # the line is still 'new' - i.e. before anyone has even accepted
        # or started it, since a ticket sitting unclaimed in the queue is
        # exactly the kind of delay this should catch) and stops the
        # moment it's marked Ready (ready_time) - not preparation_start,
        # which only measured active cook time and ignored queue time.
        now = fields.Datetime.now()
        for line in self:
            target = line.station_id.target_prep_time or 10
            warn_pct = (line.station_id.warning_threshold_pct or 80) / 100.0
            late_pct = (line.station_id.late_threshold_pct or 100) / 100.0
            start = line.station_received_time
            if not start:
                line.sla_status = 'normal'
                continue
            if line.state in ('ready', 'completed'):
                # Clock stops at Ready - a line that finished on time stays
                # "on time" forever after, it doesn't drift into Late just
                # because it's sitting in the Ready column waiting for
                # Packing/pickup.
                end = line.ready_time or now
                elapsed = (end - start).total_seconds() / 60.0
            elif line.state == 'cancelled':
                elapsed = 0.0
            else:
                elapsed = (now - start).total_seconds() / 60.0
            if elapsed >= target * late_pct:
                line.sla_status = 'late'
            elif elapsed >= target * warn_pct:
                line.sla_status = 'warning'
            else:
                line.sla_status = 'normal'

    # ---------------------------------------------------------------
    # Workflow engine: every transition goes through _line_transition,
    # which enforces LINE_TRANSITIONS and, for edge-case transitions in
    # LINE_OVERRIDE_TRANSITIONS, requires the 'override' permission.
    # ---------------------------------------------------------------
    def _line_transition(self, new_state, action, extra_vals=None, bypass_check=False):
        # REAL BUG FIX, confirmed live on Odoo.sh: bypass_check=True is
        # meant to represent a trusted internal/system call (POS Delta
        # Sync, Auto Accept, etc.) that has no station or interactive
        # user permissions of its own to be scoped by - but this method
        # used to still operate on `self` exactly as the caller passed
        # it in, meaning even a bypass_check=True call still hit the
        # calling user's own station-scoped Record Rules the moment it
        # tried to just READ line.state, before bypass_check's own
        # meaning (skip the KDS action/station permission tier) was ever
        # consulted. Clarifying the contract precisely, per explicit
        # instruction: bypass_check=True now switches the actual
        # transition work onto a sudo'd recordset - not a weakening of
        # normal Operator Record Rules (those still apply exactly as
        # before to every bypass_check=False call, which is every
        # interactive user action reachable from either KDS screen - see
        # controllers/kds.py, which never passes bypass_check at all),
        # but the concrete, correct meaning of "trusted internal call":
        # it must be able to act on data outside the calling context's
        # own row-level visibility, the same way _flexsys_kds_diff_lines()
        # and other internal flows already run under self.sudo() at
        # their own call site. bypass_check remains unreachable from any
        # controller route, so it can't be abused externally regardless.
        lines = self.sudo() if bypass_check else self
        for line in lines:
            old_state = line.state
            allowed = LINE_TRANSITIONS.get(old_state, set())
            is_override = (old_state, new_state) in LINE_OVERRIDE_TRANSITIONS
            if new_state not in allowed and not is_override:
                raise UserError(
                    _("FlexSys KDS: cannot move line '%(product)s' from '%(old)s' to '%(new)s'.")
                    % {'product': line.product_name, 'old': old_state, 'new': new_state}
                )
            action_to_check = 'override' if is_override else action
            line._kds_check_action(action_to_check, station=line.station_id, bypass=bypass_check)
            vals = dict(extra_vals or {})
            vals['state'] = new_state
            line.with_context(kds_workflow_write=True).write(vals)
            # AUDIT FIX ("State Transition Consistency", MEDIUM): this
            # used to only log an event for override transitions - a real
            # inconsistency with the order-level _wf_transition (in
            # kds_order.py), which has always logged unconditionally for
            # every transition. A normal line move (e.g. plain
            # New->Accepted) previously left no audit trail at all,
            # unlike the same move at the order level. Now matches the
            # order-level pattern exactly: every transition is logged,
            # override or not.
            event_type = 'override' if is_override else 'status_changed'
            line.env['kds.event'].log(
                line.order_id, event_type=event_type, station=line.station_id,
                old_value=old_state, new_value=new_state,
                note=_('Manual override (line)') if is_override else False)
            notify_station(line.env, line.station_id)

    def action_accept(self, bypass_check=False):
        # BUG FIX (found while implementing "Auto Accept", MEDIUM):
        # unlike action_start()/action_ready() just below, this never
        # passed extra_vals - accepted_time was never actually stamped
        # by a line-level accept, only by the order-level one
        # (kds_order.py's action_accept, via _wf_transition's
        # time_field= parameter). A manually-accepted line's own
        # Accepted timestamp was silently always blank.
        self._line_transition(
            'accepted', 'accept',
            extra_vals={'accepted_time': fields.Datetime.now()},
            bypass_check=bypass_check,
        )

    def action_start(self, bypass_check=False):
        self._line_transition(
            'preparing', 'start',
            extra_vals={'preparation_start_time': fields.Datetime.now()},
            bypass_check=bypass_check,
        )
        for line in self:
            # REAL BUG FIX, confirmed live on Odoo.sh
            # (test_auto_accept_creates_exactly_one_audit_event, "2 != 1"):
            # this used to call the FULL order.action_accept() here -
            # which goes through _wf_transition() and logs its own
            # 'accepted' audit event, a *second* one alongside the
            # line-level 'accepted' event action_accept() (the line-level
            # method) already logged moments earlier for the exact same
            # conceptual "this got accepted" moment - not two genuinely
            # separate transitions, just one line-level action whose
            # order-level state bump is purely a mechanical side effect.
            # Fixed by switching to _force_state() - the exact same
            # silent, no-log, no-permission-recheck internal helper
            # already used for the 'preparing' bump right below this
            # (added specifically for "a side effect of a line-level
            # action... without re-checking permissions that were
            # already checked for the line action that triggered it" -
            # the identical reasoning applies here). One authoritative
            # writer per transition: the line-level action_accept() call
            # (from either a manual Accept click or Auto Accept) is that
            # one writer; this cascade only needs to mechanically move
            # the order's own aggregate state and stamp its timestamp,
            # never log a second, redundant event for what a human or
            # Auto Accept already caused and already got logged once.
            if line.order_id.state == 'new':
                line.order_id._force_state('accepted', time_field='accepted_time')
            if line.order_id.state in ('new', 'accepted'):
                line.order_id._force_state('preparing', time_field='preparation_start_time')
            self.env['kds.event'].log(line.order_id, event_type='preparation_started', station=line.station_id)
            # AUDIT FIX ("Expeditor/Packing Workflow" point 8, "Reopened
            # Production Lines" + "POS Delta Sync..." HIGH/FINAL
            # BLOCKER's general-case fix): this method is also how a
            # Ready/Completed line gets reopened back to Preparing (the
            # override path, LINE_OVERRIDE_TRANSITIONS) - "Packing must
            # no longer be considered ready for final completion while a
            # required production line has returned to Preparing." Called
            # unconditionally now, same reasoning as the create() hook
            # above - the order must be pulled back even with no
            # Expeditor task involved, not just when one exists.
            line.order_id._system_reopen_if_production_incomplete(
                reason=_('line "%s" manually reopened back to Preparing') % line.product_name)

    def action_ready(self, bypass_check=False):
        self._line_transition(
            'ready', 'ready', extra_vals={'ready_time': fields.Datetime.now()},
            bypass_check=bypass_check,
        )
        # REAL BUG FIX, confirmed live on Odoo.sh: calling action_ready()
        # on a MULTI-LINE recordset (e.g. kds_order.line_ids.action_ready()
        # for a 2+ line order - a realistic "mark everything ready at
        # once" usage, not just a test artifact) used to call
        # order.action_ready() once PER LINE, not once per distinct
        # order. _line_transition above already writes every line's own
        # state to 'ready' before this runs - so by the time the SECOND
        # line in this loop checks is_expeditor_ready, it's already True
        # (every line just got written to 'ready'), and its own call to
        # order.action_ready() tried an invalid 'ready' -> 'ready' self-
        # transition (the order was already moved to 'ready' by the
        # FIRST line's own iteration), raising a UserError -
        # "cannot move order ... from 'ready' to 'ready'." Fixed by
        # de-duplicating to each *distinct* order touched, calling
        # action_ready() on it exactly once regardless of how many of
        # its own lines are in this batch.
        orders_to_advance = self.env['kds.order']
        for line in self:
            self.env['kds.event'].log(line.order_id, event_type='line_ready', station=line.station_id)
            if line.order_id.is_expeditor_ready and line.order_id.state not in ('ready', 'completed'):
                orders_to_advance |= line.order_id
        orders_to_advance.action_ready(bypass_check=bypass_check)

    def _system_reset_for_delta_sync(self, new_state='new'):
        """Internal-only workflow method (NOT a raw write) for POS Delta
        Sync to safely move a line that's already progressed (e.g.
        Ready) back to an earlier state because the underlying POS line's
        qty/note/variant changed underneath it.

        AUDIT FIX ("POS Delta Sync Still Bypasses The Central Workflow",
        HIGH/FINAL BLOCKER): replaces the previous raw
        `kline.write({..., 'state': new_state})` in
        pos_order.py's _flexsys_kds_diff_lines(). Deliberately NOT routed
        through _line_transition()/LINE_TRANSITIONS - "roll back to New"
        isn't a user-facing action at all (no button anywhere calls this;
        it's only ever an automatic system reaction to the POS order's
        own content changing), so it doesn't belong in the same matrix
        that governs an operator's own accept/start/ready/cancel taps.
        It still goes through the same event/notification/timestamp
        discipline every other transition in this module does - exactly
        what was missing from the raw write.

        Timestamps ahead of `new_state` are cleared (e.g. resetting to
        'new' clears accepted_time/preparation_start_time/ready_time),
        satisfying "correct timestamp reset/recalculation" - the line is
        genuinely restarting its journey from that point, so a stale
        earlier timestamp would misrepresent when it actually reached
        each stage this time around.

        Guards already existed at the pos_order.py call site before this
        fix (never called for a completed/cancelled line) - kept here
        too as a defense-in-depth no-op, since completed/cancelled work
        must never be silently reset regardless of caller discipline.
        """
        for line in self:
            if line.state in ('completed', 'cancelled') or line.state == new_state:
                continue
            old_state = line.state
            vals = {'state': new_state}
            if new_state == 'new':
                vals.update({'accepted_time': False, 'preparation_start_time': False, 'ready_time': False})
            elif new_state == 'accepted':
                vals.update({'preparation_start_time': False, 'ready_time': False})
            elif new_state == 'preparing':
                vals.update({'ready_time': False})
            line.with_context(kds_workflow_write=True).write(vals)
            self.env['kds.event'].log(
                line.order_id, event_type='status_changed', station=line.station_id,
                old_value=old_state, new_value=new_state,
                note=_('POS Delta Sync: line reset - underlying POS order content changed'))
            notify_station(self.env, line.station_id)
        # Reconcile the parent order (and any active Expeditor task) now
        # that a line moved backward - same centralized method used for
        # a manual line reopen and for new lines arriving via delta sync.
        self.mapped('order_id')._system_reopen_if_production_incomplete(
            reason=_('existing item(s) modified via POS Delta Sync: %s') % ', '.join(self.mapped('product_name')))

    def action_cancel(self, reason=False, bypass_check=False):
        for line in self:
            if line.state in ('completed', 'cancelled'):
                raise UserError(
                    _("FlexSys KDS: cannot cancel line '%(product)s' (already %(state)s).")
                    % {'product': line.product_name, 'state': line.state})
            line._kds_check_action('cancel', station=line.station_id, bypass=bypass_check)
            # AUDIT FIX (dev request "Cancellation Visibility Improvement",
            # point 4: "Previous state" explicitly required in the trail):
            # captured before the write below - by the time log() ran
            # previously, line.state already reflected the NEW value
            # ('cancelled'), so the transition's own starting point was
            # never actually recorded anywhere, unlike the equivalent
            # order-level event (_wf_transition already does this
            # correctly). Note also now embeds product/qty explicitly
            # ("Product/Line", "Original quantity") - kds.event has no
            # dedicated line_id/qty field of its own (a station-scoped
            # audit event, not a per-line one), so this is the direct way
            # to satisfy that requirement without a schema change; the
            # line record itself (order_id.line_ids), its qty, and this
            # event's own old_value/new_value/timestamp/user_id together
            # already cover the rest of the requested fields.
            previous_state = line.state
            line.with_context(kds_workflow_write=True).write({
                'state': 'cancelled',
                'cancel_reason': reason,
                'cancelled_by': self.env.user.id,
                'cancelled_at': fields.Datetime.now(),
                'line_change': 'removed',
            })
            self.env['kds.event'].log(
                line.order_id, event_type='line_removed', station=line.station_id,
                old_value=previous_state, new_value='cancelled',
                note=_("Cancelled: %(qty)s x %(product)s - %(reason)s") % {
                    'qty': line.qty,
                    'product': line.product_name,
                    'reason': reason or _('no reason given'),
                })
            notify_station(self.env, line.station_id)

    def action_move_station(self, new_station_id, bypass_check=False):
        new_station = self.env['kds.station'].browse(new_station_id)
        for line in self:
            line._kds_check_action('move_station', station=line.station_id, bypass=bypass_check)
            line._kds_check_action('move_station', station=new_station, bypass=bypass_check)
            old_station = line.station_id
            line.with_context(kds_workflow_write=True).write({'station_id': new_station.id})
            self.env['kds.event'].log(
                line.order_id, event_type='station_moved',
                old_value=old_station.name, new_value=new_station.name)
            notify_station(self.env, old_station)
            notify_station(self.env, new_station)
