# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools import consteq
from odoo.tools.misc import DEFAULT_SERVER_DATETIME_FORMAT
from werkzeug.security import check_password_hash, generate_password_hash


class FlexSysOperationsManagerAccount(models.Model):
    _name = 'flexsys.operations.manager'
    _description = 'FlexSys Independent Manager Account'
    _rec_name = 'name'
    _order = 'name'

    name = fields.Char(required=True)
    login = fields.Char(required=True, index=True, copy=False)
    password_hash = fields.Char(copy=False)
    new_password = fields.Char(string='New Password', copy=False)
    # Legacy field kept temporarily for safe upgrades from earlier versions.
    pos_config_id = fields.Many2one(
        'pos.config',
        string='Legacy Assigned POS Branch',
        domain=[('operations_branch_enabled', '=', True)],
        ondelete='set null',
        copy=False,
    )
    pos_config_ids = fields.Many2many(
        'pos.config',
        'operations_manager_pos_config_rel',
        'manager_id',
        'pos_config_id',
        string='Assigned POS Branches',
        domain=[('operations_branch_enabled', '=', True)],
        help='The manager can view and manage only these POS branches.',
    )
    active = fields.Boolean(default=True)
    language = fields.Selection(selection=lambda self: self.env['res.lang'].get_installed(), default=lambda self: self.env.lang)
    can_view_dashboard = fields.Boolean(default=True)
    can_manage_store = fields.Boolean(default=True)
    last_login = fields.Datetime(readonly=True)
    session_token_hash = fields.Char(copy=False, readonly=True)
    session_expires_at = fields.Datetime(copy=False, readonly=True)

    _login_unique = models.Constraint(
        'UNIQUE(login)',
        'Manager login must be unique.',
    )

    @api.constrains('pos_config_ids', 'active')
    def _validate_assigned_branches(self):
        for record in self:
            if record.active and not record.pos_config_ids:
                raise ValidationError(_('An active manager account must be linked to at least one POS branch.'))
            if record.pos_config_ids.filtered(lambda pos: not pos.operations_branch_enabled):
                raise ValidationError(_('All assigned POS records must be enabled as QR branches.'))

    @api.constrains('login')
    def _check_login(self):
        for record in self:
            if record.login and len(record.login.strip()) < 3:
                raise ValidationError(_('Manager login must contain at least 3 characters.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            legacy_pos_id = vals.get('pos_config_id')
            if legacy_pos_id and not vals.get('pos_config_ids'):
                vals['pos_config_ids'] = [(6, 0, [legacy_pos_id])]
            password = vals.pop('new_password', False)
            if not password:
                raise ValidationError(_('A password is required for the manager account.'))
            if len(password) < 8:
                raise ValidationError(_('Manager password must contain at least 8 characters.'))
            vals['password_hash'] = generate_password_hash(password, method='pbkdf2:sha256:600000')
            vals['login'] = (vals.get('login') or '').strip().lower()
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        legacy_pos_id = vals.get('pos_config_id')
        if legacy_pos_id and 'pos_config_ids' not in vals:
            vals['pos_config_ids'] = [(6, 0, [legacy_pos_id])]
        password = vals.pop('new_password', False)
        if password:
            if len(password) < 8:
                raise ValidationError(_('Manager password must contain at least 8 characters.'))
            vals['password_hash'] = generate_password_hash(password, method='pbkdf2:sha256:600000')
            vals['session_token_hash'] = False
            vals['session_expires_at'] = False
        if 'login' in vals:
            vals['login'] = (vals.get('login') or '').strip().lower()
        return super().write(vals)

    def _ensure_branch_migration(self):
        for record in self:
            if not record.pos_config_ids and record.pos_config_id:
                record.sudo().write({'pos_config_ids': [(6, 0, [record.pos_config_id.id])]})
        return self

    def verify_password(self, password):
        self.ensure_one()
        return bool(
            self.active
            and self.password_hash
            and password
            and check_password_hash(self.password_hash, password)
        )

    def create_session(self, raw_token, hours=12):
        self.ensure_one()
        self.sudo().write({
            'session_token_hash': generate_password_hash(raw_token, method='pbkdf2:sha256:200000'),
            'session_expires_at': fields.Datetime.now() + timedelta(hours=hours),
            'last_login': fields.Datetime.now(),
        })

    def verify_session(self, raw_token):
        self.ensure_one()
        if not self.active or not raw_token or not self.session_token_hash:
            return False
        if not self.session_expires_at or self.session_expires_at <= fields.Datetime.now():
            return False
        return check_password_hash(self.session_token_hash, raw_token)

    def clear_session(self):
        self.sudo().write({
            'session_token_hash': False,
            'session_expires_at': False,
        })


class FlexSysPlatformBranchOperations(models.Model):
    _inherit = 'flexsys.platform.branch'

    operations_pos_config_ids = fields.Many2many(
        'pos.config',
        'flexsys_platform_branch_pos_config_rel',
        'branch_id',
        'pos_config_id',
        string='Operations POS Branches',
        domain=[('operations_branch_enabled', '=', True)],
        help='POS configurations available in Operations when this platform branch is active.',
    )


class FlexSysPlatformUserOperations(models.Model):
    _inherit = 'flexsys.platform.user'

    operations_pos_config_ids = fields.Many2many(
        'pos.config',
        compute='_compute_operations_access',
        string='Operations POS Branches',
    )
    can_view_dashboard = fields.Boolean(compute='_compute_operations_access')
    can_manage_store = fields.Boolean(compute='_compute_operations_access')

    @api.depends(
        'role_ids.permission_ids',
        'branch_ids',
        'branch_ids.operations_pos_config_ids',
    )
    def _compute_operations_access(self):
        for user in self:
            permission_codes = set(
                user.role_ids.permission_ids.filtered('active').mapped('code')
            )
            user.operations_pos_config_ids = user.branch_ids.mapped(
                'operations_pos_config_ids'
            )
            user.can_view_dashboard = 'operations.access' in permission_codes
            user.can_manage_store = (
                'operations.manage_store' in permission_codes
                or 'platform.admin' in permission_codes
            )

    @property
    def pos_config_ids(self):
        """Compatibility alias used by the existing Operations controllers."""
        self.ensure_one()
        return self.operations_pos_config_ids

    def _ensure_branch_migration(self):
        """Compatibility method for the legacy manager-account interface."""
        return self

    def clear_session(self):
        """Close all active platform sessions for this user."""
        self.ensure_one()
        self.env['flexsys.platform.session'].sudo().search([
            ('user_id', '=', self.id),
            ('active', '=', True),
        ]).close()
