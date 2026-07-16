# -*- coding: utf-8 -*-
from odoo import fields, models


class QtCafeTable(models.Model):
    _name = 'qtcafe.table'
    _description = 'QT Cafe Table'
    _order = 'pos_config_id, sequence, name'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    pos_config_id = fields.Many2one(
        'pos.config',
        string='POS Branch',
        required=True,
        ondelete='cascade',
        domain=[('qtcafe_branch_enabled', '=', True)],
        index=True,
    )
