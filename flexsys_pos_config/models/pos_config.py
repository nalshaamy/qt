# -*- coding: utf-8 -*-
# FLPOS - Adds customer receipt options to each Point of Sale configuration.

from odoo import api, fields, models


class PosConfig(models.Model):
    """Extend POS configuration with customer receipt branding options."""

    _inherit = "pos.config"

    flexsys_hide_powered_by_odoo = fields.Boolean(
        string="Hide Powered by Odoo",
        default=True,
        help="Removes the Powered by Odoo line from the customer receipt.",
    )
    flexsys_receipt_logo = fields.Image(
        string="Customer Receipt Logo",
        attachment=True,
        max_width=600,
        max_height=300,
        help=(
            "A dedicated PNG receipt logo, independent from the company logo. "
            "Odoo automatically resizes it to protect POS loading performance."
        ),
    )

    @api.model
    def _load_pos_data_fields(self, config):
        """Add FLPOS fields to Odoo's standard POS configuration payload.

        The parent field list is always preserved. This is the official Odoo 19
        extension point for adding fields to models loaded by the POS client.
        """
        fields_to_load = list(super()._load_pos_data_fields(config))
        for field_name in (
            "flexsys_hide_powered_by_odoo",
            "flexsys_receipt_logo",
        ):
            if field_name not in fields_to_load:
                fields_to_load.append(field_name)
        return fields_to_load
