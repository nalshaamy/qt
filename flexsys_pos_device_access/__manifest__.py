{
    "name": "FlexSys POS Device Access",
    "summary": "Pair trusted cashier devices to a fixed Odoo POS with one-time links, PIN verification, and audit logs",
    "version": "19.0.1.0.0",
    "category": "Sales/Point of Sale",
    "description": """
Secure POS device access for Odoo 19. Pair a cashier browser to one POS configuration
with a short-lived one-time link, keep Odoo employee PIN verification mandatory,
block Backend and cross-POS navigation for device sessions, and retain a complete
audit trail. No external service is required.
""",
    "author": "FlexSys",
    "website": "https://flexsyssa.com",
    "support": "info@flexsyssa.com",
    "price": 99.0,
    "currency": "USD",
    "license": "LGPL-3",
    "depends": ["pos_hr", "web"],
    "images": [
        "static/description/banner.png",
        "static/description/pairing_flow.png",
        "static/description/security_layers.png",
        "static/description/admin_overview.png",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "flexsys_pos_device_access/static/src/app/login_screen_pin_audit.js",
        ],
    },
    "data": [
        "security/security.xml",
        "data/device_sequence.xml",
        "security/ir.model.access.csv",
        "wizard/token_wizard_views.xml",
        "views/pos_device_views.xml",
        "views/access_log_views.xml",
        "data/ir_cron.xml",
    ],
    "installable": True,
    "application": False,
}
