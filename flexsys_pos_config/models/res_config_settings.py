# -*- coding: utf-8 -*-
# FLPOS - Exposes receipt options inside Point of Sale general settings.

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    """Expose the selected POS configuration receipt options in Odoo settings."""

    _inherit = "res.config.settings"

    flexsys_hide_powered_by_odoo = fields.Boolean(
        related="pos_config_id.flexsys_hide_powered_by_odoo",
        readonly=False,
        string="Hide Powered by Odoo",
    )
    flexsys_receipt_logo = fields.Binary(
        related="pos_config_id.flexsys_receipt_logo",
        readonly=False,
        string="Customer Receipt Logo",
    )
