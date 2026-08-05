# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    operations_default_pos_config_id = fields.Many2one(
        'pos.config',
        string='Default POS for Orders',
        config_parameter='operations_qr_order.default_pos_config_id',
        help='Default POS configuration used when the QR menu is opened without a specific pos_config_id.',
    )


    operations_public_url_prefix = fields.Char(
        string='Public Brand URL Prefix',
        config_parameter='flexsys_operations.public_url_prefix',
        default='brand',
        help='Public customer URL prefix, for example qtcafe, sirat, albaik or barns.',
    )
