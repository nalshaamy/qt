# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductCategory(models.Model):
    _inherit = 'product.category'

    kds_station_id = fields.Many2one(
        'kds.station', string='Default KDS Station',
        help="Fallback production station for products in this category."
    )
