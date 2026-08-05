# -*- coding: utf-8 -*-
from odoo import fields, models


class FlexSysOperationsTable(models.Model):
    _name = 'flexsys.operations.table'
    _description = 'FlexSys Table'
    _order = 'pos_config_id, sequence, name'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    pos_config_id = fields.Many2one(
        'pos.config',
        string='POS Branch',
        required=True,
        ondelete='cascade',
        domain=[('operations_branch_enabled', '=', True)],
        index=True,
    )
