{
    "name": "FlexSys Odoo Stability",
    "summary": "Browser storage resilience and diagnostics for Odoo 19",
    "version": "19.0.1.0.0",
    "category": "Technical",
    "author": "FlexSys",
    "website": "https://flexsys.sa",
    "license": "LGPL-3",
    "depends": ["web", "point_of_sale"],
    "assets": {
        "web.assets_backend": [
            "flexsys_odoo_stability/static/src/js/rpc_quota_recovery.js",
        ],
        "point_of_sale._assets_pos": [
            "flexsys_odoo_stability/static/src/js/rpc_quota_recovery.js",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
