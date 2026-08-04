from odoo import fields, models


class FlexSysOperationsQrMenuCategory(models.Model):
    _name = 'flexsys.operations.menu.category'
    _description = 'Menu Category'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
