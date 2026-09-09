from datetime import timedelta

from odoo import api, fields, models


class FlexSysPosDeviceAccessLog(models.Model):
    _name = "flexsys.pos.device.access.log"
    _description = "FlexSys POS Device Access Log"
    _order = "create_date desc, id desc"
    _rec_name = "token_fingerprint"

    device_id = fields.Many2one("flexsys.pos.device", ondelete="set null", index=True)
    pos_config_id = fields.Many2one("pos.config", ondelete="set null", index=True)
    company_id = fields.Many2one("res.company", ondelete="set null", index=True)
    service_user_id = fields.Many2one("res.users", ondelete="set null", index=True)
    employee_id = fields.Many2one("hr.employee", ondelete="set null", index=True)
    success = fields.Boolean(index=True)
    event = fields.Selection([
        ("success", "Success"),
        ("invalid_token", "Invalid Token"),
        ("inactive", "Inactive / Revoked"),
        ("expired", "Expired Token"),
        ("ip_denied", "IP Denied"),
        ("user_invalid", "Technical User Invalid"),
        ("config_invalid", "POS Configuration Invalid"),
        ("pin_success", "Cashier PIN Verified"),
    ], required=True, index=True)
    ip_address = fields.Char(index=True)
    user_agent = fields.Char()
    token_fingerprint = fields.Char(index=True, help="Non-secret SHA-256 prefix for correlation only.")

    @api.model
    def _cron_cleanup_access_logs(self):
        icp = self.env["ir.config_parameter"].sudo()
        try:
            retention_days = int(icp.get_param("flexsys_pos_device_access.log_retention_days", "90"))
        except (TypeError, ValueError):
            retention_days = 90
        retention_days = max(1, retention_days)
        cutoff = fields.Datetime.now() - timedelta(days=retention_days)
        self.sudo().search([("create_date", "<", cutoff)]).unlink()
