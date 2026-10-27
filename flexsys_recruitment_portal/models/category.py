from odoo import fields, models


class CareerCategory(models.Model):
    _name = 'flexsys.career.category'
    _description = 'General Career Category'
    _order = 'sequence, name, id'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', ondelete='cascade', required=True, default=lambda self: self.env.company)
    description = fields.Text(translate=True)
