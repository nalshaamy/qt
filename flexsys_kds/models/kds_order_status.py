# -*- coding: utf-8 -*-
from odoo import fields, models


class KdsOrderStatus(models.Model):
    """DECISION (audit finding "Configurable Workflow Architecture",
    MEDIUM - explicit direction received): for the first production
    release, the hardcoded Python workflow
    (kds_order.py's ORDER_TRANSITIONS / kds_order_line.py's
    LINE_TRANSITIONS - both extensively tested, 117+ regression tests as
    of this writing) remains the SOLE authoritative runtime workflow.
    Stability was explicitly preferred over configurability for v1.

    This model (and kds.order.status.transition) exist purely as
    inspectable Phase-1-foundation data - seeded to match the hardcoded
    workflow exactly - and are NOT read by the actual workflow engine,
    the KDS screens, or the SLA engine. Editing a record here has
    **zero effect on runtime behavior**. Because settings that look
    functional but silently do nothing are worse than no settings at
    all, the backend menu that exposed this for editing has been
    removed (see views/kds_menus.xml) - the models/data/views
    themselves are left in place rather than deleted, since this is
    real, correct foundation work for a genuine future enhancement, not
    a mistake to undo.

    If a later release decides to actually wire the workflow engine to
    consume these records at runtime, that's a real, larger undertaking
    (rewriting _wf_transition()/_line_transition() to validate against
    kds.order.status.transition instead of the Python dicts; making both
    KDS screens ask the backend for the next valid action instead of
    assuming fixed state names; having the SLA engine key off
    `counts_as_ready` instead of the literal string 'ready'; a full pass
    updating every existing test) - not something to half-do alongside
    other work. Restoring the menu item removed above is the one-line
    signal that decision has actually been made and followed through on,
    not just aspirational.
    """
    _name = 'kds.order.status'
    _description = 'FlexSys KDS Order/Line Status (configurable workflow state)'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(
        required=True,
        help="Stable technical key (e.g. 'preparing'). Used internally to "
             "match this status against the flags below and against "
             "kds.order.status.transition rows - changing it after go-live "
             "on a status other modules/flows depend on is not recommended."
    )
    sequence = fields.Integer(default=10)

    is_initial = fields.Boolean(
        string='Starting Status',
        help="The status a new order/line begins in. Exactly one status "
             "should normally have this set."
    )
    is_terminal = fields.Boolean(
        string='Terminal Status',
        help="No further transitions are expected from this status in "
             "normal flow (e.g. Completed, Cancelled)."
    )
    counts_as_ready = fields.Boolean(
        string='Counts as "Ready" for SLA',
        help="Once a line/order reaches a status with this flag set, the "
             "SLA clock should stop (Phase 3: the SLA engine will read "
             "this instead of hardcoding the literal status 'ready')."
    )
    is_active_state = fields.Boolean(
        string='Counts as Active (shown on KDS screens)',
        default=True,
        help="Whether orders/lines sitting in this status should still "
             "appear on the live KDS screens. Off for terminal end-states "
             "like Completed/Cancelled (Phase 3: the KDS screen queries "
             "will read this instead of hardcoding "
             "state not in ('completed', 'cancelled'))."
    )
    color = fields.Integer(default=0, help="Reserved for a future color-coded status UI.")
    active = fields.Boolean(default=True)

    transition_ids = fields.One2many(
        'kds.order.status.transition', 'from_status_id', string='Outgoing Transitions')

    # ODOO 19 API MIGRATION: see kds_order.py's own comment on this same
    # change for the full explanation - purely a declaration-syntax
    # change, no behavioral difference.
    _code_uniq = models.Constraint(
        'unique(code)', 'Status code must be unique.')
