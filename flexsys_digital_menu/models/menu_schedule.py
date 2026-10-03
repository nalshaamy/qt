from datetime import datetime, time

import pytz

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class FlexSysMenuSchedule(models.Model):
    _name = "flexsys.menu.schedule"
    _description = "FlexSys Digital Menu Schedule"
    _order = "name"

    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", index=True)
    date_from = fields.Date()
    date_to = fields.Date()
    time_from = fields.Float(default=0.0, help="Local time, decimal hours.")
    time_to = fields.Float(default=24.0, help="Local time, decimal hours. Values crossing midnight are supported.")
    monday = fields.Boolean(default=True)
    tuesday = fields.Boolean(default=True)
    wednesday = fields.Boolean(default=True)
    thursday = fields.Boolean(default=True)
    friday = fields.Boolean(default=True)
    saturday = fields.Boolean(default=True)
    sunday = fields.Boolean(default=True)

    @api.constrains("date_from", "date_to", "time_from", "time_to")
    def _check_schedule(self):
        for record in self:
            if record.date_from and record.date_to and record.date_from > record.date_to:
                raise ValidationError("Start date cannot be after end date.")
            if not (0 <= record.time_from <= 24 and 0 <= record.time_to <= 24):
                raise ValidationError("Schedule hours must be between 0 and 24.")

    def is_active_at(self, moment=None, tz_name=None):
        self.ensure_one()
        if not self.active:
            return False
        tz_name = tz_name or self.env.company.partner_id.tz or self.env.user.tz or "UTC"
        tz = pytz.timezone(tz_name)
        if moment is None:
            local_dt = datetime.now(tz)
        else:
            if moment.tzinfo is None:
                moment = pytz.UTC.localize(moment)
            local_dt = moment.astimezone(tz)

        local_date = local_dt.date()
        if self.date_from and local_date < self.date_from:
            return False
        if self.date_to and local_date > self.date_to:
            return False

        weekday_flags = [
            self.monday, self.tuesday, self.wednesday, self.thursday,
            self.friday, self.saturday, self.sunday,
        ]
        if not weekday_flags[local_dt.weekday()]:
            return False

        current = local_dt.hour + local_dt.minute / 60.0 + local_dt.second / 3600.0
        start = self.time_from
        stop = self.time_to
        if start == stop:
            return True
        if start < stop:
            return start <= current < stop
        return current >= start or current < stop
