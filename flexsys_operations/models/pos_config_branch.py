# -*- coding: utf-8 -*-
from odoo import fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    operations_branch_enabled = fields.Boolean(
        string='Available as QR Branch',
        default=False,
    )
    operations_branch_name = fields.Char(
        string='QR Branch Name',
        help='Name shown to customers when choosing a branch.',
    )
    operations_branch_address = fields.Char(
        string='QR Branch Address',
    )
    operations_latitude = fields.Float(
        string='Latitude',
        digits=(10, 7),
    )
    operations_longitude = fields.Float(
        string='Longitude',
        digits=(10, 7),
    )
    operations_branch_is_open = fields.Boolean(
        string='Branch Open',
        default=True,
    )
    operations_branch_closed_message = fields.Char(
        string='Branch Closed Message',
        default='هذا الفرع مغلق حاليًا.',
    )
    operations_max_order_distance_km = fields.Float(
        string='Maximum Order Distance (km)',
        default=15.0,
        help='Maximum delivery distance from this branch. 0 means unlimited.',
    )


    operations_enable_dine_in = fields.Boolean(string='Enable Dine In', default=True)
    operations_enable_takeaway = fields.Boolean(string='Enable Takeaway', default=True)
    operations_enable_car_order = fields.Boolean(string='Enable Car Order', default=True)
    operations_enable_delivery = fields.Boolean(string='Enable Delivery', default=True)

    operations_enable_cash = fields.Boolean(string='Enable Cash Payment', default=True)
    operations_enable_card = fields.Boolean(string='Enable Card Payment', default=True)
    operations_enable_wallet = fields.Boolean(string='Enable Electronic Wallet', default=True)
