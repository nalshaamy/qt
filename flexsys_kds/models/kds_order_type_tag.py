# -*- coding: utf-8 -*-
from odoo import fields, models


class KdsOrderTypeTag(models.Model):
    """A tiny lookup model whose only purpose is letting
    kds.routing.rule.order_type_ids be a proper Many2many (tag picker)
    instead of a single-value Selection - Odoo has no native "pick
    several values from a fixed list" widget backed by a plain Selection
    field, so this is the standard way to get that UX. `kds.order` /
    `kds.order.line` themselves keep the actual order_type as a plain
    Selection field - only the *routing rule's matching criteria* needed
    to become multi-value.
    """
    _name = 'kds.order.type.tag'
    _description = 'FlexSys KDS Order Type (routing tag)'
    _order = 'sequence'

    name = fields.Char(required=True)
    code = fields.Char(required=True, help="Must match a kds.order.order_type selection value.")
    sequence = fields.Integer(default=10)

    # ODOO 19 API MIGRATION: see kds_order.py's own comment on this same
    # change for the full explanation - purely a declaration-syntax
    # change, no behavioral difference.
    _code_uniq = models.Constraint(
        'unique(code)', 'Order type code must be unique.')
