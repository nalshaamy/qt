# -*- coding: utf-8 -*-
# FLPOS - Exposes per-POS options in Point of Sale settings.

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    """Expose FLPOS fields for the POS selected on the settings page."""

    _inherit = "res.config.settings"

    flexsys_enable_custom_receipt_logo = fields.Boolean(
        related="pos_config_id.flexsys_enable_custom_receipt_logo",
        readonly=False,
        string="Enable Custom Receipt Logo",
    )
    flexsys_receipt_logo = fields.Image(
        related="pos_config_id.flexsys_receipt_logo",
        readonly=False,
        string="Customer Receipt Logo",
    )
    flexsys_hide_company_logo = fields.Boolean(
        related="pos_config_id.flexsys_hide_company_logo",
        readonly=False,
        string="Hide Company Logo",
    )
    flexsys_hide_powered_by_odoo = fields.Boolean(
        related="pos_config_id.flexsys_hide_powered_by_odoo",
        readonly=False,
        string="Hide Powered by Odoo",
    )
    flexsys_enable_thermal_closing_report = fields.Boolean(
        related="pos_config_id.flexsys_enable_thermal_closing_report",
        readonly=False,
        string="Enable Thermal Closing Report",
    )
    flexsys_enable_a4_closing_report = fields.Boolean(
        related="pos_config_id.flexsys_enable_a4_closing_report",
        readonly=False,
        string="Enable A4 Closing Report",
    )
    flexsys_auto_print_thermal_closing_report = fields.Boolean(
        related="pos_config_id.flexsys_auto_print_thermal_closing_report",
        readonly=False,
        string="Auto Print Thermal Closing Report After Closing",
    )
