import base64
import mimetypes
import uuid
from datetime import datetime
from urllib.parse import urlparse

import pytz

from odoo import api, fields, models
from odoo.exceptions import ValidationError


_ALLOWED_EXTENSIONS = {
    "image": {".jpg", ".jpeg", ".png", ".webp"},
    "animated": {".gif", ".webp"},
    "video": {".mp4", ".webm"},
}
_MAX_MEDIA_BYTES = 25 * 1024 * 1024


class FlexSysMenuBanner(models.Model):
    _name = "flexsys.menu.banner"
    _description = "FlexSys Digital Menu Promotional Banner"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True, string="Banner Name")
    sequence = fields.Integer(default=10)
    is_published = fields.Boolean(default=True, string="Published")
    menu_id = fields.Many2one("flexsys.menu", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="menu_id.company_id", store=True, readonly=True, index=True)

    media_type = fields.Selection(
        [("image", "Image"), ("animated", "Animated Image"), ("video", "Video")],
        default="image",
        required=True,
        string="Media Type",
    )
    desktop_media = fields.Binary(attachment=True, string="Desktop Media")
    desktop_filename = fields.Char(string="Desktop Filename")
    mobile_media = fields.Binary(attachment=True, string="Mobile Media Override")
    mobile_filename = fields.Char(string="Mobile Filename")
    fit_mode = fields.Selection(
        [("contain", "Contain"), ("cover", "Cover")],
        default="contain",
        required=True,
        string="Banner Fit",
    )
    alt_text = fields.Char(translate=True, string="Alt Text")
    click_url = fields.Char(string="Click URL")
    open_new_tab = fields.Boolean(default=False, string="Open Link in New Tab")

    start_date = fields.Date()
    end_date = fields.Date()
    schedule_ids = fields.Many2many(
        "flexsys.menu.schedule",
        "flexsys_menu_banner_schedule_rel",
        "banner_id",
        "schedule_id",
        string="Schedules",
    )
    public_key = fields.Char(default=lambda self: uuid.uuid4().hex[:16], required=True, copy=False, index=True)

    _public_key_unique = models.Constraint(
        "unique(public_key)",
        "Banner public key must be unique.",
    )

    @api.constrains("start_date", "end_date")
    def _check_dates(self):
        for banner in self:
            if banner.start_date and banner.end_date and banner.start_date > banner.end_date:
                raise ValidationError("Banner start date cannot be after end date.")

    @api.constrains("desktop_media", "desktop_filename", "mobile_media", "mobile_filename", "media_type", "is_published")
    def _check_media(self):
        for banner in self:
            if banner.is_published and not banner.desktop_media:
                raise ValidationError("A published banner requires desktop media.")
            banner._validate_media_value(banner.desktop_media, banner.desktop_filename, "desktop")
            banner._validate_media_value(banner.mobile_media, banner.mobile_filename, "mobile")

    @api.constrains("click_url")
    def _check_click_url(self):
        for banner in self:
            value = (banner.click_url or "").strip()
            if not value:
                continue
            if value.startswith("/") and not value.startswith("//"):
                continue
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValidationError("Banner click URL must be an absolute http(s) URL or a relative path starting with '/'.")

    @api.constrains("menu_id", "schedule_ids")
    def _check_company_consistency(self):
        for banner in self:
            if any(schedule.company_id and schedule.company_id != banner.company_id for schedule in banner.schedule_ids):
                raise ValidationError("Banner schedules must belong to the menu company or be shared.")

    def _validate_media_value(self, value, filename, label):
        self.ensure_one()
        if not value:
            return
        try:
            raw = base64.b64decode(value)
        except Exception as exc:
            raise ValidationError(f"Invalid {label} banner media.") from exc
        if len(raw) > _MAX_MEDIA_BYTES:
            raise ValidationError("Banner media must not exceed 25 MB per file.")
        suffix = ""
        if filename and "." in filename:
            suffix = "." + filename.rsplit(".", 1)[-1].lower()
        allowed = _ALLOWED_EXTENSIONS.get(self.media_type, set())
        if suffix and suffix not in allowed:
            raise ValidationError(
                f"Unsupported {label} file for {dict(self._fields['media_type'].selection).get(self.media_type)} banner."
            )

    def is_active_now(self, preview=False):
        self.ensure_one()
        if not self.is_published and not preview:
            return False
        tz = pytz.timezone(self.menu_id.timezone or "UTC")
        today = datetime.now(tz).date()
        if self.start_date and today < self.start_date:
            return False
        if self.end_date and today > self.end_date:
            return False
        if self.schedule_ids and not any(schedule.is_active_at(tz_name=self.menu_id.timezone) for schedule in self.schedule_ids):
            return False
        return bool(self.desktop_media)

    def media_mimetype(self, mobile=False):
        self.ensure_one()
        filename = self.mobile_filename if mobile and self.mobile_media else self.desktop_filename
        guessed = mimetypes.guess_type(filename or "")[0]
        if guessed:
            return guessed
        if self.media_type == "video":
            return "video/mp4"
        if self.media_type == "animated":
            return "image/webp"
        return "image/jpeg"
