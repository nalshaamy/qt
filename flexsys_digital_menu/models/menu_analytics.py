import hashlib
from datetime import datetime, timedelta

import pytz

from odoo import api, fields, models


EVENT_TYPES = [
    ("menu_view", "Menu View"),
    ("product_open", "Product Open"),
    ("category_filter", "Category Filter"),
    ("search", "Search"),
    ("offer_open", "Offer Open"),
    ("banner_open", "Banner Open"),
    ("language_change", "Language Change"),
    ("branch_change", "Branch Change"),
]


class FlexSysMenuAnalyticsEvent(models.Model):
    _name = "flexsys.menu.analytics.event"
    _description = "FlexSys Digital Menu Analytics Event"
    _order = "event_at desc, id desc"

    menu_id = fields.Many2one("flexsys.menu", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="menu_id.company_id", store=True, readonly=True, index=True)
    event_type = fields.Selection(EVENT_TYPES, required=True, index=True)
    event_at = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    event_date = fields.Date(default=fields.Date.context_today, required=True, index=True)
    language = fields.Selection([("ar", "Arabic"), ("en", "English")], index=True)
    pos_config_id = fields.Many2one("pos.config", ondelete="set null", index=True)
    reference_key = fields.Char(index=True)
    reference_label = fields.Char(index=True)
    search_term = fields.Char(index=True)
    session_hash = fields.Char(index=True)

    @api.model
    def record_public_event(self, menu, event_type, payload):
        if not menu.analytics_enabled or event_type not in dict(EVENT_TYPES):
            return False
        language = payload.get("language") if payload.get("language") in ("ar", "en") else menu.default_language
        branch_key = (payload.get("branch") or "")[:32]
        branch = menu.resolve_branch_key(branch_key)
        reference_key = (payload.get("reference") or "")[:64]
        search_term = (payload.get("term") or "").strip()[:80]
        raw_session = (payload.get("session") or "")[:128]
        session_hash = hashlib.sha256(f"{menu.id}:{raw_session}".encode()).hexdigest()[:32] if raw_session else ""

        reference_label = ""
        if event_type == "product_open" and reference_key:
            record = self.env["flexsys.menu.product"].sudo().search([
                ("menu_id", "=", menu.id), ("public_key", "=", reference_key)
            ], limit=1)
            reference_label = record._effective_name() if record else ""
        elif event_type == "category_filter" and reference_key and reference_key != "all":
            record = self.env["flexsys.menu.category"].sudo().search([
                ("menu_id", "=", menu.id), ("public_key", "=", reference_key)
            ], limit=1)
            reference_label = record.name if record else ""
        elif event_type == "offer_open" and reference_key:
            record = self.env["flexsys.menu.offer"].sudo().search([
                ("menu_id", "=", menu.id), ("public_key", "=", reference_key)
            ], limit=1)
            reference_label = record.name if record else ""
        elif event_type == "banner_open" and reference_key:
            record = self.env["flexsys.menu.banner"].sudo().search([
                ("menu_id", "=", menu.id), ("public_key", "=", reference_key)
            ], limit=1)
            reference_label = record.name if record else ""

        if event_type == "menu_view" and session_hash:
            # Count one menu view per anonymous browser session per day to keep metrics useful and storage light.
            today = datetime.now(pytz.timezone(menu.timezone or "UTC")).date()
            existing = self.sudo().search_count([
                ("menu_id", "=", menu.id),
                ("event_type", "=", "menu_view"),
                ("event_date", "=", today),
                ("session_hash", "=", session_hash),
            ])
            if existing:
                return False

        return self.sudo().create({
            "menu_id": menu.id,
            "event_type": event_type,
            "event_date": datetime.now(pytz.timezone(menu.timezone or "UTC")).date(),
            "language": language,
            "pos_config_id": branch.id if branch else False,
            "reference_key": reference_key,
            "reference_label": reference_label[:160],
            "search_term": search_term if event_type == "search" else "",
            "session_hash": session_hash,
        })

    @api.model
    def _cron_cleanup_old_events(self):
        menus = self.env["flexsys.menu"].sudo().search([])
        now = fields.Datetime.now()
        for menu in menus:
            if menu.analytics_disabled:
                continue
            days = max(7, min(int(menu.analytics_retention_days or 90), 365))
            cutoff = now - timedelta(days=days)
            self.sudo().search([
                ("menu_id", "=", menu.id),
                ("event_at", "<", cutoff),
            ]).unlink()
        return True
