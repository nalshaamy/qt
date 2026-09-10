"""Confinement for FlexSys POS device-authenticated Odoo sessions."""

import logging

from odoo import http
from odoo.http import request
from odoo.addons.point_of_sale.controllers.main import PosController
from odoo.addons.web.controllers.home import Home

_logger = logging.getLogger(__name__)


def _device_session_binding():
    """Return (device, stale_binding).

    A stale binding must never fall through to normal Backend behaviour because
    the authenticated user is a technical POS service user. Reset/Revoke or a
    credential version change therefore invalidates already-open POS sessions.
    """
    device_id = request.session.get("flexsys_pos_device_id")
    if not device_id:
        return False, False

    try:
        device_id = int(device_id)
    except (TypeError, ValueError):
        return False, True

    if not request.session.uid or not request.db:
        return False, True

    device = request.env["flexsys.pos.device"].sudo().browse(device_id).exists()
    if not device:
        return False, True

    version = request.session.get("flexsys_pos_device_credential_version")
    valid = bool(
        device.active
        and not device.revoked_at
        and device.credential_hash
        and not device._credential_is_expired()
        and device.service_user_id.id == request.session.uid
        and version == device.credential_version
    )
    return device, not valid


def _bound_pos_url(device):
    return f"/pos/ui/{device.pos_config_id.id}/login"


def _audit_block(device, event, details=None):
    try:
        if not device:
            return
        with request.env.cr.savepoint():
            request.env["flexsys.pos.device.access.log"].sudo().create({
                "device_id": device.id,
                "pos_config_id": device.pos_config_id.id,
                "company_id": device.company_id.id,
                "service_user_id": device.service_user_id.id,
                "actor_user_id": request.env.user.id,
                "success": False,
                "event": event,
                "ip_address": request.httprequest.remote_addr or "",
                "user_agent": (request.httprequest.headers.get("User-Agent") or "")[:512],
                "details": (details or "")[:1000],
            })
    except Exception:
        _logger.exception("FlexSys POS Device Access could not write guard audit event %s", event)


def _stale_redirect(device):
    _audit_block(device, "stale_session_blocked", details="Device session invalidated by reset/revoke/version change")
    request.session.logout(keep_db=True)
    response = request.redirect("/flexsys/pos/device/start", code=303)
    response.headers["Cache-Control"] = "no-store"
    return response


class FlexSysWebClientDeviceGuard(Home):
    @http.route()
    def web_client(self, s_action=None, **kw):
        device, stale = _device_session_binding()
        if stale:
            return _stale_redirect(device)
        if device:
            _audit_block(device, "backend_blocked", details="Backend navigation blocked")
            response = request.redirect(_bound_pos_url(device), code=303)
            response.headers["Cache-Control"] = "no-store"
            return response
        return super().web_client(s_action=s_action, **kw)


class FlexSysPosConfigDeviceGuard(PosController):
    @http.route()
    def pos_web(self, config_id=False, from_backend=False, subpath=None, **k):
        device, stale = _device_session_binding()
        if stale:
            return _stale_redirect(device)
        if device:
            bound_config_id = device.pos_config_id.id
            try:
                requested_config_id = int(config_id) if config_id else False
            except (TypeError, ValueError):
                requested_config_id = False
            if requested_config_id != bound_config_id:
                _audit_block(
                    device,
                    "pos_switch_blocked",
                    details=f"Requested POS config {str(config_id)[:100]}; bound POS config {bound_config_id}",
                )
                response = request.redirect(_bound_pos_url(device), code=303)
                response.headers["Cache-Control"] = "no-store"
                return response
        return super().pos_web(config_id=config_id, from_backend=from_backend, subpath=subpath, **k)
