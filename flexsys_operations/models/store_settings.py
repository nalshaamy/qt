# -*- coding: utf-8 -*-
from odoo import api, fields, models


class QtCafeStoreSettings(models.Model):
    _name = 'qtcafe.store.settings'
    _description = 'QT Cafe Store Settings'
    _rec_name = 'name'

    name = fields.Char(default='QT Cafe Store', required=True)
    is_open = fields.Boolean(string='Store Open', default=True)
    closed_message = fields.Char(
        string='Closed Message',
        default='المتجر مغلق حاليًا، نعود لخدمتكم قريبًا.',
    )
    reopen_at = fields.Datetime(string='Expected Reopen Time')
    allow_browse_when_closed = fields.Boolean(
        string='Allow Menu Browsing While Closed',
        default=True,
    )

    @api.model
    def get_settings(self):
        settings = self.sudo().search([], limit=1)
        if not settings:
            settings = self.sudo().create({})
        return settings
