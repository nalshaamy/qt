# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .kds_notify import notify_station

# Mirrors the naming style of ORDER_TRANSITIONS/LINE_TRANSITIONS in
# kds_order.py/kds_order_line.py - same centralized-workflow principle,
# a separate small matrix rather than a shared one, since Expeditor's
# own lifecycle is conceptually its own stage (assembly/handoff), not
# just another production station reusing the same states.
EXPEDITOR_TRANSITIONS = {
    'waiting': {'packing', 'cancelled'},
    'packing': {'ready', 'cancelled'},
    'ready': {'completed', 'cancelled'},
    'completed': set(),
    'cancelled': set(),
}
# Reopening a Ready/Completed packing task back to Packing - same
# override-permission principle as ORDER_OVERRIDE_TRANSITIONS/
# LINE_OVERRIDE_TRANSITIONS.
EXPEDITOR_OVERRIDE_TRANSITIONS = {
    ('ready', 'packing'),
    ('completed', 'packing'),
}


class KdsExpeditorTask(models.Model):
    """The Expeditor/Packing stage as a real, independently-tracked
    operational task - audit finding "Expeditor/Packing Workflow"
    (the final Phase 1 item). Deliberately NOT just a boolean flag on
    kds.order: this model has its own state, responsible user, and
    timestamps, exactly so Packing Time can be measured separately from
    Production Time (see `packing_duration` below) rather than the two
    being blended together.

    One (at most one *active*, i.e. non-cancelled) task per order,
    created lazily - only once every production line is actually Ready
    (kds.order.is_expeditor_ready), not up front when the order is
    created - so an order that never finishes production, or gets
    cancelled first, never accumulates an idle, meaningless task record.

    Does NOT participate in product routing at all - kds.routing.rule
    only ever targets production stations (kds.station records with
    is_expeditor=False); this model exists specifically so the
    Burger/Coffee/etc. lines are never duplicated or re-routed through
    the expeditor station, matching "Do Not Duplicate Product Routing".
    """
    _name = 'kds.expeditor.task'
    _inherit = ['kds.access.mixin']
    _description = 'FlexSys KDS Expeditor / Packing Task'
    _order = 'id desc'

    order_id = fields.Many2one('kds.order', required=True, ondelete='cascade', index=True)
    station_id = fields.Many2one(
        'kds.station', required=True, string='Expeditor Station', ondelete='restrict')
    company_id = fields.Many2one(related='order_id.company_id', store=True)

    state = fields.Selection([
        ('waiting', 'Waiting'),
        ('packing', 'Packing'),
        ('ready', 'Ready'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='waiting', required=True)

    user_id = fields.Many2one(
        'res.users', string='Responsible User',
        help="Set when someone actually starts packing (action_start), "
             "not at task creation - a task can sit in 'Waiting' with no "
             "one assigned yet.")

    # FINAL PHASE 1 AUDIT FIX (finding 3, DOCUMENTATION): "Please document
    # the distinction explicitly: Packing Wait + Work Time = Packing SLA
    # elapsed time. Actual active packing work = Packing Duration. This
    # will prevent Analytics from treating the two metrics as
    # equivalent." Documented here on the fields themselves (not just in
    # a prose doc elsewhere) so anyone querying/reporting on this model
    # sees the distinction at the point of use.
    available_time = fields.Datetime(
        string='Available Since',
        help="When every production line became Ready - i.e. when this "
             "task was created. This is the START of the Packing SLA "
             "clock (see sla_status below), which is DIFFERENT from "
             "Packing Duration (which starts later, at start_time - see "
             "below). Production Time (kds.order's own created_time -> "
             "this field) is measured independently of both.")
    start_time = fields.Datetime(
        string='Packing Start Time',
        help="When someone actually began packing - this is where "
             "Packing DURATION starts counting (see packing_duration "
             "below), which is *after* available_time, not the same "
             "instant - there's normally a wait between an order "
             "becoming Available and someone actually picking it up.")
    ready_time = fields.Datetime(string='Packing Ready Time')
    completion_time = fields.Datetime()

    packing_duration = fields.Float(
        compute='_compute_packing_duration', store=True,
        string='Packing Duration (min)',
        help="ACTIVE PACKING WORK ONLY: start_time -> ready_time. This is "
             "NOT the same measurement as Packing SLA (sla_status below), "
             "which also includes the wait between the order becoming "
             "Available and someone actually starting to pack it. "
             "Formula: Packing Wait Time + Packing Duration = Packing SLA "
             "elapsed time. Kept deliberately separate from "
             "kds.order.line's own prep_duration (Production Time) too, "
             "so Analytics can distinguish all three rather than one "
             "blended fulfillment number: Production Time, Packing Wait "
             "Time, and Packing Duration (active work).")

    sla_status = fields.Selection([
        ('normal', 'Normal'),
        ('warning', 'Warning'),
        ('late', 'Late'),
    ], compute='_compute_sla_status', string='Packing SLA',
        help="WAIT + WORK TIME COMBINED: measured from available_time "
             "(the order became Available for packing) through to "
             "ready_time (or now, if still open) - this INCLUDES any time "
             "the order sat waiting before someone started packing it, "
             "unlike packing_duration above (active work only, starting "
             "from start_time). Formula: Packing Wait Time + Packing "
             "Duration = Packing SLA elapsed time. Treating this and "
             "packing_duration as interchangeable in a report would "
             "understate how long an order actually sat waiting for "
             "packing to begin.")

    active = fields.Boolean(default=True)

    @api.depends('start_time', 'ready_time')
    def _compute_packing_duration(self):
        for task in self:
            if task.start_time and task.ready_time:
                delta = task.ready_time - task.start_time
                task.packing_duration = round(delta.total_seconds() / 60.0, 1)
            else:
                task.packing_duration = 0.0

    @api.depends('available_time', 'ready_time', 'state', 'station_id.target_prep_time',
                 'station_id.warning_threshold_pct', 'station_id.late_threshold_pct')
    def _compute_sla_status(self):
        # Deliberately its own computation, not reusing
        # kds.order.line._compute_sla_status - Packing SLA must never get
        # blended with Kitchen/Bar/Coffee production SLA (audit finding
        # "Expeditor SLA": "Do not mix Packing SLA with Kitchen/Bar
        # preparation SLA"). Same target/threshold fields on kds.station
        # are reused rather than duplicated onto this model, since the
        # expeditor station is still a kds.station and already has its
        # own SLA configuration (and its own validation constraint from
        # the "SLA Validation" fix).
        now = fields.Datetime.now()
        for task in self:
            target = task.station_id.target_prep_time or 10
            warn_pct = (task.station_id.warning_threshold_pct or 80) / 100.0
            late_pct = (task.station_id.late_threshold_pct or 100) / 100.0
            start = task.available_time
            if not start:
                task.sla_status = 'normal'
                continue
            if task.state in ('ready', 'completed'):
                end = task.ready_time or now
                elapsed = (end - start).total_seconds() / 60.0
            elif task.state == 'cancelled':
                elapsed = 0.0
            else:
                elapsed = (now - start).total_seconds() / 60.0
            if elapsed >= target * late_pct:
                task.sla_status = 'late'
            elif elapsed >= target * warn_pct:
                task.sla_status = 'warning'
            else:
                task.sla_status = 'normal'

    # ---------------------------------------------------------------
    # Workflow - same centralized-transition principle as kds.order/
    # kds.order.line (audit finding "State Transition Consistency"
    # applies here too, not just to the two existing models).
    # _kds_check_action() itself is inherited from kds.access.mixin -
    # reuses the same action-tier map (ACTION_MIN_GROUP in
    # kds_access.py) as production stations, so Expeditor doesn't need
    # its own separate permission matrix: "start"/"ready"/"complete"/
    # "cancel"/"override" already exist there with sensible tiers.
    # ---------------------------------------------------------------
    def _transition(self, new_state, action, extra_vals=None, bypass_check=False):
        # Same fix as kds_order_line.py's own _line_transition() (and
        # kds_order.py's _wf_transition()) - see that method's own
        # detailed comment for the full explanation. bypass_check=True
        # means "trusted internal call, operate with a trusted
        # environment" consistently across every workflow model in this
        # module, not just the two most common ones.
        tasks = self.sudo() if bypass_check else self
        for task in tasks:
            old_state = task.state
            allowed = EXPEDITOR_TRANSITIONS.get(old_state, set())
            is_override = (old_state, new_state) in EXPEDITOR_OVERRIDE_TRANSITIONS
            if new_state not in allowed and not is_override:
                raise UserError(_(
                    "FlexSys KDS: cannot move the Expeditor/Packing task for order "
                    "%(order)s from '%(old)s' to '%(new)s'."
                ) % {'order': task.order_id.name, 'old': old_state, 'new': new_state})
            task._kds_check_action('override' if is_override else action, station=task.station_id, bypass=bypass_check)
            vals = dict(extra_vals or {})
            vals['state'] = new_state
            task.with_context(kds_workflow_write=True).write(vals)
            event_type = 'override' if is_override else 'status_changed'
            task.env['kds.event'].log(
                task.order_id, event_type=event_type, station=task.station_id,
                old_value='expeditor_%s' % old_state, new_value='expeditor_%s' % new_state,
                note=_('Expeditor/Packing') if not is_override else _('Expeditor/Packing override'))
            notify_station(task.env, task.station_id)

    def action_start(self, bypass_check=False):
        self._transition('packing', 'start',
                          extra_vals={'start_time': fields.Datetime.now(), 'user_id': self.env.uid},
                          bypass_check=bypass_check)

    def action_ready(self, bypass_check=False):
        self._transition('ready', 'ready', extra_vals={'ready_time': fields.Datetime.now()},
                          bypass_check=bypass_check)

    def action_complete(self, bypass_check=False):
        # AUDIT FIX ("Expeditor Completion Safety Check", MEDIUM/FINAL
        # VERIFICATION): a server-side guard, checked at the moment of
        # completion itself - not relying on the UI already being
        # correct, and not relying only on the earlier reconciliation
        # done when a production line reopens
        # (_system_reopen_if_production_incomplete, which already
        # cancels this exact task when that happens - but a race is still
        # possible: a line could reopen in the narrow window *between*
        # that reconciliation and this specific completion request being
        # processed, e.g. two concurrent requests, or a stale UI that
        # already had this task's Ready state loaded before the line
        # reopened elsewhere). Checked before the transition, not after -
        # a stale/concurrent request must be rejected outright, not
        # allowed to complete and then get silently corrected.
        for task in self:
            if not task.order_id.is_expeditor_ready:
                raise UserError(_(
                    "FlexSys KDS: cannot complete the Expeditor/Packing task for order "
                    "%s - a required production line is no longer Ready. Refresh and "
                    "try again once production is complete."
                ) % task.order_id.name)
        self._transition('completed', 'complete', extra_vals={'completion_time': fields.Datetime.now()},
                          bypass_check=bypass_check)
        for task in self:
            task.order_id.action_complete(bypass_check=True)

    def action_cancel(self, bypass_check=False):
        self._transition('cancelled', 'cancel', bypass_check=bypass_check)
