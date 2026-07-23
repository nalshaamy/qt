# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    bonat_discount_percentage_product_id = fields.Many2one('product.product',
        string="Bonat Discount Product",
        help="This product will be used as down payment on a sale order.")
