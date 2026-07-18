from odoo import fields, models


class QtCafeQrMenuCategory(models.Model):
    _name = 'qtcafe.qr.menu.category'
    _description = 'QT Cafe QR Menu Category'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
