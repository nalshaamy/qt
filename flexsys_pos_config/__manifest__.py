# -*- coding: utf-8 -*-
# FLPOS - Standalone Odoo 19 Point of Sale configuration and reporting module.

{
    "name": "FLPOS",
    "summary": "Configurable POS receipt engine and enhanced session closing reports",
    "version": "19.0.4.1.0",
    "category": "Sales/Point of Sale",
    "author": "FlexSys",
    "website": "https://flexsys.sa",
    "license": "LGPL-3",
    "depends": ["point_of_sale"],
    "data": [
        "security/flexsys_pos_receipt_security.xml",
        "security/ir.model.access.csv",
        "report/pos_session_report.xml",
        "report/pos_session_templates.xml",
        "views/pos_session_views.xml",
        "views/receipt_designer_views.xml",
        "views/res_config_settings_views.xml",
        "views/receipt_preview_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "flexsys_pos_config/static/src/scss/receipt_designer.scss",
            "flexsys_pos_config/static/src/js/receipt_builder.js",
            "flexsys_pos_config/static/src/xml/receipt_builder.xml",
            "flexsys_pos_config/static/src/scss/receipt_builder.scss",
        ],
        "web.report_assets_common": [
            "flexsys_pos_config/static/src/scss/pos_session_report.scss",
        ],
        "point_of_sale._assets_pos": [
            "flexsys_pos_config/static/src/xml/order_receipt.xml",
            "flexsys_pos_config/static/src/scss/order_receipt.scss",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
