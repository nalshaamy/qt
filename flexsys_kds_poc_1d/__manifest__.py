{
    'name': 'FlexSys KDS - POC-1D Native Backend ePOS Flow (TEMPORARY)',
    'version': '19.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'POC ONLY: KDS card Print reuses Odoo native Backend ePOS flow (test_epos) + LNA - no EpsonPrinter/ePOSLayout dependency. Not a commercial module.',
    'description': """
TEMPORARY PROOF-OF-CONCEPT MODULE - NOT PART OF THE FLEXSYS KDS
COMMERCIAL BASELINE. Supersedes POC-1C entirely.

ARCHITECTURAL SHIFT FROM POC-1C: POC-1C attempted to reuse Odoo's own
EpsonPrinter/BasePrinter/render_service/html-to-image class chain,
which requires the point_of_sale.ePOSLayout QWeb template - a
dependency this round deliberately avoids entirely, since that
template's own exact source file could not be confirmed with
certainty.

This round instead mirrors Odoo's own NATIVE BACKEND ePOS TEST-PRINT
FLOW, per direct confirmation that point_of_sale already loads, in
'web.assets_backend' (not requiring anything added here for these):
  point_of_sale/static/src/backend/test_epos/*
  point_of_sale/static/src/app/utils/init_lna.js

This POC's own new code imports only initLNA/getLNATargetAddressSpace
from the confirmed init_lna.js path, and otherwise builds the
ePOS-Print XML test payload and posts it directly via fetch() to the
standard Epson CGI endpoint - Epson's own published, documented
protocol, not a guess - kept entirely inside a separate "Direct ePOS
Adapter" file
(static/src/js/flexsys_epos_direct_adapter.js), deliberately isolated
from the KDS card's own print-button interception logic
(flexsys_poc1d_print_intercept.js), so a future "Station -> Odoo IoT
Adapter" can be added later without touching either.

Design (unchanged from the prior round): kds.station itself is the
single printing setup point - no pos.printer record involved. The
"Printing (POC)" tab has:
  - Printing Method: Direct Network / Odoo IoT (Selection)
  - Printer IP (Char), shown only for Direct Network
  - Use Local Network Access (Boolean, default True) - this design's
    own equivalent of pos.printer's own use_local_network_access field
  - An IoT placeholder field, shown only for Odoo IoT (not functional
    this round)

This module does not modify any file inside flexsys_kds, and does not
touch kds.print.job, kds.printer, the Agent API, Retry/Fallback,
Reprint, Routing, or Workflow. Only Direct Network / Epson ePOS is
tested this round.

CONFIRMED PASS ON INTERNAL KDS: a real ticket printed successfully
through this exact path (Internal KDS Card Print -> Current Station
-> Printer IP -> Direct ePOS Adapter -> Epson -> physical printer).
The Internal KDS integration (models/kds_station.py,
views/kds_station_views.xml, and both files under static/src/js/) is
UNCHANGED from that confirmed-passing state in this round.

ADDED THIS ROUND: Public Kiosk integration
(/flexsyskds/public/<station>/<token>). That page is standalone HTML
with a classic <script> tag - no Odoo Web Client/OWL/module loader at
all, so the Internal KDS Adapter's own "@point_of_sale/..." import
cannot resolve there. A second, standalone-page equivalent adapter
(static/src/public/flexsys_epos_direct_public.js, plain JS, no
imports, exposing window.FlexSysKDSPrint.printDirectEpos()) implements
the SAME protocol - same XML, same endpoint, same timeout, same LNA
semantics (via the browser's own navigator.permissions API instead of
Odoo's initLNA(), since that too cannot be imported there), same
response parsing, same success/error contract.

This module does not modify controllers/kds_kiosk.py inside
flexsys_kds. A new controller
(controllers/kds_kiosk_poc1d.py) extends
FlexSysKdsKioskController via normal Odoo controller inheritance:
kiosk_page() calls the ORIGINAL handler via super() first, then only
appends one small <script> injection snippet right before </body> -
the original response is otherwise untouched. A second, new route
(/flexsys_kds_poc_1d/public/printing_config/<station>/<token>) reuses
flexsys_kds's own single, central _station_from_token() token-
validation function directly (never re-implemented or weakened), and
returns only station_id, station_name, flexsys_printing_method,
flexsys_printer_ip, and flexsys_use_local_network_access - no Agent
Key, no printer secrets, nothing else.

The injected script wraps the EXISTING global printOrder(orderId)
function already defined in flexsys_kds's own Kiosk page template: a
'direct_network' station's Print button now uses the Direct ePOS
Adapter instead of the legacy /flexsyskds/public/api/print route; any
other station falls through to the original, completely unchanged
legacy flow.

Uninstall this module once the POC is complete.
""",
    'author': 'FlexSys',
    'depends': ['flexsys_kds', 'point_of_sale'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'data': [
        'views/kds_station_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            # REAL TICKET RENDERING ROUND: the ONE shared file both
            # Internal KDS and Public Kiosk load and call identically
            # - loaded first so window.FlexSysTicketBuilder is defined
            # before either adapter file below could ever call it.
            'flexsys_kds_poc_1d/static/src/shared/flexsys_ticket_renderer.js',
            # Internal KDS integration - transport itself UNCHANGED,
            # confirmed PASS; only the XML-building call site inside
            # the adapter now delegates to the shared builder above.
            'flexsys_kds_poc_1d/static/src/js/flexsys_epos_direct_adapter.js',
            'flexsys_kds_poc_1d/static/src/js/flexsys_poc1d_print_intercept.js',
        ],
        # Deliberately NOT added to any assets bundle: the Public
        # Kiosk page is standalone HTML, not part of any Odoo asset
        # bundle. flexsys_ticket_renderer.js and
        # flexsys_epos_direct_public.js are both served as plain
        # static HTTP files instead (Odoo serves every file under any
        # module's own static/ automatically at
        # /<module_name>/static/<path> with zero extra registration),
        # loaded via plain <script src="..."> tags injected by
        # controllers/kds_kiosk_poc1d.py - the shared builder's own
        # <script> tag placed before the public adapter's own, so it
        # is defined first there too.
    },
    'license': 'LGPL-3',
}
