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
- Printing: Direct Network (Epson ePOS) browser printing and the
  legacy external Print Agent path, both tracked through the same
  `kds.print.job` record; the Legacy Agent path additionally supports
  automatic retry and backup-printer fallback.
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
            # Loaded before kds_app.js so window.FlexSysTicketBuilder is
            # defined before kds_app.js's own onPrintClick could ever
            # call it (a real ES import handles
            # flexsys_epos_direct_adapter.js's own load-order
            # automatically regardless of position here, but this
            # shared renderer is called only via the global
            # window.FlexSysTicketBuilder, not an import, so its own
            # position here is what guarantees load order for it).
            'flexsys_kds/static/src/shared/flexsys_ticket_renderer.js',
            # HIGH-DENSITY LAYOUT: window.FlexSysPagination must be
            # defined before kds_app.js's own pagination getter could
            # ever call it - same load-order reasoning as the ticket
            # renderer immediately above.
            'flexsys_kds/static/src/shared/flexsys_pagination.js',
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
        #
        # PHASE 3 ("POS Direct Auto Print Worker"): three files added,
        # in the explicit dependency order required - the shared
        # ticket renderer and Direct ePOS adapter must both be
        # available BEFORE the worker itself ever runs (the worker
        # calls window.FlexSysTicketBuilder and imports
        # flexsysPrintViaDirectEpos directly). Deliberately only these
        # three - the Public Kiosk's own standalone files
        # (flexsys_epos_direct_public.js and anything under
        # static/src/public/) are NOT loaded here; POS uses the ES
        # module adapter (flexsys_epos_direct_adapter.js), the same
        # one Internal KDS already uses, not the Kiosk's own
        # vanilla-JS equivalent.
        'point_of_sale._assets_pos': [
            'flexsys_kds/static/src/js/flexsys_kds_offline_send_warning.js',
            'flexsys_kds/static/src/shared/flexsys_ticket_renderer.js',
            'flexsys_kds/static/src/js/flexsys_epos_direct_adapter.js',
            'flexsys_kds/static/src/js/flexsys_pos_direct_print_worker.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'post_init_hook': 'post_init_hook',
}
