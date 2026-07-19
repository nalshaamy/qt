{
    'name': 'FlexSys Trans Manager',
    'version': '19.0.1.3.0',
    'category': 'Inventory/Inventory',
    'summary': 'FlexSys independent operations and inventory dashboard',
    'description': 'FlexSys Trans Manager - Operations Platform - إدارة العمليات',
    'author': 'FlexSys',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'stock', 'product'],
    'data': [
        'security/ir.model.access.csv',
        'views/inventory_manager_views.xml',
        'views/web_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'flexsys_odoo_trans/static/src/css/inventory_portal.css',
        ],
    },
    'application': True,
    'installable': True,
}
