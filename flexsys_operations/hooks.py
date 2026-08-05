# -*- coding: utf-8 -*-
"""Installation hooks for idempotent FlexSys Operations seed data."""


def _bind_xmlid(env, *, xml_name, model, record):
    """Bind an existing business record to this module XML ID when missing."""
    if not record:
        return
    imd = env['ir.model.data'].sudo()
    existing = imd.search([
        ('module', '=', 'flexsys_operations'),
        ('name', '=', xml_name),
    ], limit=1)
    if existing:
        if existing.model != model or existing.res_id != record.id:
            existing.write({'model': model, 'res_id': record.id, 'noupdate': True})
        return
    imd.create({
        'module': 'flexsys_operations',
        'name': xml_name,
        'model': model,
        'res_id': record.id,
        'noupdate': True,
    })


def pre_init_hook(env):
    """Reconnect orphaned seed records before XML data is loaded.

    Failed or interrupted historical installations may leave records in the
    database after their ``ir.model.data`` bindings are gone. Rebinding by the
    stable business keys makes installation and reinstallation idempotent.
    """
    permission_model = env['flexsys.platform.permission'].sudo()
    application_model = env['flexsys.platform.application'].sudo()
    workspace_model = env['flexsys.platform.workspace.item'].sudo()

    permission = permission_model.search([
        ('code', '=', 'operations.manage_store'),
    ], limit=1)
    _bind_xmlid(
        env,
        xml_name='permission_operations_manage_store',
        model='flexsys.platform.permission',
        record=permission,
    )

    application = application_model.search([
        ('code', '=', 'operations'),
    ], limit=1)
    _bind_xmlid(
        env,
        xml_name='application_operations',
        model='flexsys.platform.application',
        record=application,
    )

    if not application:
        return

    workspace_xmlids = {
        'active_orders': 'workspace_operations_active_orders',
        'ready_orders': 'workspace_operations_ready_orders',
        'scheduled_orders': 'workspace_operations_scheduled_orders',
        'open_tasks': 'workspace_operations_open_tasks',
        'orders': 'workspace_operations_orders_action',
        'kitchen': 'workspace_operations_kitchen_action',
        'self_order': 'workspace_operations_self_order_action',
        'stations': 'workspace_operations_stations_widget',
    }
    for code, xml_name in workspace_xmlids.items():
        item = workspace_model.search([
            ('application_id', '=', application.id),
            ('code', '=', code),
        ], limit=1)
        _bind_xmlid(
            env,
            xml_name=xml_name,
            model='flexsys.platform.workspace.item',
            record=item,
        )
