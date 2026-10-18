{
 "name": "FlexSys POS Receipt",
 "summary": "Bilingual refined POS 80mm receipt layout for Odoo 19",
 "version": "19.0.1.0.13",
 "category": "Point of Sale",
 "author": "FlexSys",
 "website": "https://flexsyssa.com",
 "license": "LGPL-3",
 "depends": ["point_of_sale"],
 "data": ["views/pos_config_views.xml"],
 "assets": {"point_of_sale._assets_pos": [
  "flexsys_pos_receipt/static/src/js/order_receipt.js",
  "flexsys_pos_receipt/static/src/xml/order_receipt.xml",
  "flexsys_pos_receipt/static/src/scss/order_receipt.scss",
  "flexsys_pos_receipt/static/src/scss/receipt_v111.scss",
  "flexsys_pos_receipt/static/src/scss/receipt_v112.scss",
  "flexsys_pos_receipt/static/src/scss/receipt_v113.scss"
 ]},
 "installable": True,
 "application": False
}
