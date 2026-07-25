# -*- coding: utf-8 -*-
# FLPOS - Point of Sale configuration fields.

from odoo import api, fields, models


class PosConfig(models.Model):
    """Store FLPOS options separately for every Point of Sale configuration."""

    _inherit = "pos.config"

    # Receipt configuration
    flexsys_enable_custom_receipt_logo = fields.Boolean(
        string="Enable Custom Receipt Logo",
        default=True,
        help="Enable the dedicated FLPOS logo on customer receipts.",
    )
    flexsys_receipt_logo = fields.Image(
        string="Customer Receipt Logo",
        attachment=True,
        max_width=600,
        max_height=300,
        help=(
            "A dedicated receipt logo independent from the company logo. "
            "Odoo resizes it automatically to protect POS performance."
        ),
    )
    flexsys_has_receipt_logo = fields.Boolean(
        string="Has Customer Receipt Logo",
        compute="_compute_flexsys_has_receipt_logo",
        store=True,
        help="Technical flag used by the POS receipt without loading the image binary.",
    )
    flexsys_hide_company_logo = fields.Boolean(
        string="Hide Company Logo",
        default=True,
        help="Hide the standard company logo from customer receipts.",
    )
    flexsys_hide_powered_by_odoo = fields.Boolean(
        string="Hide Powered by Odoo",
        default=True,
        help="Remove the Powered by Odoo line from customer receipts.",
    )

    # Closing report configuration
    flexsys_enable_thermal_closing_report = fields.Boolean(
        string="Enable Thermal Closing Report",
        default=False,
        help="Enable the FLPOS closing report designed for thermal printers.",
    )
    flexsys_enable_a4_closing_report = fields.Boolean(
        string="Enable A4 Closing Report",
        default=True,
        help="Enable the FLPOS A4 session closing report.",
    )
    flexsys_auto_print_thermal_closing_report = fields.Boolean(
        string="Auto Print Thermal Closing Report After Closing",
        default=False,
        help=(
            "Automatically open the thermal closing report for printing only "
            "after the POS session has been closed successfully."
        ),
    )


    @api.model
    def _load_pos_data_read(self, records, config):
        """Keep Odoo's complete POS configuration payload and add FLPOS values."""
        loaded_records = super()._load_pos_data_read(records, config)
        for loaded_record, record in zip(loaded_records, records):
            loaded_record.update({
                "flexsys_enable_custom_receipt_logo": record.flexsys_enable_custom_receipt_logo,
                "flexsys_has_receipt_logo": record.flexsys_has_receipt_logo,
                "flexsys_hide_company_logo": record.flexsys_hide_company_logo,
                "flexsys_hide_powered_by_odoo": record.flexsys_hide_powered_by_odoo,
                "flexsys_enable_thermal_closing_report": record.flexsys_enable_thermal_closing_report,
                "flexsys_enable_a4_closing_report": record.flexsys_enable_a4_closing_report,
                "flexsys_auto_print_thermal_closing_report": record.flexsys_auto_print_thermal_closing_report,
            })
        return loaded_records

    @api.depends("flexsys_receipt_logo")
    def _compute_flexsys_has_receipt_logo(self):
        """Store whether a dedicated receipt logo is configured."""
        for config in self:
            config.flexsys_has_receipt_logo = bool(config.flexsys_receipt_logo)
