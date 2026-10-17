from odoo import fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    flexsys_show_company_footer = fields.Boolean(
        string="Show Company Details on POS Receipt",
        default=False,
        help="Show the branch address and contact details at the bottom of the POS receipt.",
    )

    # Diagnostic isolation: do not override _load_pos_data_fields.
    # The field remains defined, but is not injected into POS startup data.
