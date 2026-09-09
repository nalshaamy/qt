import hashlib
import ipaddress
import secrets
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.fields import Command
from odoo.exceptions import ValidationError


class FlexSysPosDevice(models.Model):
    _name = "flexsys.pos.device"
    _description = "FlexSys POS Device Access"
    _order = "company_id, name"

    name = fields.Char(required=True, index=True)
    device_uid = fields.Char(string="Device ID", copy=False, readonly=True, index=True)
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
        string="POS Service User",
        index=True,
        domain="[('active', '=', True), ('share', '=', False)]",
        help=(
            "Internal Odoo user used only to establish the device POS session. "
            "The cashier identity is verified separately by the native POS PIN screen."
        ),
    )
    service_user_is_managed = fields.Boolean(
        string="Managed by FlexSys",
        compute="_compute_service_user_is_managed",
    )

    # V1.0 legacy secure-link fields are intentionally retained so an existing
    # link can be consumed once as a V1.1 pairing link after module upgrade.
    token_hash = fields.Char(copy=False, readonly=True, index=True)
    token_hint = fields.Char(copy=False, readonly=True)
    token_created_at = fields.Datetime(copy=False, readonly=True)
    token_revoked_at = fields.Datetime(copy=False, readonly=True)
    token_expiry_policy = fields.Selection(
        [
            ("never", "No Expiry"),
            ("30_days", "30 Days"),
            ("90_days", "90 Days"),
            ("custom", "Custom Date"),
        ],
        string="Legacy Access Expiry Policy",
        default="never",
        required=True,
    )
    token_expires_at = fields.Datetime(copy=False, string="Legacy Access Expires At")

    # V1.1 one-time pairing token. Only the hash is persisted.
    pairing_token_hash = fields.Char(copy=False, readonly=True, index=True)
    pairing_token_hint = fields.Char(copy=False, readonly=True)
    pairing_token_created_at = fields.Datetime(copy=False, readonly=True)
    pairing_token_expires_at = fields.Datetime(copy=False, readonly=True)
    pairing_token_used_at = fields.Datetime(copy=False, readonly=True)
    pairing_link_validity = fields.Selection(
        [
            ("5", "5 Minutes"),
            ("10", "10 Minutes"),
            ("30", "30 Minutes"),
            ("60", "60 Minutes"),
        ],
        string="Pairing Link Validity",
        default="10",
        required=True,
    )
    has_pairing_link = fields.Boolean(compute="_compute_has_pairing_link")

    # Long-lived browser/device credential. The raw value exists only in the
    # Secure + HttpOnly cookie; Odoo stores a SHA-256 hash.
    credential_hash = fields.Char(copy=False, readonly=True, index=True)
    credential_hint = fields.Char(copy=False, readonly=True)
    credential_created_at = fields.Datetime(copy=False, readonly=True)
    credential_expires_at = fields.Datetime(copy=False, string="Credential Expires At")
    credential_expiry_policy = fields.Selection(
        [
            ("never", "No Expiry"),
            ("30_days", "30 Days"),
            ("90_days", "90 Days"),
            ("custom", "Custom Date"),
        ],
        string="Credential Expiry Policy",
        default="never",
        required=True,
    )
    credential_version = fields.Integer(default=0, copy=False, readonly=True)

    paired_at = fields.Datetime(copy=False, readonly=True)
    paired_ip = fields.Char(copy=False, readonly=True)
    paired_user_agent = fields.Char(copy=False, readonly=True)
    revoked_at = fields.Datetime(copy=False, readonly=True)
    revoked_by = fields.Many2one("res.users", copy=False, readonly=True, ondelete="set null")

    allowed_ip = fields.Char(
        string="Allowed IP / CIDR",
        help="Optional comma-separated exact IPs or CIDR networks. Leave empty to allow any client IP.",
    )
    last_used_at = fields.Datetime(copy=False, readonly=True)
    last_ip = fields.Char(copy=False, readonly=True)
    last_user_pin_success = fields.Char(
        copy=False,
        readonly=True,
        help="Last employee whose native POS PIN was successfully verified. No PIN value is stored.",
    )
    last_user_pin_success_at = fields.Datetime(copy=False, readonly=True)
    access_count = fields.Integer(copy=False, readonly=True, default=0)
    access_log_count = fields.Integer(compute="_compute_access_log_count")
    notes = fields.Text()

    pairing_state = fields.Selection(
        [
            ("unpaired", "Unpaired"),
            ("paired", "Paired"),
            ("disabled", "Disabled"),
            ("revoked", "Revoked"),
            ("expired", "Expired"),
        ],
        string="Pairing Status",
        compute="_compute_pairing_state",
        store=False,
    )
    # Backward-compatible display field used by older views/integrations.
    access_status = fields.Selection(
        [
            ("not_configured", "Not Configured"),
            ("active", "Active"),
            ("disabled", "Disabled"),
            ("revoked", "Revoked"),
            ("expired", "Expired"),
        ],
        string="Device Access Status",
        compute="_compute_access_status",
        store=False,
    )
    has_token = fields.Boolean(compute="_compute_has_token")

    _legacy_token_hash_unique = models.Constraint(
        "UNIQUE(token_hash)",
        "The legacy secure token hash must be unique.",
    )
    _pairing_token_hash_unique = models.Constraint(
        "UNIQUE(pairing_token_hash)",
        "The pairing token hash must be unique.",
    )
    _credential_hash_unique = models.Constraint(
        "UNIQUE(credential_hash)",
        "The device credential hash must be unique.",
    )
    _device_uid_unique = models.Constraint(
        "UNIQUE(device_uid)",
        "The Device ID must be unique.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [dict(vals) for vals in vals_list]
        for vals in vals_list:
            if not vals.get("device_uid"):
                vals["device_uid"] = self.env["ir.sequence"].next_by_code("flexsys.pos.device") or _("New")
            if not vals.get("service_user_id"):
                company = self.env["res.company"].browse(vals.get("company_id") or self.env.company.id)
                vals["service_user_id"] = self._get_or_create_managed_service_user(company).id
        return super().create(vals_list)

    @api.depends("token_hash")
    def _compute_has_token(self):
        for rec in self:
            rec.has_token = bool(rec.token_hash)

    @api.depends("pairing_token_hash", "pairing_token_used_at", "pairing_token_expires_at")
    def _compute_has_pairing_link(self):
        now = fields.Datetime.now()
        for rec in self:
            rec.has_pairing_link = bool(
                rec.pairing_token_hash
                and not rec.pairing_token_used_at
                and (not rec.pairing_token_expires_at or rec.pairing_token_expires_at > now)
            )

    @api.depends("service_user_id", "company_id")
    def _compute_service_user_is_managed(self):
        for rec in self:
            rec.service_user_is_managed = bool(
                rec.service_user_id
                and rec.company_id
                and rec.service_user_id.login == rec._managed_service_login(rec.company_id)
            )

    @api.depends("active", "credential_hash", "credential_expires_at", "revoked_at")
    def _compute_pairing_state(self):
        now = fields.Datetime.now()
        for rec in self:
            if not rec.active:
                rec.pairing_state = "disabled"
            elif rec.revoked_at:
                rec.pairing_state = "revoked"
            elif rec.credential_hash and rec.credential_expires_at and rec.credential_expires_at <= now:
                rec.pairing_state = "expired"
            elif rec.credential_hash:
                rec.pairing_state = "paired"
            else:
                rec.pairing_state = "unpaired"

    @api.depends("active", "credential_hash", "credential_expires_at", "revoked_at")
    def _compute_access_status(self):
        for rec in self:
            state = rec.pairing_state
            rec.access_status = {
                "unpaired": "not_configured",
                "paired": "active",
                "disabled": "disabled",
                "revoked": "revoked",
                "expired": "expired",
            }.get(state, "not_configured")

    def _compute_access_log_count(self):
        grouped = self.env["flexsys.pos.device.access.log"]._read_group(
            [("device_id", "in", self.ids)], ["device_id"], ["__count"]
        ) if self.ids else []
        by_device = {device.id: count for device, count in grouped}
        for rec in self:
            rec.access_log_count = by_device.get(rec.id, 0)

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
            if not user:
                raise ValidationError(_("A POS Service User is required."))
            if rec.company_id not in user.company_ids:
                raise ValidationError(_("The POS Service User must have access to the device company."))
            if user._is_system():
                raise ValidationError(_("A system administrator cannot be used as the POS Service User."))
            if not (
                user.has_group("point_of_sale.group_pos_user")
                or user.has_group("point_of_sale.group_pos_manager")
            ):
                raise ValidationError(_("The POS Service User must have Point of Sale access (User or Administrator)."))

    @api.constrains("allowed_ip")
    def _check_allowed_ip(self):
        for rec in self:
            for entry in rec._allowed_ip_entries():
                try:
                    if "/" in entry:
                        ipaddress.ip_network(entry, strict=False)
                    else:
                        ipaddress.ip_address(entry)
                except ValueError as exc:
                    raise ValidationError(_("Invalid Allowed IP / CIDR entry: %s", entry)) from exc

    @api.model
    def _managed_service_login(self, company):
        return f"flexsys.pos.service.company.{company.id}@local.invalid"

    @api.model
    def _get_or_create_managed_service_user(self, company):
        company = company.sudo().exists()
        if not company:
            raise ValidationError(_("A valid company is required to create the POS Service User."))

        login = self._managed_service_login(company)
        Users = self.env["res.users"].sudo().with_context(active_test=False)
        user = Users.search([("login", "=", login)], limit=1)
        base_user = self.env.ref("base.group_user")
        pos_user = self.env.ref("point_of_sale.group_pos_user")

        if not user:
            user = Users.create({
                "name": _("FlexSys POS Service — %s", company.name),
                "login": login,
                "company_id": company.id,
                "company_ids": [Command.set([company.id])],
                "group_ids": [Command.set([base_user.id, pos_user.id])],
                "active": True,
            })
        else:
            vals = {}
            if not user.active:
                vals["active"] = True
            if company not in user.company_ids:
                vals["company_ids"] = [Command.link(company.id)]
            if not user.has_group("point_of_sale.group_pos_user"):
                vals["group_ids"] = [Command.link(pos_user.id)]
            if user.company_id != company:
                vals["company_id"] = company.id
            if vals:
                user.write(vals)

        if user._is_system():
            raise ValidationError(_("The managed FlexSys POS Service User unexpectedly has system administration rights."))
        return user

    def action_use_managed_service_user(self):
        self.ensure_one()
        user = self._get_or_create_managed_service_user(self.company_id)
        self.service_user_id = user
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("POS Service User"),
                "message": _("FlexSys managed POS Service User is assigned and ready."),
                "type": "success",
                "sticky": False,
            },
        }

    @api.model
    def _new_raw_token(self):
        return secrets.token_urlsafe(32)

    @api.model
    def _hash_token(self, token):
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _allowed_ip_entries(self):
        self.ensure_one()
        if not self.allowed_ip:
            return []
        return [x.strip() for x in self.allowed_ip.replace("\n", ",").split(",") if x.strip()]

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
        for entry in self._allowed_ip_entries():
            try:
                if "/" in entry:
                    if address in ipaddress.ip_network(entry, strict=False):
                        return True
                elif address == ipaddress.ip_address(entry):
                    return True
            except ValueError:
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

    def _credential_is_expired(self):
        self.ensure_one()
        return bool(self.credential_expires_at and self.credential_expires_at <= fields.Datetime.now())

    def _credential_expiration_on_pair(self, now):
        self.ensure_one()
        policy = self.credential_expiry_policy
        if policy == "never":
            return False
        if policy == "30_days":
            return now + timedelta(days=30)
        if policy == "90_days":
            return now + timedelta(days=90)
        if policy == "custom":
            if not self.credential_expires_at:
                raise ValidationError(_("Set a custom Credential Expires At date before generating the Pairing Link."))
            if self.credential_expires_at <= now:
                raise ValidationError(_("The custom Credential Expires At date must be in the future."))
            return self.credential_expires_at
        return False

    def _pairing_link_expiration(self, now):
        self.ensure_one()
        try:
            minutes = int(self.pairing_link_validity or "10")
        except (TypeError, ValueError):
            minutes = 10
        return now + timedelta(minutes=max(1, minutes))

    def _audit_admin_event(self, event, success=True, details=False):
        self.ensure_one()
        self.env["flexsys.pos.device.access.log"].sudo().create({
            "device_id": self.id,
            "pos_config_id": self.pos_config_id.id,
            "company_id": self.company_id.id,
            "service_user_id": self.service_user_id.id,
            "actor_user_id": self.env.user.id,
            "success": success,
            "event": event,
            "details": details or False,
        })

    def _build_pairing_wizard(self, raw_token):
        self.ensure_one()
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "").rstrip("/")
        url = f"{base_url}/flexsys/pos/pair/{raw_token}"
        wizard = self.env["flexsys.pos.device.token.wizard"].create({
            "device_id": self.id,
            "token_value": raw_token,
            "token_url": url,
            "expires_at": self.pairing_token_expires_at,
        })
        return {
            "type": "ir.actions.act_window",
            "name": _("One-Time Device Pairing Link"),
            "res_model": "flexsys.pos.device.token.wizard",
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_generate_pairing_link(self):
        self.ensure_one()
        if not self.active:
            raise ValidationError(_("Enable the device before generating a Pairing Link."))
        if self.revoked_at:
            raise ValidationError(_("This device is revoked. Reset Pairing before generating a new link."))
        if self.credential_hash:
            raise ValidationError(_("This device is already paired. Reset Pairing before binding another browser/device."))
        if not self._service_user_is_valid():
            raise ValidationError(_("The POS Service User is not valid. Run Test Device Access or assign the managed service user."))
        if not self.pos_config_id.active or not self.pos_config_id.module_pos_hr:
            raise ValidationError(_("The Point of Sale must be active with Employee Login enabled."))

        raw_token = self._new_raw_token()
        now = fields.Datetime.now()
        event = "pairing_link_rotated" if self.pairing_token_hash and not self.pairing_token_used_at else "pairing_link_created"
        self.write({
            "pairing_token_hash": self._hash_token(raw_token),
            "pairing_token_hint": raw_token[-8:],
            "pairing_token_created_at": now,
            "pairing_token_expires_at": self._pairing_link_expiration(now),
            "pairing_token_used_at": False,
            # A new V1.1 link supersedes any legacy V1.0 secure link.
            "token_hash": False,
            "token_hint": False,
            "token_created_at": False,
            "token_revoked_at": False,
        })
        self._audit_admin_event(event, success=True)
        return self._build_pairing_wizard(raw_token)

    # Backward-compatible method name for upgrades from 1.0.x.
    def action_generate_token(self):
        return self.action_generate_pairing_link()

    def action_reset_pairing(self):
        for rec in self:
            rec._audit_admin_event("pairing_reset", success=True)
            rec.write({
                "credential_hash": False,
                "credential_hint": False,
                "credential_created_at": False,
                "credential_expires_at": False if rec.credential_expiry_policy != "custom" else rec.credential_expires_at,
                "credential_version": rec.credential_version + 1,
                "paired_at": False,
                "paired_ip": False,
                "paired_user_agent": False,
                "pairing_token_hash": False,
                "pairing_token_hint": False,
                "pairing_token_created_at": False,
                "pairing_token_expires_at": False,
                "pairing_token_used_at": False,
                "token_hash": False,
                "token_hint": False,
                "token_created_at": False,
                "token_revoked_at": False,
                "revoked_at": False,
                "revoked_by": False,
            })
        return True

    def action_revoke_access(self):
        for rec in self:
            rec._audit_admin_event("device_revoked", success=True)
            rec.write({
                "credential_hash": False,
                "credential_hint": False,
                "credential_created_at": False,
                "credential_version": rec.credential_version + 1,
                "pairing_token_hash": False,
                "pairing_token_hint": False,
                "pairing_token_created_at": False,
                "pairing_token_expires_at": False,
                "pairing_token_used_at": False,
                "token_hash": False,
                "token_hint": False,
                "token_created_at": False,
                "token_revoked_at": fields.Datetime.now(),
                "revoked_at": fields.Datetime.now(),
                "revoked_by": self.env.user.id,
            })
        return True

    # Backward-compatible method name for upgrades from 1.0.x.
    def action_revoke_token(self):
        return self.action_revoke_access()

    def action_test_device_access(self):
        self.ensure_one()
        problems = []
        warnings = []

        if not self.active:
            problems.append(_("Device is disabled."))
        if self.revoked_at:
            problems.append(_("Device access is revoked."))
        if not self.pos_config_id or not self.pos_config_id.active:
            problems.append(_("Point of Sale is missing or inactive."))
        elif self.pos_config_id.company_id != self.company_id:
            problems.append(_("Point of Sale belongs to a different company."))
        elif not self.pos_config_id.module_pos_hr:
            problems.append(_("Employee Login is not enabled on the Point of Sale."))
        if not self._service_user_is_valid():
            problems.append(_("POS Service User is missing, invalid, or has insufficient POS access."))
        try:
            self._check_allowed_ip()
        except ValidationError as exc:
            problems.append(str(exc))

        if self.credential_hash:
            if self._credential_is_expired():
                problems.append(_("The paired device credential is expired."))
        elif self.has_pairing_link:
            warnings.append(_("Device is not paired yet; a one-time Pairing Link is ready."))
        else:
            warnings.append(_("Device is not paired. Generate a one-time Pairing Link."))

        if problems:
            message = "\n".join([_("Device Access test failed:"), *[f"• {item}" for item in problems]])
            if warnings:
                message += "\n" + "\n".join(f"• {item}" for item in warnings)
            self._audit_admin_event("device_test_failed", success=False, details="; ".join(problems)[:1000])
            notification_type = "danger"
            title = _("Device Access Test Failed")
        else:
            message = _("Configuration is ready.")
            if warnings:
                message += "\n" + "\n".join(f"• {item}" for item in warnings)
            self._audit_admin_event("device_test_success", success=True, details="; ".join(warnings)[:1000])
            notification_type = "success" if not warnings else "warning"
            title = _("Device Access Ready")

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": title,
                "message": message,
                "type": notification_type,
                "sticky": bool(problems),
            },
        }

    def action_open_access_logs(self):
        self.ensure_one()
        action = self.env.ref("flexsys_pos_device_access.action_flexsys_pos_device_access_log").read()[0]
        action["domain"] = [("device_id", "=", self.id)]
        action["context"] = {"default_device_id": self.id}
        return action
