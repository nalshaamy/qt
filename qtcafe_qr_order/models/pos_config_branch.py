# -*- coding: utf-8 -*-
from odoo import fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    qtcafe_branch_enabled = fields.Boolean(
        string='Available as QR Branch',
        default=False,
    )
    qtcafe_branch_name = fields.Char(
        string='QR Branch Name',
        help='Name shown to customers when choosing a branch.',
    )
    qtcafe_branch_address = fields.Char(
        string='QR Branch Address',
    )
    qtcafe_latitude = fields.Float(
        string='Latitude',
        digits=(10, 7),
    )
    qtcafe_longitude = fields.Float(
        string='Longitude',
        digits=(10, 7),
    )
    qtcafe_branch_is_open = fields.Boolean(
        string='Branch Open',
        default=True,
    )
    qtcafe_branch_closed_message = fields.Char(
        string='Branch Closed Message',
        default='هذا الفرع مغلق حاليًا.',
    )
    qtcafe_max_order_distance_km = fields.Float(
        string='Maximum Order Distance (km)',
        default=15.0,
        help='Maximum delivery distance from this branch. 0 means unlimited.',
    )


    qtcafe_enable_dine_in = fields.Boolean(string='Enable Dine In', default=True)
    qtcafe_enable_takeaway = fields.Boolean(string='Enable Takeaway', default=True)
    qtcafe_enable_car_order = fields.Boolean(string='Enable Car Order', default=True)
    qtcafe_enable_delivery = fields.Boolean(string='Enable Delivery', default=True)

    qtcafe_enable_cash = fields.Boolean(string='Enable Cash Payment', default=True)
    qtcafe_enable_card = fields.Boolean(string='Enable Card Payment', default=True)
    qtcafe_enable_wallet = fields.Boolean(string='Enable Electronic Wallet', default=True)
