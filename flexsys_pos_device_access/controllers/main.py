import hashlib
import logging
import re
from datetime import timedelta

from odoo import fields, http
from odoo.http import request

_logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,160}$")


class FlexSysPosDeviceAccessController(http.Controller):
    """Public device-token gateway.

    The token authenticates the *device*. It deliberately does not identify
    the cashier. The target URL remains /pos/ui/<config_id>/login so Odoo's
    native employee/PIN unlock screen stays in the flow.
    """

    def _client_ip(self):
        # Odoo's HTTP stack applies ProxyFix. remote_addr is therefore the
        # preferred value instead of trusting arbitrary X-Forwarded-For input.
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
            ("success", "=", False),
            ("create_date", ">=", since),
        ])
        return failed >= max_failed

    def _log(self, *, device=None, employee=None, success=False, event="invalid_token", token=""):
        vals = {
            "device_id": device.id if device else False,
            "pos_config_id": device.pos_config_id.id if device else False,
            "company_id": device.company_id.id if device else False,
            "service_user_id": device.service_user_id.id if device else False,
            "employee_id": employee.id if employee else False,
            "success": success,
            "event": event,
            "ip_address": self._client_ip(),
            "user_agent": (request.httprequest.headers.get("User-Agent") or "")[:512],
            "token_fingerprint": self._token_fingerprint(token),
        }
        request.env["flexsys.pos.device.access.log"].sudo().create(vals)

    def _generic_not_found(self):
        # Keep failure responses intentionally generic so the public endpoint
        # does not reveal whether a device, POS, user or token exists.
        # Odoo 19's request.not_found() returns a NotFound HTTP exception, not
        # a mutable Response object, so headers must be set on a real response.
        response = request.make_response("Not Found", status=404)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def _establish_device_session(self, device):
        """Create the technical-user session through Odoo's native finalizer.

        The device token authenticates the device; it never authenticates the
        cashier.  We intentionally reuse ``Session.finalize()`` instead of
        manually reproducing Odoo's session internals.  This keeps the module
        aligned with the exact Odoo 19 session implementation running on the
        server (session token, context and rotation included).
        """
        user = device.service_user_id.sudo()
        session = request.session

        # A device URL must deterministically select its dedicated technical
        # user rather than inherit an existing browser login.
        session.logout(keep_db=True)

        # Session.finalize() is Odoo's native conversion from a pre-session to
        # an authenticated session.  The Secure Device Token is our custom
        # authentication factor, so we populate only the two pre-session values
        # that finalize() expects; no Odoo password is stored or exposed.
        session["pre_login"] = user.login
        session["pre_uid"] = user.id
        session.finalize(request.env)

        # Keep the device binding in the authenticated session for PIN-success
        # auditing.  Never place the raw device token in the session.
        session["flexsys_pos_device_id"] = device.id
        session.touch()

        # The current request started as auth='public'; switch its environment
        # to the now-authenticated technical user before redirect/post-dispatch.
        request.update_env(user=session.uid, context=session.context, su=False)

    @http.route(
        "/flexsys/pos/device/<string:token>",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        sitemap=False,
        readonly=False,
    )
    def device_entry(self, token, **kwargs):
        ip_address = self._client_ip()
        if self._is_rate_limited(ip_address):
            _logger.warning("FlexSys POS device access rate limited for IP %s", ip_address)
            response = request.make_response("Too Many Requests", status=429)
            response.headers["Cache-Control"] = "no-store"
            response.headers["Retry-After"] = "60"
            return response

        if not token or not _TOKEN_RE.fullmatch(token):
            self._log(success=False, event="invalid_token", token=token)
            return self._generic_not_found()

        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        device = request.env["flexsys.pos.device"].sudo().search([
            ("token_hash", "=", token_hash),
        ], limit=1)

        if not device:
            self._log(success=False, event="invalid_token", token=token)
            return self._generic_not_found()

        if not device.active or not device.token_hash:
            self._log(device=device, success=False, event="inactive", token=token)
            return self._generic_not_found()

        if device._token_is_expired():
            self._log(device=device, success=False, event="expired", token=token)
            return self._generic_not_found()

        if not device._ip_is_allowed(ip_address):
            self._log(device=device, success=False, event="ip_denied", token=token)
            return self._generic_not_found()

        if not device._service_user_is_valid():
            self._log(device=device, success=False, event="user_invalid", token=token)
            return self._generic_not_found()

        if (
            not device.pos_config_id.active
            or device.pos_config_id.company_id != device.company_id
            or not device.pos_config_id.module_pos_hr
        ):
            self._log(device=device, success=False, event="config_invalid", token=token)
            return self._generic_not_found()

        now = fields.Datetime.now()
        # SQL increment avoids losing concurrent increments if the same device
        # link is opened twice at nearly the same time.
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
        self._log(device=device, success=True, event="success", token=token)

        self._establish_device_session(device)

        target = f"/pos/ui/{device.pos_config_id.id}/login"
        response = request.redirect(target, code=303)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @http.route(
        "/flexsys/pos/device/pin-success",
        type="jsonrpc",
        auth="user",
        methods=["POST"],
        readonly=False,
    )
    def pin_success(self, employee_id=None):
        """Audit a successful native POS employee PIN verification.

        The POS frontend calls this only after pos_hr has accepted the PIN.
        This endpoint never receives or stores the PIN itself.
        """
        device_id = request.session.get("flexsys_pos_device_id")
        if not device_id or not employee_id:
            return False

        device = request.env["flexsys.pos.device"].sudo().browse(int(device_id)).exists()
        if not device or not device.active or device.service_user_id.id != request.env.user.id:
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
