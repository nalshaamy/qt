{
    "name": "FlexSys POS Device Access",
    "summary": "Secure device-token entry to a fixed Odoo POS while preserving cashier PIN verification",
    "version": "19.0.1.1.0",
    "category": "Sales/Point of Sale",
    "author": "FlexSys",
    "website": "https://flexsyssa.com",
    "license": "LGPL-3",
    "depends": ["pos_hr", "web"],
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
