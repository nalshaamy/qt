{
    'name': 'FlexSys KDS - POC-1D Native Backend ePOS Flow (TEMPORARY)',
    'version': '19.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'POC ONLY: IoT device placeholder field for future Odoo IoT POC. Not a commercial module.',
    'description': """
TEMPORARY PROOF-OF-CONCEPT MODULE - NOT PART OF THE FLEXSYS KDS
COMMERCIAL BASELINE.

MERGE UPDATE ("POC -> flexsys_kds Merge"): every production-proven
component of this POC has been moved into flexsys_kds itself:
  - flexsys_printing_method / flexsys_printer_ip /
    flexsys_use_local_network_access fields (now in flexsys_kds's own
    models/kds_station.py)
  - the "Printing" tab (now in flexsys_kds's own
    views/kds_station_views.xml)
  - the Shared Ticket Renderer (flexsys_ticket_renderer.js)
  - the Internal KDS Direct ePOS Adapter (flexsys_epos_direct_adapter.js)
  - the Public Kiosk Direct ePOS Adapter (flexsys_epos_direct_public.js)
  - the Internal KDS print-button integration (merged directly into
    flexsys_kds's own kds_app.js)
  - the Public Kiosk print-button integration and printing-config
    bootstrap (merged directly into flexsys_kds's own
    controllers/kds_kiosk.py)

flexsys_kds is now the sole owner of all of the above - installable
and fully functional entirely on its own, with zero dependency on
this POC module.

This POC module now retains ONLY flexsys_iot_device_placeholder - a
placeholder field confirmed to have zero runtime dependency anywhere
(only its own field definition and its own view field reference,
nothing reads or writes it from any JS/Python logic) - kept here
because it is NOT production-proven and does not enter the commercial
core, per explicit direction, pending a separate, later Odoo IoT POC
round.

Safe to uninstall once flexsys_kds's own "Printing" tab and Direct
ePOS integration are confirmed fully working on their own (regression
test), without this module installed.
""",
    'author': 'FlexSys',
    'depends': ['flexsys_kds'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'data': [
        'views/kds_station_views.xml',
    ],
    'license': 'LGPL-3',
}
