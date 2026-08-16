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

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Order source code must be unique.'),
    ]
