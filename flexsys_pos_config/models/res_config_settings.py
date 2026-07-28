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
    flexsys_report_language = fields.Selection(
        related="pos_config_id.flexsys_report_language",
        readonly=False,
        string="Report Language",
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
    flexsys_enable_email_closing_report = fields.Boolean(
        related="pos_config_id.flexsys_enable_email_closing_report",
        readonly=False,
        string="Enable Email Closing Report",
    )
    flexsys_show_top_selling_products = fields.Boolean(
        related="pos_config_id.flexsys_show_top_selling_products",
        readonly=False,
        string="Show Top Selling Products",
    )
    flexsys_hide_zero_sales_top_products = fields.Boolean(
        related="pos_config_id.flexsys_hide_zero_sales_top_products",
        readonly=False,
        string="Hide Zero-Sales Products from Top Products",
    )

    flexsys_show_cashier_performance = fields.Boolean(
        related="pos_config_id.flexsys_show_cashier_performance",
        readonly=False,
        string="Show Cashier Performance",
    )
