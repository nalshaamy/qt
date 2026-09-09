import hashlib
import logging
import re
from datetime import timedelta

from odoo import fields, http
from odoo.http import request

_logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,160}$")
_DEVICE_COOKIE = "flexsys_pos_device_credential"
_COOKIE_MAX_AGE = 365 * 24 * 60 * 60


class FlexSysPosDeviceAccessController(http.Controller):
    """One-time device pairing gateway plus persistent device entry."""

    def _client_ip(self):
        return request.httprequest.remote_addr or ""

    def _token_fingerprint(self, token):
        if not token:
            return False
        return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]

    def _rate_limit_settings(self):
        icp = request.env["ir.config_parameter"].sudo()
        try:
            max_failed = int(icp.get_param("flexsys_pos_device_access.rate_limit_max_failed", "10"))
        except (TypeError, ValueError):
            max_failed = 10
        try:
            window_seconds = int(icp.get_param("flexsys_pos_device_access.rate_limit_window_seconds", "60"))
        except (TypeError, ValueError):
            window_seconds = 60
        return max(1, max_failed), max(10, window_seconds)

    def _is_rate_limited(self, ip_address):
        if not ip_address:
            return False
        max_failed, window_seconds = self._rate_limit_settings()
        since = fields.Datetime.now() - timedelta(seconds=window_seconds)
        failed = request.env["flexsys.pos.device.access.log"].sudo().search_count([
            ("ip_address", "=", ip_address),
            ("event", "in", ["invalid_token", "invalid_credential"]),
            ("create_date", ">=", since),
        ])
        return failed >= max_failed

    def _log(self, *, device=None, employee=None, success=False, event="invalid_token", token="", details=False):
        request.env["flexsys.pos.device.access.log"].sudo().create({
            "device_id": device.id if device else False,
            "pos_config_id": device.pos_config_id.id if device else False,
            "company_id": device.company_id.id if device else False,
            "service_user_id": device.service_user_id.id if device else False,
            "employee_id": employee.id if employee else False,
            "actor_user_id": request.session.uid or False,
            "success": success,
            "event": event,
            "ip_address": self._client_ip(),
            "user_agent": (request.httprequest.headers.get("User-Agent") or "")[:512],
            "token_fingerprint": self._token_fingerprint(token),
            "details": (details or "")[:1000],
        })

    def _response(self, body, status=403, clear_cookie=False):
        response = request.make_response(body, status=status)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        if clear_cookie:
            response.delete_cookie(_DEVICE_COOKIE, path="/")
        return response

    def _generic_not_found(self):
        return self._response("Not Found", status=404)

    def _pairing_denied(self):
        return self._response(
            "Device pairing is unavailable. Ask an administrator to reset pairing and issue a new one-time link.",
            status=403,
        )

    def _device_denied(self, clear_cookie=True):
        return self._response(
            "This browser is not authorized for this POS device. Ask an administrator to reset device pairing.",
            status=403,
            clear_cookie=clear_cookie,
        )

    def _device_is_operational(self, device, ip_address):
        return bool(
            device
            and device.active
            and not device.revoked_at
            and device.pos_config_id.active
            and device.pos_config_id.company_id == device.company_id
            and device.pos_config_id.module_pos_hr
            and device._service_user_is_valid()
            and device._ip_is_allowed(ip_address)
        )

    def _establish_device_session(self, device):
        user = device.service_user_id.sudo()
        session = request.session
        session.logout(keep_db=True)
        session["pre_login"] = user.login
        session["pre_uid"] = user.id
        session.finalize(request.env)
        session["flexsys_pos_device_id"] = device.id
        session["flexsys_pos_device_credential_version"] = device.credential_version
        session.touch()
        request.update_env(user=session.uid, context=session.context, su=False)

    def _set_device_cookie(self, response, raw_credential, device):
        max_age = _COOKIE_MAX_AGE
        if device.credential_expires_at:
            remaining = int((device.credential_expires_at - fields.Datetime.now()).total_seconds())
            max_age = max(1, min(_COOKIE_MAX_AGE, remaining))
        response.set_cookie(
            _DEVICE_COOKIE,
            raw_credential,
            max_age=max_age,
            secure=True,
            httponly=True,
            samesite="Lax",
            path="/",
        )
        return response

    def _refresh_device_cookie(self, response, raw_credential, device):
        return self._set_device_cookie(response, raw_credential, device)

    def _find_pairing_device(self, token_hash):
        Device = request.env["flexsys.pos.device"].sudo()
        device = Device.search([("pairing_token_hash", "=", token_hash)], limit=1)
        if device:
            return device, False
        # Upgrade compatibility: a V1.0 secure link becomes a one-time V1.1
        # pairing link. It is consumed once and can never be used again.
        legacy = Device.search([("token_hash", "=", token_hash)], limit=1)
        return legacy, bool(legacy)

    @http.route(
        [
            "/flexsys/pos/pair/<string:token>",
            "/flexsys/pos/device/<string:token>",
        ],
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        sitemap=False,
        readonly=False,
    )
    def pair_device(self, token, **kwargs):
        ip_address = self._client_ip()
        if self._is_rate_limited(ip_address):
            response = self._response("Too Many Requests", status=429)
            response.headers["Retry-After"] = "60"
            return response

        if not token or not _TOKEN_RE.fullmatch(token):
            self._log(success=False, event="invalid_token", token=token)
            return self._generic_not_found()

        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        device, legacy = self._find_pairing_device(token_hash)
        if not device:
            self._log(success=False, event="invalid_token", token=token)
            return self._generic_not_found()

        # Serialize pairing attempts so two browsers opening the same link at
        # nearly the same instant cannot both win the first-device binding.
        request.env.cr.execute("SELECT id FROM flexsys_pos_device WHERE id = %s FOR UPDATE", (device.id,))
        device.invalidate_recordset()

        if legacy:
            used_at = False
            expires_at = device.token_expires_at
        else:
            used_at = device.pairing_token_used_at
            expires_at = device.pairing_token_expires_at

        if used_at or device.credential_hash:
            self._log(device=device, success=False, event="pairing_reuse_rejected", token=token)
            return self._pairing_denied()
        if expires_at and expires_at <= fields.Datetime.now():
            self._log(device=device, success=False, event="pairing_expired", token=token)
            return self._pairing_denied()
        if not self._device_is_operational(device, ip_address):
            event = "ip_denied" if not device._ip_is_allowed(ip_address) else "config_invalid"
            self._log(device=device, success=False, event=event, token=token)
            return self._pairing_denied()

        raw_credential = device._new_raw_token()
        now = fields.Datetime.now()
        credential_expires_at = device._credential_expiration_on_pair(now)
        new_version = device.credential_version + 1
        vals = {
            "credential_hash": device._hash_token(raw_credential),
            "credential_hint": raw_credential[-8:],
            "credential_created_at": now,
            "credential_expires_at": credential_expires_at,
            "credential_version": new_version,
            "paired_at": now,
            "paired_ip": ip_address,
            "paired_user_agent": (request.httprequest.headers.get("User-Agent") or "")[:512],
            "revoked_at": False,
            "revoked_by": False,
        }
        if legacy:
            vals.update({
                "token_revoked_at": now,
                "token_hash": False,
                "token_hint": False,
                "token_created_at": False,
            })
        else:
            vals["pairing_token_used_at"] = now
        device.write(vals)

        self._log(
            device=device,
            success=True,
            event="pairing_success",
            token=token,
            details="legacy_v1_link" if legacy else False,
        )

        response = request.redirect("/flexsys/pos/device/start", code=303)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return self._set_device_cookie(response, raw_credential, device)

    @http.route(
        "/flexsys/pos/device/start",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        sitemap=False,
        readonly=False,
    )
    def device_start(self, **kwargs):
        ip_address = self._client_ip()
        raw_credential = request.httprequest.cookies.get(_DEVICE_COOKIE, "")
        if not raw_credential or not _TOKEN_RE.fullmatch(raw_credential):
            self._log(success=False, event="invalid_credential")
            return self._device_denied(clear_cookie=True)

        credential_hash = hashlib.sha256(raw_credential.encode("utf-8")).hexdigest()
        device = request.env["flexsys.pos.device"].sudo().search([
            ("credential_hash", "=", credential_hash),
        ], limit=1)
        if not device:
            self._log(success=False, event="invalid_credential")
            return self._device_denied(clear_cookie=True)

        if not device.active:
            self._log(device=device, success=False, event="device_disabled")
            return self._device_denied(clear_cookie=True)
        if device.revoked_at:
            self._log(device=device, success=False, event="device_revoked")
            return self._device_denied(clear_cookie=True)
        if device._credential_is_expired():
            self._log(device=device, success=False, event="credential_expired")
            return self._device_denied(clear_cookie=True)
        if not device._ip_is_allowed(ip_address):
            self._log(device=device, success=False, event="ip_denied")
            return self._device_denied(clear_cookie=False)
        if not device._service_user_is_valid():
            self._log(device=device, success=False, event="user_invalid")
            return self._device_denied(clear_cookie=False)
        if (
            not device.pos_config_id.active
            or device.pos_config_id.company_id != device.company_id
            or not device.pos_config_id.module_pos_hr
        ):
            self._log(device=device, success=False, event="config_invalid")
            return self._device_denied(clear_cookie=False)

        now = fields.Datetime.now()
        request.env.cr.execute(
            """
            UPDATE flexsys_pos_device
               SET last_used_at = %s,
                   last_ip = %s,
                   access_count = COALESCE(access_count, 0) + 1,
                   write_date = %s
             WHERE id = %s
            """,
            (now, ip_address, now, device.id),
        )
        device.invalidate_recordset(["last_used_at", "last_ip", "access_count"])
        self._log(device=device, success=True, event="device_access_success")

        self._establish_device_session(device)
        response = request.redirect(f"/pos/ui/{device.pos_config_id.id}/login", code=303)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return self._refresh_device_cookie(response, raw_credential, device)

    @http.route(
        "/flexsys/pos/device/pin-success",
        type="jsonrpc",
        auth="user",
        methods=["POST"],
        readonly=False,
    )
    def pin_success(self, employee_id=None):
        device_id = request.session.get("flexsys_pos_device_id")
        version = request.session.get("flexsys_pos_device_credential_version")
        if not device_id or not employee_id:
            return False

        device = request.env["flexsys.pos.device"].sudo().browse(int(device_id)).exists()
        if (
            not device
            or not device.active
            or device.revoked_at
            or not device.credential_hash
            or device._credential_is_expired()
            or version != device.credential_version
            or device.service_user_id.id != request.env.user.id
        ):
            return False

        employee = request.env["hr.employee"].sudo().browse(int(employee_id)).exists()
        if not employee or employee.company_id != device.company_id or not employee.pin:
            return False

        now = fields.Datetime.now()
        device.sudo().write({
            "last_user_pin_success": employee.display_name,
            "last_user_pin_success_at": now,
        })
        self._log(device=device, employee=employee, success=True, event="pin_success")
        return True
