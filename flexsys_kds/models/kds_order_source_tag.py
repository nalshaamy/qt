# -*- coding: utf-8 -*-
from odoo import fields, models


class KdsOrderSourceTag(models.Model):
    """Same idea as kds.order.type.tag, for the 'source' matching
    criterion on routing rules (Odoo POS / QR Order / Web Order / ...)."""
    _name = 'kds.order.source.tag'
    _description = 'FlexSys KDS Order Source (routing tag)'
    _order = 'sequence'

    name = fields.Char(required=True)
    code = fields.Char(required=True, help="Must match a kds.order.source selection value.")
    sequence = fields.Integer(default=10)

    # ODOO 19 API MIGRATION: see kds_order.py's own comment on this same
    # change for the full explanation - purely a declaration-syntax
    # change, no behavioral difference.
    _code_uniq = models.Constraint(
        'unique(code)', 'Order source code must be unique.')
