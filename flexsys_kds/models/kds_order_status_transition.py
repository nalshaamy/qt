# -*- coding: utf-8 -*-
from odoo import fields, models


class KdsOrderStatusTransition(models.Model):
    """Which status->status moves are allowed, and at what permission
    tier. Seeded (see data/kds_workflow_status_data.xml) to exactly match
    the current hardcoded LINE_TRANSITIONS/ORDER_TRANSITIONS dicts in
    kds_order_line.py/kds_order.py, plus the two existing
    LINE_OVERRIDE_TRANSITIONS/ORDER_OVERRIDE_TRANSITIONS entries
    (requires_override=True). Not yet read by the actual workflow engine -
    see the docstring on kds.order.status for the phased plan this is
    Phase 1 of.
    """
    _name = 'kds.order.status.transition'
    _description = 'FlexSys KDS Allowed Status Transition'
    _order = 'sequence, id'

    from_status_id = fields.Many2one('kds.order.status', required=True, ondelete='cascade')
    to_status_id = fields.Many2one('kds.order.status', required=True, ondelete='cascade')

    action_code = fields.Char(
        help="Best-effort technical label for which action currently "
             "triggers this transition (e.g. 'accept', 'start', 'ready', "
             "'complete', 'cancel', 'hold') - not yet load-bearing "
             "anywhere; Phase 2 will use this to connect a transition row "
             "to the permission tier it needs "
             "(kds.access.mixin.ACTION_MIN_GROUP) and to the KDS screens' "
             "action buttons. A handful of entries seeded here have no "
             "single current action clearly mapped to them (the original "
             "hardcoded matrix was slightly more permissive than what the "
             "UI actually exercises) - those are left blank rather than "
             "guessed."
    )
    requires_override = fields.Boolean(
        help="Matches an entry in the current "
             "ORDER_OVERRIDE_TRANSITIONS/LINE_OVERRIDE_TRANSITIONS sets - "
             "an edge-case move (e.g. reopening a Completed order) that "
             "needs the Administrator-tier 'override' permission rather "
             "than the normal tier for its action_code."
    )
    applies_to = fields.Selection([
        ('both', 'Order and Line'),
        ('order', 'Order Only'),
        ('line', 'Line Only'),
    ], default='both', required=True,
        help="The current hardcoded matrices are identical for kds.order "
             "and kds.order.line, so 'both' covers everything that exists "
             "today - this field exists so a future customization could "
             "diverge the two without a model change.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('from_to_scope_uniq', 'unique(from_status_id, to_status_id, applies_to)',
         'This exact transition already exists for this scope.'),
    ]
