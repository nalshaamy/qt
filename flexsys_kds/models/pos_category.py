# -*- coding: utf-8 -*-
from odoo import fields, models


class PosCategory(models.Model):
    _inherit = 'pos.category'

    kds_station_id = fields.Many2one(
        'kds.station', string='Default KDS Station',
        help="Fallback production station for products in this POS category, "
             "used when no FlexSys KDS routing rule matches. This is the "
             "category cashiers/staff actually organize products under in "
             "the POS - usually the right place to set a default, rather "
             "than the internal inventory category."
    )
