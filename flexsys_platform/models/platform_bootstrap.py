# -*- coding: utf-8 -*-
"""Idempotent registration of Operations inside FlexSys Platform.

All mutable platform registry data is created/updated by stable business keys.
XML is only used to invoke this service on install and every upgrade.
"""
from odoo import api, models


class FlexSysPlatformApplication(models.Model):
    _inherit = 'flexsys.platform.application'

    @api.model
    def _bind_operations_xmlid(self, xml_name, record):
        """Attach the stable module XML ID to an existing or new record."""
        if not record:
            return
        imd = self.env['ir.model.data'].sudo()
        xmlid = imd.search([
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
            imd.create(values)

    @api.model
    def _ensure_operations_seed_data(self):
        """Create or update Operations registry data without duplicate inserts.

        The method is safe to run repeatedly and preserves permissions added to
        the administrator role by other applications.
        """
        Permission = self.env['flexsys.platform.permission'].sudo().with_context(active_test=False)
        Role = self.env['flexsys.platform.role'].sudo().with_context(active_test=False)
        Workspace = self.env['flexsys.platform.workspace.item'].sudo().with_context(active_test=False)
        PlatformUser = self.env['flexsys.platform.user'].sudo().with_context(active_test=False)

        permission_values = {
            'name': 'Manage Operations Settings',
            'code': 'operations.manage_store',
            'application_code': 'operations',
            'active': True,
        }
        permission = Permission.search([
            ('code', '=', permission_values['code']),
        ], limit=1)
        if permission:
            permission.write(permission_values)
        else:
            permission = Permission.create(permission_values)
        self._bind_operations_xmlid('permission_operations_manage_store', permission)

        application_values = {
            'name': 'Operations',
            'code': 'operations',
            'summary': 'Orders, execution tasks, stations and mission control',
            'icon': 'fa-diagram-project',
            'url': '/flexsys/workspace/operations',
            'version': '19.0.3.1.8',
            'module_name': 'flexsys_platform',
            'category': 'operations',
            'workspace_enabled': True,
            'search_enabled': True,
            'search_provider_model': 'flexsys.operations.order',
            'search_provider_method': '_flexsys_search_results',
            'sequence': 10,
            'required_permission_code': 'operations.access',
            'workspace_title': 'Operations',
            'workspace_subtitle': 'Orders, execution tasks, stations and live operational status',
            'workspace_provider_model': 'flexsys.operations.order',
            'health_status': 'healthy',
            'health_message': 'Operations workspace is registered and available.',
            'active': True,
        }
        application = self.sudo().with_context(active_test=False).search([('code', '=', 'operations')], limit=1)
        if application:
            application.write(application_values)
        else:
            application = self.sudo().create(application_values)
        self._bind_operations_xmlid('application_operations', application)

        workspace_specs = (
            ('workspace_operations_active_orders', 'active_orders', 'metric', 'Active Orders', False, 'fa-bolt', 10, '', 'active_orders', True, ''),
            ('workspace_operations_ready_orders', 'ready_orders', 'metric', 'Ready', False, 'fa-check-circle', 20, '', 'ready_orders', True, ''),
            ('workspace_operations_scheduled_orders', 'scheduled_orders', 'metric', 'Scheduled', False, 'fa-clock-o', 30, '', 'scheduled_orders', True, ''),
            ('workspace_operations_open_tasks', 'open_tasks', 'metric', 'Open Tasks', False, 'fa-list-check', 40, '', 'open_tasks', True, ''),
            ('workspace_operations_orders_action', 'orders', 'action', 'Orders', 'Open and manage all orders', 'fa-receipt', 10, '/flexsys/operations/orders', '', True, 'operations.access'),
            ('workspace_operations_kitchen_action', 'kitchen', 'action', 'Kitchen', 'Open the kitchen workspace', 'fa-fire', 20, '/flexsys/operations/kitchen', '', True, 'operations.access'),
            ('workspace_operations_self_order_action', 'self_order', 'action', 'Self Order', 'Preview the customer ordering experience', 'fa-mobile-screen', 30, '/{brand}/menu', '', True, ''),
            ('workspace_operations_stations_widget', 'stations', 'widget', 'Active Stations', 'Stations available in the current context', 'fa-layer-group', 10, '', 'stations', False, ''),
        )
        for (xml_name, code, item_type, title, description, icon, sequence,
             action_url, metric_key, active, permission_code) in workspace_specs:
            values = {
                'application_id': application.id,
                'item_type': item_type,
                'code': code,
                'title': title,
                'description': description or False,
                'icon': icon,
                'sequence': sequence,
                'action_url': action_url or False,
                'metric_key': metric_key or False,
                'active': active,
                'permission_code': permission_code or False,
            }
            item = Workspace.search([
                ('application_id', '=', application.id),
                ('code', '=', code),
            ], limit=1)
            if item:
                item.write(values)
            else:
                item = Workspace.create(values)
            self._bind_operations_xmlid(xml_name, item)

        admin_role = Role.search([('code', '=', 'platform_admin')], limit=1)
        if admin_role:
            permission_ids = Permission.search([
                ('code', 'in', ['operations.access', 'operations.manage_store']),
            ]).ids
            missing_ids = list(set(permission_ids) - set(admin_role.permission_ids.ids))
            if missing_ids:
                admin_role.write({'permission_ids': [(4, permission_id) for permission_id in missing_ids]})
            self._bind_operations_xmlid('role_platform_admin_extension', admin_role)

            users_without_roles = PlatformUser.search([
                ('active', '=', True),
                ('role_ids', '=', False),
            ])
            if users_without_roles:
                users_without_roles.write({'role_ids': [(4, admin_role.id)]})

        return True
