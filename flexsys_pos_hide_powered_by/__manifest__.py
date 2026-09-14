# -*- coding: utf-8 -*-
{
    "name": "FlexSys POS Hide Powered By",
    "version": "19.0.1.0.0",
    "summary": "Hide the Powered by Odoo footer from Point of Sale customer receipts.",
    "description": '''
FlexSys POS Hide Powered By
===========================

A lightweight, standalone Odoo 19 module that hides the
"Powered by Odoo" footer from Point of Sale customer receipts.

No Odoo core files are modified.
''',
    "category": "Point of Sale",
    "author": "FlexSys",
    "website": "https://flexsyssa.com",
    "support": "info@flexsyssa.com",
    "license": "LGPL-3",
    "depends": ["point_of_sale"],
    "data": [],
    "assets": {
        "point_of_sale._assets_pos": [
            "flexsys_pos_hide_powered_by/static/src/xml/order_receipt.xml",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
