{
    'name': 'FlexSys KDS',
    'version': '19.0.7.13.0',
    'category': 'Point of Sale',
    'summary': 'Multi-station Kitchen Display System for Odoo POS',
    'description': """
FlexSys KDS
===========
Multi-station Kitchen Display System and production management layer
for Odoo 19 Point of Sale.

Current Scope (Phase 1 - complete)
-----------------------------------
- Station-based routing engine (product / POS category / inventory
  category / order type / source / POS config), multi-company isolated
- Configurable POS -> KDS send trigger: After Payment (default) or On
  Send to KDS (native Odoo Send/New action, not a custom button)
- Centralized workflow engine (New / Accepted / Preparing / Ready /
  Completed / Cancelled / On Hold) - every transition, including
  system-triggered corrections, audited and never a raw state write
- Live SLA tracking per station, with a 1-minute freshness refresh
- Optional Expeditor / Packing final-assembly stage - a real tracked
  task (own state machine, timestamps, separate SLA), not just a flag
- Printing: job queue with an atomic claim/lease mechanism and a
  versioned payload contract for an external Print Agent (not included)
- Role-based security (Operator / Supervisor / Branch Manager /
  Administrator), station-scoped record rules, protected-field write
  guards
- Two KDS screens: authenticated backend (bus.bus realtime) and public
  token-based kiosk (polling)
- Full audit log (kds.event)

See README.md for current product documentation, docs/ARCHITECTURE.md
and docs/PRINT_AGENT.md for technical detail, and CHANGELOG.md for the
full development history.

Technical module name: flexsys_kds
    """,
    'author': 'FlexSys',
    'website': 'https://flexsys.example.com',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'point_of_sale', 'product'],
    'data': [
        'security/kds_security.xml',
        'security/ir.model.access.csv',
        'data/kds_data.xml',
        'data/kds_workflow_status_data.xml',
        'views/kds_printer_views.xml',
        'views/kds_station_views.xml',
        'views/kds_routing_rule_views.xml',
        'views/kds_print_job_views.xml',
        'views/kds_printer_hub_views.xml',
        'views/kds_order_views.xml',
        'views/kds_event_views.xml',
        'views/kds_order_status_views.xml',
        'views/kds_pos_config_views.xml',
        'views/product_views.xml',
        'views/kds_screen_templates.xml',
        'views/kds_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'flexsys_kds/static/src/scss/kds_style.scss',
            'flexsys_kds/static/src/js/kds_i18n.js',
            'flexsys_kds/static/src/js/kds_audio.js',
            'flexsys_kds/static/src/js/kds_store.js',
            'flexsys_kds/static/src/js/kds_order_card.js',
            'flexsys_kds/static/src/js/kds_app.js',
            'flexsys_kds/static/src/xml/kds_templates.xml',
        ],
        # REAL BUG FIX ("LIVE NETWORK TRACE - EXACT ODOO 'ORDER / SEND
        # TO PREPARATION' SERVER PATH CONFIRMED"): the two frontend
        # patches that previously lived in this bundle
        # (flexsys_kds_pos_send_signal.js,
        # flexsys_kds_pos_send_signal_order_model.js - v7.9.3/v7.9.6)
        # were REMOVED (in v7.11.0), confirmed no longer needed: a live
        # browser Network trace showed zero effect from either patch for
        # the "Order" confirmation-dialog action, while the SAME trace
        # confirmed the actual RPC call for that action is
        # pos.order.sync_from_ui - a server-side entry point every POS
        # save goes through, overridden directly in models/pos_order.py
        # instead.
        #
        # REAL BUG FIX ("FINAL IMPLEMENTATION REQUEST - Frontend
        # Durable Send Generation"): this bundle is reintroduced here,
        # deliberately minimal - exactly ONE file, doing exactly ONE
        # thing (a local, synchronous, offline-safe field increment,
        # with no RPC call of its own at all - see that file's own
        # top-of-file comment for the complete explanation of why this
        # is architecturally different from, and does not repeat the
        # failure mode of, the two removed patches above). This is the
        # confirmed, narrowly-scoped fix for the one remaining gap in
        # v7.12.1's own backend architecture, which the client's own
        # review explicitly accepted as correct and asked not to be
        # redesigned.
        'point_of_sale._assets_pos': [
            'flexsys_kds/static/src/js/flexsys_kds_send_generation.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'post_init_hook': 'post_init_hook',
}
