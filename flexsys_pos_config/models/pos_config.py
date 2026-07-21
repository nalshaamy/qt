# -*- coding: utf-8 -*-
# FLPOS - Adds customer receipt options to each Point of Sale configuration.

from odoo import api, fields, models


class PosConfig(models.Model):
    """Extend POS configuration with dedicated customer receipt branding options."""

    _inherit = "pos.config"

    flexsys_hide_powered_by_odoo = fields.Boolean(
        string="Hide Powered by Odoo",
        default=True,
        help="Removes the Powered by Odoo line from the printed customer receipt.",
    )
    flexsys_receipt_logo = fields.Binary(
        string="Customer Receipt Logo",
        attachment=True,
        help="A dedicated logo printed on the customer receipt independently from the company logo.",
    )

    @api.model
    def _load_pos_data_fields(self, config_id):
        """Load FLPOS receipt settings into the POS frontend configuration data."""
        fields_to_load = super()._load_pos_data_fields(config_id)
        return fields_to_load + [
            "flexsys_hide_powered_by_odoo",
            "flexsys_receipt_logo",
        ]
