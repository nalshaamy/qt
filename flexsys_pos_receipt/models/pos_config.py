from odoo import fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    # Intentionally NO _load_pos_data_fields override: the POS loader is left untouched.
    flexsys_show_company_footer = fields.Boolean(
        string="Show Company Details on POS Receipt", default=False,
        help="Print branch address/contact details at the receipt bottom; VAT stays at the top.",
    )
    flexsys_show_header_image = fields.Boolean(
        string="Show Promotional Header Image", default=False,
    )
    flexsys_header_image_position = fields.Selection(
        [("above", "Above the Logo"), ("below", "Below the Logo")],
        string="Promotional Header Image Position", default="above", required=True,
    )
    flexsys_header_image = fields.Image(
        string="Promotional Header Image", max_width=576, max_height=700,
        help="Optional high-contrast black-and-white PNG/JPG. Resized to at most 576 x 700 pixels.",
    )
    flexsys_show_footer_image = fields.Boolean(
        string="Show Promotional Footer Image", default=False,
    )
    flexsys_footer_image = fields.Image(
        string="Promotional Footer Image", max_width=576, max_height=700,
        help="Optional high-contrast black-and-white PNG/JPG. Resized to at most 576 x 700 pixels.",
    )
    flexsys_currency_symbol_mode = fields.Selection(
        [("new", "New Saudi Riyal Symbol"), ("sr", "SR Text")],
        string="Receipt Currency Symbol", default="new", required=True,
        help="Changes receipt presentation only. Odoo accounting currency remains SAR.",
    )
    flexsys_show_thank_you = fields.Boolean(
        string="Show Custom Thank You Message", default=False,
    )
    flexsys_thank_you_ar = fields.Char(string="Thank You Message (Arabic)")
    flexsys_thank_you_en = fields.Char(string="Thank You Message (English)")
