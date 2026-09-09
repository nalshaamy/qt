from odoo import fields, models


class FlexSysPosDeviceTokenWizard(models.TransientModel):
    _name = "flexsys.pos.device.token.wizard"
    _description = "FlexSys POS Device Secure Link"

    device_id = fields.Many2one("flexsys.pos.device", required=True, readonly=True)
    token_value = fields.Char(string="Secure Token", required=True, readonly=True)
    token_url = fields.Char(string="Secure Device URL", required=True, readonly=True)
