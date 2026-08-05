# -*- coding: utf-8 -*-
from datetime import timedelta
import secrets

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError
from werkzeug.security import check_password_hash, generate_password_hash


class FlexSysPlatformPermission(models.Model):
    _name = 'flexsys.platform.permission'
    _description = 'FlexSys Platform Permission'
    _order = 'application_code, code'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, index=True)
    application_code = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)

    _code_unique = models.Constraint('UNIQUE(code)', 'Permission code must be unique.')

    @api.model
    def _ensure_seed_data(self):
        """Create or update stable platform seed data without duplicates."""
        permission_model = self.sudo()
        role_model = self.env['flexsys.platform.role'].sudo()
        xmlid_model = self.env['ir.model.data'].sudo()

        seed_permissions = (
            ('permission_platform_access', 'Access Platform', 'platform.access', 'platform'),
            ('permission_operations_access', 'Access Operations', 'operations.access', 'operations'),
        )
        permission_records = {}
        for xml_name, name, code, application_code in seed_permissions:
            record = permission_model.search([('code', '=', code)], limit=1)
            values = {
                'name': name,
                'code': code,
                'application_code': application_code,
                'active': True,
            }
            if record:
                record.write(values)
            else:
                record = permission_model.create(values)
            permission_records[code] = record
            self._bind_seed_xmlid(xmlid_model, xml_name, record)

        role = role_model.search([('code', '=', 'platform_admin')], limit=1)
        role_values = {
            'name': 'Platform Administrator',
            'code': 'platform_admin',
            'active': True,
            'permission_ids': [(6, 0, [
                permission_records['platform.access'].id,
                permission_records['operations.access'].id,
            ])],
        }
        if role:
            role.write(role_values)
        else:
            role = role_model.create(role_values)
        self._bind_seed_xmlid(xmlid_model, 'role_platform_admin', role)
        return True

    @api.model
    def _bind_seed_xmlid(self, xmlid_model, xml_name, record):
        xmlid = xmlid_model.search([
            ('module', '=', 'flexsys_platform'),
            ('name', '=', xml_name),
        ], limit=1)
        values = {
            'module': 'flexsys_platform',
            'name': xml_name,
            'model': record._name,
            'res_id': record.id,
            'noupdate': True,
        }
        if xmlid:
            xmlid.write(values)
        else:
            xmlid_model.create(values)



class FlexSysPlatformRole(models.Model):
    _name = 'flexsys.platform.role'
    _description = 'FlexSys Platform Role'
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    permission_ids = fields.Many2many(
        'flexsys.platform.permission',
        'flexsys_platform_role_permission_rel',
        'role_id', 'permission_id',
        string='Permissions',
    )

    _code_unique = models.Constraint('UNIQUE(code)', 'Role code must be unique.')


class FlexSysPlatformBranch(models.Model):
    _name = 'flexsys.platform.branch'
    _description = 'FlexSys Platform Branch'
    _order = 'company_id, sequence, name'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, index=True)
    company_id = fields.Many2one('res.company', required=True, index=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    timezone = fields.Selection(related='company_id.partner_id.tz', readonly=False)

    _company_code_unique = models.Constraint(
        'UNIQUE(company_id, code)',
        'Branch code must be unique within the company.',
    )


class FlexSysPlatformUser(models.Model):
    _name = 'flexsys.platform.user'
    _description = 'FlexSys Platform User'
    _rec_name = 'name'
    _order = 'name'

    name = fields.Char(required=True)
    login = fields.Char(required=True, index=True, copy=False)
    email = fields.Char(index=True)
    password_hash = fields.Char(copy=False)
    new_password = fields.Char(string='New Password', copy=False)
    active = fields.Boolean(default=True)
    language = fields.Selection(selection=lambda self: self.env['res.lang'].get_installed(), default=lambda self: self.env.lang)
    timezone = fields.Selection(selection=lambda self: self._tz_get(), default=lambda self: self.env.user.tz or 'UTC')
    role_ids = fields.Many2many('flexsys.platform.role', string='Roles')
    company_ids = fields.Many2many('res.company', string='Allowed Companies')
    branch_ids = fields.Many2many('flexsys.platform.branch', string='Allowed Branches')
    default_company_id = fields.Many2one('res.company', string='Default Company')
    default_branch_id = fields.Many2one('flexsys.platform.branch', string='Default Branch')
    last_login = fields.Datetime(readonly=True)
    session_token_hash = fields.Char(copy=False, readonly=True)
    session_expires_at = fields.Datetime(copy=False, readonly=True)

    _login_unique = models.Constraint('UNIQUE(login)', 'Platform user login must be unique.')

    @api.model
    def _tz_get(self):
        return [(tz, tz) for tz in __import__('pytz').all_timezones]

    @api.constrains('default_company_id', 'company_ids')
    def _check_default_company(self):
        for rec in self:
            if rec.default_company_id and rec.default_company_id not in rec.company_ids:
                raise ValidationError(_('Default company must be one of the allowed companies.'))

    @api.constrains('default_branch_id', 'branch_ids', 'default_company_id')
    def _check_default_branch(self):
        for rec in self:
            if rec.default_branch_id and rec.default_branch_id not in rec.branch_ids:
                raise ValidationError(_('Default branch must be one of the allowed branches.'))
            if rec.default_branch_id and rec.default_company_id and rec.default_branch_id.company_id != rec.default_company_id:
                raise ValidationError(_('Default branch must belong to the default company.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            password = vals.pop('new_password', False)
            if not password or len(password) < 8:
                raise ValidationError(_('A password of at least 8 characters is required.'))
            vals['login'] = (vals.get('login') or '').strip().lower()
            vals['password_hash'] = generate_password_hash(password, method='pbkdf2:sha256:600000')
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        password = vals.pop('new_password', False)
        if password:
            if len(password) < 8:
                raise ValidationError(_('Password must contain at least 8 characters.'))
            vals.update({
                'password_hash': generate_password_hash(password, method='pbkdf2:sha256:600000'),
                'session_token_hash': False,
                'session_expires_at': False,
            })
        if 'login' in vals:
            vals['login'] = (vals.get('login') or '').strip().lower()
        return super().write(vals)

    def verify_password(self, password):
        self.ensure_one()
        return bool(self.active and password and self.password_hash and check_password_hash(self.password_hash, password))

    def create_session(self, hours=12):
        self.ensure_one()
        raw_token = secrets.token_urlsafe(32)
        self.sudo().write({
            'session_token_hash': generate_password_hash(raw_token, method='pbkdf2:sha256:200000'),
            'session_expires_at': fields.Datetime.now() + timedelta(hours=hours),
            'last_login': fields.Datetime.now(),
        })
        return raw_token

    def verify_session(self, raw_token):
        self.ensure_one()
        return bool(
            self.active and raw_token and self.session_token_hash
            and self.session_expires_at and self.session_expires_at > fields.Datetime.now()
            and check_password_hash(self.session_token_hash, raw_token)
        )

    def has_permission(self, code):
        self.ensure_one()
        return code in self.role_ids.permission_ids.filtered('active').mapped('code')


class FlexSysPlatformSession(models.Model):
    _name = 'flexsys.platform.session'
    _description = 'FlexSys Platform Session'
    _order = 'last_activity_at desc, id desc'

    user_id = fields.Many2one(
        'flexsys.platform.user', required=True, index=True, ondelete='cascade'
    )
    token_hash = fields.Char(required=True, copy=False, readonly=True)
    expires_at = fields.Datetime(required=True, index=True, readonly=True)
    last_activity_at = fields.Datetime(default=fields.Datetime.now, index=True, readonly=True)
    company_id = fields.Many2one('res.company', required=True, index=True, ondelete='cascade')
    branch_id = fields.Many2one('flexsys.platform.branch', index=True, ondelete='set null')
    ip_address = fields.Char(readonly=True)
    user_agent = fields.Char(readonly=True)
    active = fields.Boolean(default=True, index=True)

    @api.constrains('company_id', 'branch_id', 'user_id')
    def _check_context_scope(self):
        for rec in self:
            if rec.company_id not in rec.user_id.company_ids:
                raise ValidationError(_('Session company is not allowed for this user.'))
            if rec.branch_id:
                if rec.branch_id not in rec.user_id.branch_ids:
                    raise ValidationError(_('Session branch is not allowed for this user.'))
                if rec.branch_id.company_id != rec.company_id:
                    raise ValidationError(_('Session branch must belong to the selected company.'))

    @api.model
    def create_for_user(self, user, *, hours=12, company=None, branch=None, ip_address=None, user_agent=None):
        user.ensure_one()
        allowed_companies = user.company_ids.filtered('active')
        if not allowed_companies:
            raise ValidationError(_('At least one allowed company is required.'))

        requested_company = company or user.default_company_id
        company = requested_company if requested_company in allowed_companies else allowed_companies[:1]

        allowed_branches = user.branch_ids.filtered(
            lambda item: item.active and item.company_id == company
        )
        requested_branch = branch or user.default_branch_id
        branch = requested_branch if requested_branch in allowed_branches else allowed_branches[:1]
        raw_token = secrets.token_urlsafe(32)
        session = self.sudo().create({
            'user_id': user.id,
            'token_hash': generate_password_hash(raw_token, method='pbkdf2:sha256:200000'),
            'expires_at': fields.Datetime.now() + timedelta(hours=hours),
            'company_id': company.id,
            'branch_id': branch.id if branch else False,
            'ip_address': ip_address,
            'user_agent': user_agent,
        })
        user.sudo().write({'last_login': fields.Datetime.now()})
        return session, raw_token

    def verify_token(self, raw_token):
        self.ensure_one()
        return bool(
            self.active and raw_token and self.token_hash
            and self.expires_at > fields.Datetime.now()
            and check_password_hash(self.token_hash, raw_token)
        )

    def touch(self):
        self.ensure_one()
        now = fields.Datetime.now()
        if not self.last_activity_at or (now - self.last_activity_at).total_seconds() >= 60:
            self.sudo().write({'last_activity_at': now})

    def set_context(self, company, branch=None):
        self.ensure_one()
        values = {'company_id': company.id, 'branch_id': branch.id if branch else False}
        self.sudo().write(values)
        return True

    def close(self):
        self.ensure_one()
        self.sudo().write({'active': False})

    def write(self, vals):
        allowed = {'active', 'last_activity_at', 'company_id', 'branch_id'}
        if set(vals) - allowed:
            raise AccessError(_('Platform session security fields cannot be modified.'))
        return super().write(vals)

    def unlink(self):
        raise AccessError(_('Platform sessions cannot be deleted.'))


class FlexSysPlatformApplication(models.Model):
    _name = 'flexsys.platform.application'
    _description = 'FlexSys Platform Application'
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, index=True)
    summary = fields.Char(translate=True)
    icon = fields.Char(default='fa-cubes')
    url = fields.Char(required=True)
    version = fields.Char(required=True, default='1.0.0')
    module_name = fields.Char(required=True, index=True)
    category = fields.Selection([
        ('operations', 'Operations'),
        ('inventory', 'Inventory'),
        ('point_of_sale', 'Point of Sale'),
        ('kitchen', 'Kitchen'),
        ('crm', 'CRM'),
        ('analytics', 'Analytics'),
        ('platform', 'Platform'),
        ('other', 'Other'),
    ], default='other', required=True, index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    workspace_enabled = fields.Boolean(default=True)
    search_enabled = fields.Boolean(default=False)
    search_provider_model = fields.Char()
    search_provider_method = fields.Char(default='_flexsys_search_results')
    required_permission_code = fields.Char()
    health_status = fields.Selection([
        ('unknown', 'Unknown'),
        ('healthy', 'Healthy'),
        ('degraded', 'Degraded'),
        ('unavailable', 'Unavailable'),
    ], default='unknown', required=True, readonly=True)
    health_message = fields.Char(readonly=True)
    last_health_check_at = fields.Datetime(readonly=True)
    workspace_title = fields.Char(translate=True)
    workspace_subtitle = fields.Char(translate=True)
    workspace_provider_model = fields.Char()
    workspace_provider_method = fields.Char(default='_flexsys_workspace_metrics')
    workspace_item_ids = fields.One2many('flexsys.platform.workspace.item', 'application_id', string='Workspace Items')

    _code_unique = models.Constraint('UNIQUE(code)', 'Application code must be unique.')
    _module_unique = models.Constraint('UNIQUE(module_name)', 'Application module name must be unique.')

    @api.constrains('code')
    def _check_code(self):
        for rec in self:
            code = rec.code or ''
            if not code.replace('_', '').isalnum() or code.lower() != code:
                raise ValidationError(_(
                    'Application code must contain lowercase letters, numbers, and underscores only.'
                ))

    @api.constrains('url')
    def _check_url(self):
        for rec in self:
            if not rec.url or not rec.url.startswith('/') or rec.url.startswith('//'):
                raise ValidationError(_('Application URL must be an internal path starting with /.'))

    @api.model
    def register_application(self, values):
        """Create or update one application registration by stable application code."""
        required = {'name', 'code', 'url', 'module_name', 'version'}
        missing = sorted(required - set(values))
        if missing:
            raise ValidationError(_('Missing application registration fields: %s') % ', '.join(missing))
        clean_values = dict(values)
        clean_values['code'] = clean_values['code'].strip().lower()
        clean_values['module_name'] = clean_values['module_name'].strip()
        application = self.sudo().search([('code', '=', clean_values['code'])], limit=1)
        if application:
            application.write(clean_values)
            return application
        return self.sudo().create(clean_values)

    def is_available_for(self, user):
        """Return whether the independent FlexSys user can open this application."""
        self.ensure_one()
        return bool(
            self.active
            and (not self.required_permission_code or user.has_permission(self.required_permission_code))
        )

    def get_search_results(self, session, query, limit=8):
        """Return normalized, permission-aware search results for one application."""
        self.ensure_one()
        if not self.search_enabled or not self.is_available_for(session.user_id):
            return []
        query = (query or '').strip()
        if len(query) < 2 or not self.search_provider_model or not self.search_provider_method:
            return []
        method_name = self.search_provider_method.strip()
        if not method_name.startswith('_flexsys_search_'):
            raise ValidationError(_('Search provider methods must use the _flexsys_search_ prefix.'))
        provider = self.env[self.search_provider_model].sudo()
        method = getattr(provider, method_name, None)
        if not method:
            raise ValidationError(_('Search provider method was not found.'))
        raw_results = method(session=session, query=query, limit=max(1, min(int(limit or 8), 20))) or []
        results = []
        for item in raw_results[:20]:
            if not isinstance(item, dict):
                continue
            url = item.get('url') or self.url
            if not url.startswith('/') or url.startswith('//'):
                continue
            title = str(item.get('title') or '').strip()
            if not title:
                continue
            results.append({
                'application_code': self.code,
                'application_name': self.name,
                'application_icon': self.icon,
                'title': title,
                'subtitle': str(item.get('subtitle') or '').strip(),
                'type': str(item.get('type') or _('Record')),
                'icon': str(item.get('icon') or self.icon or 'fa-file'),
                'url': url,
            })
        return results

    @api.model
    def universal_search(self, session, query, limit=30):
        """Search all registered applications available in the active platform context."""
        query = (query or '').strip()
        if len(query) < 2:
            return []
        applications = self.sudo().search([
            ('active', '=', True),
            ('search_enabled', '=', True),
        ])
        applications = applications.filtered(lambda app: app.is_available_for(session.user_id))
        results = []
        per_application = max(3, min(10, int(limit or 30)))
        for application in applications:
            results.extend(application.get_search_results(session, query, limit=per_application))
            if len(results) >= limit:
                break
        return results[:max(1, min(int(limit or 30), 50))]

    def get_workspace_values(self, session):
        """Build one safe, permission-aware workspace payload."""
        self.ensure_one()
        user = session.user_id
        items = self.workspace_item_ids.filtered(lambda item: item.is_available_for(user))
        metrics = {}
        if self.workspace_provider_model and self.workspace_provider_method:
            method_name = self.workspace_provider_method.strip()
            if not method_name.startswith('_flexsys_workspace_'):
                raise ValidationError(_('Workspace provider methods must use the _flexsys_workspace_ prefix.'))
            provider = self.env[self.workspace_provider_model].sudo()
            method = getattr(provider, method_name, None)
            if not method:
                raise ValidationError(_('Workspace provider method was not found.'))
            metrics = method(session=session) or {}
        layout = self.env['flexsys.platform.workspace.layout'].sudo().search([
            ('user_id', '=', user.id), ('application_id', '=', self.id)
        ], limit=1).layout or {}
        hidden = set(layout.get('hidden', []))
        order = layout.get('order', [])
        rank = {code: index for index, code in enumerate(order)}
        items = items.filtered(lambda item: item.code not in hidden)
        items = items.sorted(key=lambda item: (rank.get(item.code, 9999), item.sequence, item.id))
        return {
            'application': self,
            'metrics': metrics,
            'metric_items': items.filtered(lambda item: item.item_type == 'metric'),
            'action_items': items.filtered(lambda item: item.item_type == 'action'),
            'widget_items': items.filtered(lambda item: item.item_type == 'widget'),
        }

    def update_health(self, status, message=None):
        """Update application health metadata through one controlled entry point."""
        allowed = {'unknown', 'healthy', 'degraded', 'unavailable'}
        if status not in allowed:
            raise ValidationError(_('Unsupported application health status.'))
        self.sudo().write({
            'health_status': status,
            'health_message': message or False,
            'last_health_check_at': fields.Datetime.now(),
        })
        return True


class FlexSysPlatformWorkspaceItem(models.Model):
    _name = 'flexsys.platform.workspace.item'
    _description = 'FlexSys Workspace Item'
    _order = 'application_id, item_type, sequence, id'

    application_id = fields.Many2one(
        'flexsys.platform.application', required=True, index=True, ondelete='cascade'
    )
    item_type = fields.Selection([
        ('metric', 'Metric'),
        ('action', 'Quick Action'),
        ('widget', 'Widget'),
    ], required=True, index=True)
    code = fields.Char(required=True, index=True)
    title = fields.Char(required=True, translate=True)
    description = fields.Char(translate=True)
    icon = fields.Char(default='fa-circle')
    sequence = fields.Integer(default=10)
    size = fields.Selection([('small', 'Small'), ('medium', 'Medium'), ('large', 'Large')], default='medium')
    permission_code = fields.Char()
    action_url = fields.Char()
    metric_key = fields.Char()
    active = fields.Boolean(default=True)

    _app_code_unique = models.Constraint(
        'UNIQUE(application_id, code)',
        'Workspace item code must be unique within the application.',
    )

    @api.constrains('action_url')
    def _check_action_url(self):
        for rec in self:
            if rec.action_url and (not rec.action_url.startswith('/') or rec.action_url.startswith('//')):
                raise ValidationError(_('Workspace action URL must be an internal path starting with /.'))

    def is_available_for(self, user):
        self.ensure_one()
        return bool(self.active and (not self.permission_code or user.has_permission(self.permission_code)))


class FlexSysPlatformWorkspaceLayout(models.Model):
    _name = 'flexsys.platform.workspace.layout'
    _description = 'FlexSys Workspace Layout'
    _order = 'user_id, application_id'

    user_id = fields.Many2one('flexsys.platform.user', required=True, index=True, ondelete='cascade')
    application_id = fields.Many2one('flexsys.platform.application', required=True, index=True, ondelete='cascade')
    layout = fields.Json(default=dict)

    _user_app_unique = models.Constraint(
        'UNIQUE(user_id, application_id)',
        'Each user can have only one saved layout per application.',
    )


class FlexSysSystemLog(models.Model):
    _name = 'flexsys.system.log'
    _description = 'FlexSys System Log'
    _order = 'create_date desc, id desc'

    event_type = fields.Selection([
        ('authentication', 'Authentication'), ('data', 'Data'), ('workflow', 'Workflow'),
        ('report', 'Report'), ('security', 'Security'), ('system', 'System'),
        ('api', 'API'), ('integration', 'Integration'),
    ], required=True, index=True)
    action = fields.Char(required=True, index=True)
    description = fields.Text()
    application_code = fields.Char(index=True)
    model_name = fields.Char(index=True)
    record_ref = fields.Char(index=True)
    platform_user_id = fields.Many2one('flexsys.platform.user', index=True, ondelete='set null')
    company_id = fields.Many2one('res.company', index=True, ondelete='set null')
    branch_id = fields.Many2one('flexsys.platform.branch', index=True, ondelete='set null')
    before_value = fields.Text()
    after_value = fields.Text()
    ip_address = fields.Char()
    user_agent = fields.Char()

    @api.model
    def record(self, event_type, action, **values):
        allowed = {'description', 'application_code', 'model_name', 'record_ref', 'platform_user_id',
                   'company_id', 'branch_id', 'before_value', 'after_value', 'ip_address', 'user_agent'}
        payload = {key: value for key, value in values.items() if key in allowed}
        payload.update({'event_type': event_type, 'action': action})
        return self.sudo().create(payload)

    def write(self, vals):
        raise AccessError(_('System log entries cannot be modified.'))

    def unlink(self):
        raise AccessError(_('System log entries cannot be deleted.'))
