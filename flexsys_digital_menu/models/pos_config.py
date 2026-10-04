from datetime import datetime
from urllib.parse import urlparse

import pytz

from odoo import api, fields, models
from odoo.exceptions import ValidationError


WEEKDAYS = [
    ("0", "Monday"),
    ("1", "Tuesday"),
    ("2", "Wednesday"),
    ("3", "Thursday"),
    ("4", "Friday"),
    ("5", "Saturday"),
    ("6", "Sunday"),
]


class PosConfig(models.Model):
    _inherit = "pos.config"

    digital_menu_public_name = fields.Char(translate=True, string="Public Branch Name")
    digital_menu_description = fields.Text(translate=True, string="Branch Description")
    digital_menu_address = fields.Char(translate=True, string="Public Address")
    digital_menu_phone = fields.Char(string="Public Phone")
    digital_menu_whatsapp = fields.Char(string="WhatsApp")
    digital_menu_map_url = fields.Char(string="Map URL")
    digital_menu_latitude = fields.Float(digits=(10, 7), string="Latitude")
    digital_menu_longitude = fields.Float(digits=(10, 7), string="Longitude")
    digital_menu_image = fields.Image(max_width=1600, max_height=1200, string="Branch Image")
    digital_menu_hour_ids = fields.One2many(
        "flexsys.menu.branch.hour", "pos_config_id", string="Working Hours"
    )

    def _digital_menu_public_name(self):
        self.ensure_one()
        operations_name = self.operations_branch_name if "operations_branch_name" in self._fields else ""
        return self.digital_menu_public_name or operations_name or self.name

    @api.constrains("digital_menu_map_url")
    def _check_digital_menu_map_url(self):
        for pos in self:
            value = (pos.digital_menu_map_url or "").strip()
            if value and urlparse(value).scheme not in ("http", "https"):
                raise ValidationError("Digital Menu Map URL must use http or https.")

    def _digital_menu_map_link(self):
        self.ensure_one()
        if self.digital_menu_map_url:
            return self.digital_menu_map_url.strip()
        latitude = self.digital_menu_latitude
        longitude = self.digital_menu_longitude
        if not (latitude or longitude) and "operations_latitude" in self._fields and "operations_longitude" in self._fields:
            latitude = self.operations_latitude
            longitude = self.operations_longitude
        if latitude or longitude:
            return (
                "https://www.google.com/maps/search/?api=1&query="
                f"{latitude},{longitude}"
            )
        return ""

    def _digital_menu_open_status(self, tz_name=None):
        self.ensure_one()
        hours = self.digital_menu_hour_ids
        if not hours:
            if "operations_branch_is_open" in self._fields:
                return bool(self.operations_branch_is_open)
            return None
        tz = pytz.timezone(tz_name or self.company_id.partner_id.tz or self.env.user.tz or "UTC")
        now = datetime.now(tz)
        weekday = str(now.weekday())
        previous_weekday = str((now.weekday() - 1) % 7)
        day_hours = hours.filtered(lambda line: line.weekday == weekday).sorted("sequence")
        overnight = hours.filtered(
            lambda line: line.weekday == previous_weekday and not line.closed and line.time_from > line.time_to
        ).sorted("sequence")
        candidates = day_hours | overnight
        if not candidates:
            return False
        return any(line.is_open_at(now) for line in candidates)


class FlexSysMenuBranchHour(models.Model):
    _name = "flexsys.menu.branch.hour"
    _description = "FlexSys Digital Menu Branch Working Hour"
    _order = "weekday, sequence, time_from"

    pos_config_id = fields.Many2one("pos.config", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="pos_config_id.company_id", store=True, readonly=True, index=True)
    weekday = fields.Selection(WEEKDAYS, required=True, default="0")
    sequence = fields.Integer(default=10)
    closed = fields.Boolean(default=False)
    time_from = fields.Float(default=8.0, help="Local time, decimal hours.")
    time_to = fields.Float(default=23.0, help="Local time, decimal hours. Crossing midnight is supported.")

    @api.constrains("time_from", "time_to")
    def _check_times(self):
        for line in self:
            if not (0 <= line.time_from <= 24 and 0 <= line.time_to <= 24):
                raise ValidationError("Working hours must be between 0 and 24.")

    def is_open_at(self, local_dt):
        self.ensure_one()
        if self.closed:
            return False
        current = local_dt.hour + local_dt.minute / 60.0 + local_dt.second / 3600.0
        start = self.time_from
        stop = self.time_to
        if start == stop:
            return True
        if start < stop:
            return start <= current < stop
        return current >= start or current < stop
