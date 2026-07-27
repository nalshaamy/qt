# -*- coding: utf-8 -*-
# FLPOS - Standalone Odoo 19 Point of Sale configuration and reporting module.

{
    "name": "FLPOS Intelligence",
    "summary": "Advanced POS Reporting, Dashboards & Business Intelligence for Odoo",
    "version": "19.0.14.2.9",
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
        "web.report_assets_common": [
            "flexsys_pos_config/static/src/scss/cairo_fonts.scss",
            "flexsys_pos_config/static/src/scss/pos_session_report.scss",
        ],
        "point_of_sale._assets_pos": [
            "flexsys_pos_config/static/src/scss/cairo_fonts.scss",
            "flexsys_pos_config/static/src/xml/order_receipt.xml",
            "flexsys_pos_config/static/src/scss/order_receipt.scss",
            "flexsys_pos_config/static/src/app/closing_popup/thermal_closing_report.js",
            "flexsys_pos_config/static/src/app/closing_popup/thermal_closing_report.xml",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
