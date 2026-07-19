from passlib.context import CryptContext

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_password_context = CryptContext(schemes=['pbkdf2_sha512'], deprecated='auto')


class FlexsysInventoryManager(models.Model):
    _name = 'flexsys.inventory.manager'
    _description = 'Independent Inventory Manager'
    _order = 'name'

    name = fields.Char(required=True, translate=True)
    email = fields.Char(required=True, index=True)
    password = fields.Char(string='Password', copy=False, store=False)
    password_hash = fields.Char(copy=False, groups='base.group_system')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
    )
    warehouse_id = fields.Many2one(
        'stock.warehouse', required=True,
        domain="[('company_id', '=', company_id)]",
    )
    can_view_stock = fields.Boolean(default=True)
    can_view_moves = fields.Boolean(default=True)
    can_view_transfers = fields.Boolean(default=True)
    last_login = fields.Datetime(readonly=True)

    _email_unique = models.Constraint(
        'UNIQUE(email)',
        'The manager email must be unique.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            password = vals.pop('password', False)
            vals['email'] = (vals.get('email') or '').strip().lower()
            if not password:
                raise ValidationError(_('A password is required.'))
            self._validate_password(password)
            vals['password_hash'] = _password_context.hash(password)
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        password = vals.pop('password', False)
        if 'email' in vals:
            vals['email'] = (vals.get('email') or '').strip().lower()
        if password:
            self._validate_password(password)
            vals['password_hash'] = _password_context.hash(password)
        return super().write(vals)

    @api.constrains('warehouse_id', 'company_id')
    def _check_warehouse_company(self):
        for manager in self:
            if manager.warehouse_id.company_id != manager.company_id:
                raise ValidationError(_('The warehouse must belong to the selected company.'))

    @api.model
    def _validate_password(self, password):
        if len(password or '') < 8:
            raise ValidationError(_('The password must contain at least 8 characters.'))

    def check_password(self, password):
        self.ensure_one()
        return bool(self.password_hash and _password_context.verify(password or '', self.password_hash))
