import hashlib
import ipaddress
import secrets

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class FlexSysPosDevice(models.Model):
    _name = "flexsys.pos.device"
    _description = "FlexSys POS Device Access"
    _order = "company_id, name"

    name = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True, index=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    pos_config_id = fields.Many2one(
        "pos.config",
        string="Point of Sale",
        required=True,
        index=True,
        domain="[('company_id', '=', company_id), ('active', '=', True)]",
    )
    service_user_id = fields.Many2one(
        "res.users",
        string="Technical POS User",
        required=True,
        index=True,
        domain="[('active', '=', True), ('share', '=', False)]",
        help=(
            "Dedicated internal Odoo user used only to establish the device POS session. "
            "The cashier identity is still verified separately by the native POS PIN screen."
        ),
    )
    token_hash = fields.Char(copy=False, readonly=True, index=True)
    token_hint = fields.Char(copy=False, readonly=True, help="Non-secret suffix shown for identification only.")
    token_created_at = fields.Datetime(copy=False, readonly=True)
    token_expires_at = fields.Datetime(copy=False, string="Token Expires At")
    allowed_ip = fields.Char(
        string="Allowed IP / CIDR",
        help="Optional comma-separated exact IPs or CIDR networks. Leave empty to allow any client IP.",
    )
    last_used_at = fields.Datetime(copy=False, readonly=True)
    last_ip = fields.Char(copy=False, readonly=True)
    last_user_pin_success = fields.Char(
        copy=False,
        readonly=True,
        help="Display name of the last employee whose PIN was successfully verified on this device. No PIN value is stored.",
    )
    last_user_pin_success_at = fields.Datetime(copy=False, readonly=True)
    access_count = fields.Integer(copy=False, readonly=True, default=0)
    notes = fields.Text()
    has_token = fields.Boolean(compute="_compute_has_token")

    _token_hash_unique = models.Constraint(
        "UNIQUE(token_hash)",
        "The secure token hash must be unique.",
    )

    @api.depends("token_hash")
    def _compute_has_token(self):
        for rec in self:
            rec.has_token = bool(rec.token_hash)

    @api.constrains("company_id", "pos_config_id")
    def _check_pos_company(self):
        for rec in self:
            if rec.pos_config_id and rec.pos_config_id.company_id != rec.company_id:
                raise ValidationError(_("The Point of Sale must belong to the device company."))
            if rec.pos_config_id and not rec.pos_config_id.module_pos_hr:
                raise ValidationError(_(
                    "Employee Login must be enabled on the Point of Sale so cashier PIN verification remains mandatory."
                ))

    @api.constrains("company_id", "service_user_id")
    def _check_service_user_company(self):
        for rec in self:
            user = rec.service_user_id.sudo()
            if user and rec.company_id not in user.company_ids:
                raise ValidationError(_("The technical POS user must have access to the device company."))
            if user and user._is_system():
                raise ValidationError(_("A system administrator cannot be used as the technical POS user."))

    @api.model
    def _new_raw_token(self):
        # 32 random bytes -> ~43 URL-safe characters (~256 bits entropy).
        return secrets.token_urlsafe(32)

    @api.model
    def _hash_token(self, token):
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _token_is_expired(self):
        self.ensure_one()
        return bool(self.token_expires_at and self.token_expires_at <= fields.Datetime.now())

    def _ip_is_allowed(self, client_ip):
        self.ensure_one()
        if not self.allowed_ip:
            return True
        if not client_ip:
            return False
        try:
            address = ipaddress.ip_address(client_ip.strip())
        except ValueError:
            return False

        entries = [x.strip() for x in self.allowed_ip.replace("\n", ",").split(",") if x.strip()]
        for entry in entries:
            try:
                if "/" in entry:
                    if address in ipaddress.ip_network(entry, strict=False):
                        return True
                elif address == ipaddress.ip_address(entry):
                    return True
            except ValueError:
                # Invalid configured entries never broaden access.
                continue
        return False

    def _service_user_is_valid(self):
        self.ensure_one()
        user = self.service_user_id.sudo()
        if not user or not user.active or user.share or user._is_system():
            return False
        if self.company_id not in user.company_ids:
            return False
        return user.has_group("point_of_sale.group_pos_user") or user.has_group("point_of_sale.group_pos_manager")

    def _build_token_wizard(self, raw_token):
        self.ensure_one()
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "").rstrip("/")
        url = f"{base_url}/flexsys/pos/device/{raw_token}"
        wizard = self.env["flexsys.pos.device.token.wizard"].create({
            "device_id": self.id,
            "token_value": raw_token,
            "token_url": url,
        })
        return {
            "type": "ir.actions.act_window",
            "name": _("Secure Device Link"),
            "res_model": "flexsys.pos.device.token.wizard",
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_generate_token(self):
        self.ensure_one()
        raw_token = self._new_raw_token()
        self.write({
            "token_hash": self._hash_token(raw_token),
            "token_hint": raw_token[-8:],
            "token_created_at": fields.Datetime.now(),
        })
        return self._build_token_wizard(raw_token)

    def action_revoke_token(self):
        for rec in self:
            rec.write({
                "token_hash": False,
                "token_hint": False,
                "token_created_at": False,
            })
        return True
