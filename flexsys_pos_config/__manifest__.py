# -*- coding: utf-8 -*-
# FLPOS - Standalone Odoo 19 Point of Sale configuration and reporting module.

{
    "name": "FLPOS",
    "summary": "POS receipt configuration and enhanced session closing reports",
    "version": "19.0.1.0.1",
    "category": "Sales/Point of Sale",
    "author": "FlexSys",
    "website": "https://flexsys.sa",
    "license": "LGPL-3",
    "depends": ["point_of_sale"],
    "data": [
        "report/pos_session_report.xml",
        "report/pos_session_templates.xml",
        "views/pos_session_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "flexsys_pos_config/static/src/xml/pos_receipt_branding.xml",
            "flexsys_pos_config/static/src/scss/pos_receipt_branding.scss",
        ],
        "web.report_assets_common": [
            "flexsys_pos_config/static/src/scss/pos_session_report.scss",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
