# -*- coding: utf-8 -*-
from odoo import fields, models

# ---------------------------------------------------------------------
# FlexSys KDS - POC-1D ONLY (TEMPORARY, NOT COMMERCIAL CODE)
#
# Same Station-as-single-printing-setup-point design as the prior
# round (kept: flexsys_printing_method, flexsys_printer_ip). Adds one
# new field, flexsys_use_local_network_access, mirroring pos.printer's
# own use_local_network_access field - since this design deliberately
# has no pos.printer record for the customer to create/select, this
# POC needs its own equivalent flag to feed the same use_lna decision
# Odoo's own native ePOS flow makes.
# ---------------------------------------------------------------------


class KdsStationPoc1d(models.Model):
    _inherit = 'kds.station'

    flexsys_printing_method = fields.Selection([
        ('direct_network', 'Direct Network (Epson ePOS)'),
        ('iot', 'Odoo IoT'),
    ], string='Printing Method (POC)', default='direct_network',
        help="POC-1D ONLY: how this station's own Print button reaches "
             "a physical printer. 'Direct Network' is the only path "
             "implemented/tested in this round - 'Odoo IoT' is a "
             "placeholder for the approved UI design, not yet wired "
             "to any print logic.")

    flexsys_printer_ip = fields.Char(
        string='Printer IP (POC)',
        help="POC-1D ONLY: this station's own Epson ePOS printer IP "
             "address on the local network, used with Odoo's own "
             "native backend ePOS test-print flow "
             "(point_of_sale/static/src/backend/test_epos/). Only "
             "relevant when Printing Method is 'Direct Network'.")

    flexsys_use_local_network_access = fields.Boolean(
        string='Use Local Network Access (POC)', default=True,
        help="POC-1D ONLY: mirrors pos.printer's own "
             "use_local_network_access field - this design has no "
             "pos.printer record, so this station-level flag feeds "
             "the same use_lna decision Odoo's own native ePOS flow "
             "makes (Chrome's Local Network Access permission for an "
             "https: page reaching a local http: printer IP).")

    # Placeholder only - not read or used by any print logic in this
    # round. A plain Char (not a Many2one to any IoT-specific model,
    # which would require the 'iot' app to be installed as a hard
    # dependency for a field this POC round doesn't even use yet) so
    # the approved tab layout (Direct Network / Odoo IoT switch with
    # the corresponding fields appearing) can be seen and reviewed
    # now, ahead of the separate IoT POC round.
    flexsys_iot_device_placeholder = fields.Char(
        string='IoT Printer Device (POC placeholder)',
        help="POC-1D ONLY, PLACEHOLDER: not implemented in this round. "
             "Odoo IoT printing is a separate, later POC - this field "
             "exists only so the approved tab layout is visible now.")
