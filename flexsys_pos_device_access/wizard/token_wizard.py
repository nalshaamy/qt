from odoo import fields, models


class FlexSysPosDeviceTokenWizard(models.TransientModel):
    _name = "flexsys.pos.device.token.wizard"
    _description = "FlexSys POS Device Pairing Link"

    device_id = fields.Many2one("flexsys.pos.device", required=True, readonly=True)
    token_value = fields.Char(string="Pairing Token", required=True, readonly=True)
    token_url = fields.Char(string="One-Time Pairing URL", required=True, readonly=True)
    expires_at = fields.Datetime(string="Expires At", readonly=True)
