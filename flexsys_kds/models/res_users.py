# -*- coding: utf-8 -*-
from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    kds_station_ids = fields.Many2many(
        'kds.station', 'kds_station_user_rel', 'user_id', 'station_id',
        string='FlexSys KDS Stations')
