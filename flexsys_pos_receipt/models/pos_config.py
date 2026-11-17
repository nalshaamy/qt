from odoo import api, fields, models
from odoo.exceptions import ValidationError


class PosConfig(models.Model):
    _inherit = "pos.config"

    # Configuration applies to the original company/POS logo, not promotional imagery.
    flexsys_logo_width_mm = fields.Integer(
        string="Receipt Logo Width (mm)", default=72, required=True,
        help="Width of the main POS receipt logo. 30-72 mm, default 72 mm for Epson TM-T20III 80 mm paper. The original aspect ratio is preserved.",
    )

    @api.constrains("flexsys_logo_width_mm")
    def _check_flexsys_logo_width_mm(self):
        for config in self:
            if not 30 <= config.flexsys_logo_width_mm <= 72:
                raise ValidationError("Receipt Logo Width must be between 30 and 72 mm.")

    flexsys_logo_trim_whitespace = fields.Boolean(
        string="Trim White Logo Margins", default=True,
        help="Trim blank white/transparent margins in the receipt-only copy of the main logo. The original image is not changed.",
    )
    flexsys_header_image_width_mm = fields.Integer(
        string="Promotional Header Image Width (mm)", default=48, required=True,
        help="Thermal-print image width from 20 to 72 mm. Default 48 mm.",
    )
    flexsys_footer_image_width_mm = fields.Integer(
        string="Promotional Footer Image Width (mm)", default=36, required=True,
        help="Thermal-print image width from 20 to 72 mm. Default 36 mm.",
    )

    @api.constrains("flexsys_header_image_width_mm", "flexsys_footer_image_width_mm")
    def _check_flexsys_promo_widths(self):
        for config in self:
            for field_name in ("flexsys_header_image_width_mm", "flexsys_footer_image_width_mm"):
                if not 20 <= config[field_name] <= 72:
                    raise ValidationError("Promotional image widths must be between 20 and 72 mm.")

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
