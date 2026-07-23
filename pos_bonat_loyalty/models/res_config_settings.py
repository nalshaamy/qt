from odoo import models, fields, api

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    enable_bonat_integration = fields.Boolean(related='company_id.enable_bonat_integration', readonly=False)
    bonat_api_key = fields.Char(related='company_id.bonat_api_key', readonly=False)
    bonat_merchant_name = fields.Char(related='company_id.bonat_merchant_name', readonly=False)
    bonat_merchant_id = fields.Char(related='company_id.bonat_merchant_id', readonly=False)
    # bonat_discount_percentage_product_id = fields.Many2one(related='company_id.bonat_discount_percentage_product_id', readonly=False)

    @api.onchange('enable_bonat_integration')
    def _onchange_enable_bonat_integration(self):
        """Clear API key if integration is disabled."""
        if not self.enable_bonat_integration:
            self.bonat_api_key = False
