from odoo import api, fields, models


class FlexSysPosDeviceTokenWizard(models.TransientModel):
    _name = "flexsys.pos.device.token.wizard"
    _description = "FlexSys POS Device Pairing Link"

    device_id = fields.Many2one("flexsys.pos.device", required=True, readonly=True)
    token_url = fields.Char(
        string="One-Time Pairing URL",
        compute="_compute_token_url",
        readonly=True,
        store=False,
    )
    expires_at = fields.Datetime(string="Expires At", readonly=True)

    @api.depends_context("flexsys_pairing_url")
    def _compute_token_url(self):
        # The raw pairing secret exists only in the action context returned to
        # the administrator's browser. It is never written to a persistent or
        # transient Odoo model.
        pairing_url = self.env.context.get("flexsys_pairing_url") or False
        for wizard in self:
            wizard.token_url = pairing_url
