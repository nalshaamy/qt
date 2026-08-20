# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    kds_station_id = fields.Many2one(
        'kds.station', string='Default KDS Station',
        help="Default production station for this product. Overridden by "
             "matching FlexSys KDS routing rules if any."
    )
