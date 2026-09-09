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
    actor_user_id = fields.Many2one("res.users", string="Actor", ondelete="set null", index=True)
    employee_id = fields.Many2one("hr.employee", ondelete="set null", index=True)
    success = fields.Boolean(index=True)
    event = fields.Selection([
        ("device_access_success", "Device Access Success"),
        ("success", "Legacy Device Access Success"),
        ("invalid_token", "Invalid Pairing Token"),
        ("pairing_link_created", "Pairing Link Created"),
        ("pairing_link_rotated", "Pairing Link Rotated"),
        ("pairing_success", "Device Pairing Success"),
        ("pairing_expired", "Pairing Link Expired"),
        ("pairing_reuse_rejected", "Pairing Reuse Rejected"),
        ("pairing_reset", "Device Pairing Reset"),
        ("invalid_credential", "Invalid Device Credential"),
        ("credential_expired", "Device Credential Expired"),
        ("device_disabled", "Device Disabled"),
        ("device_revoked", "Device Revoked"),
        ("stale_session_blocked", "Stale Device Session Blocked"),
        ("inactive", "Inactive / Revoked"),
        ("expired", "Legacy Token Expired"),
        ("ip_denied", "IP Denied"),
        ("user_invalid", "POS Service User Invalid"),
        ("config_invalid", "POS Configuration Invalid"),
        ("pin_success", "Cashier PIN Verified"),
        ("backend_blocked", "Backend Access Blocked"),
        ("pos_switch_blocked", "Other POS Access Blocked"),
        ("token_generated", "Legacy Secure Link Generated"),
        ("token_rotated", "Legacy Secure Link Rotated"),
        ("token_revoked", "Legacy Secure Link Revoked"),
        ("device_test_success", "Device Access Test Passed"),
        ("device_test_failed", "Device Access Test Failed"),
    ], required=True, index=True)
    ip_address = fields.Char(index=True)
    user_agent = fields.Char()
    token_fingerprint = fields.Char(index=True, help="Non-secret SHA-256 prefix for correlation only.")
    details = fields.Char(help="Sanitized diagnostic detail. Never contains raw tokens, device credentials, or PIN values.")

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
