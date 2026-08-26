{
    'name': 'FlexSys KDS',
    'version': '19.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Professional Multi-Station Kitchen Display & Production Management for Odoo POS',
    'description': """
FlexSys KDS
===========
Multi-station Kitchen Display System and production management layer
for Odoo Point of Sale — routes orders to the right station in real
time, tracks preparation SLA, and gives every role exactly the
visibility and control they need.

Key Capabilities
-----------------
- Multi-station Kitchen Display, with an authenticated backend screen
  and a token-based Public Kiosk.
- Intelligent station routing - explicit rules with product- and
  category-level fallback, multi-company isolated.
- Flexible station Operating Modes: KDS Only, Printer Only, or
  KDS + Printer.
- POS Quantity Reconciliation - quantity increases are reconciled
  when the POS sends the updated preparation change, while decreases
  and zero-quantity cancellations are reflected immediately,
  preserving historical kitchen production without duplicate deltas.
- SLA Monitoring per station, refreshed live.
- Expeditor / Packing - an optional final-assembly stage with its own
  tracked task and SLA.
- Printing and external Print Agent integration - an atomic job
  queue with retry and backup-printer fallback.
- Role and station-based access controls (Operator / Supervisor /
  Branch Manager / Administrator).
- Public Kiosk with secure, per-station token access.
- Company-aware routing, operational data isolation, and role-based
  access controls for multi-company environments.
- Arabic and English localization, with RTL-aware layouts.
- Operational audit logging for workflow transitions, corrections,
  printing events, and administrative actions.

See README.md for full product documentation, docs/ARCHITECTURE.md and
docs/PRINT_AGENT.md for technical/integration detail.

Technical module name: flexsys_kds
    """,
    'author': 'FlexSys',
    'website': 'https://flexsyssa.com',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'point_of_sale', 'product'],
    'data': [
        'security/kds_security.xml',
        'security/ir.model.access.csv',
        'data/kds_data.xml',
        'views/kds_printer_views.xml',
        'views/kds_station_views.xml',
        'views/kds_routing_rule_views.xml',
        'views/kds_print_job_views.xml',
        'views/kds_printer_hub_views.xml',
        'views/kds_order_views.xml',
        'views/kds_event_views.xml',
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
            # MERGED FROM PROVEN POC (flexsys_kds_poc_1d) - loaded
            # before kds_app.js so window.FlexSysTicketBuilder is
            # defined before kds_app.js's own onPrintClick could ever
            # call it (a real ES import handles
            # flexsys_epos_direct_adapter.js's own load-order
            # automatically regardless of position here, but this
            # shared renderer is called only via the global
            # window.FlexSysTicketBuilder, not an import, so its own
            # position here is what guarantees load order for it).
            'flexsys_kds/static/src/shared/flexsys_ticket_renderer.js',
            'flexsys_kds/static/src/js/flexsys_epos_direct_adapter.js',
            'flexsys_kds/static/src/js/kds_app.js',
            'flexsys_kds/static/src/xml/kds_templates.xml',
        ],
        # A single, deliberately minimal frontend patch on Odoo's own
        # sendOrderInPreparation() hook point: persists a "Pending
        # Kitchen Send" warning in plain browser localStorage (no Odoo
        # data model/field involved) if a Send fails while offline, and
        # re-shows it on reconnect - no silent auto-retry, no false
        # success indication. See that file's own top-of-file comment
        # for the full behavior.
        'point_of_sale._assets_pos': [
            'flexsys_kds/static/src/js/flexsys_kds_offline_send_warning.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'post_init_hook': 'post_init_hook',
}
