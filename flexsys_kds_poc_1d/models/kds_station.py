# -*- coding: utf-8 -*-
from odoo import fields, models

# ---------------------------------------------------------------------
# FlexSys KDS - POC-1D ONLY (TEMPORARY, NOT COMMERCIAL CODE)
#
# MERGE UPDATE: flexsys_printing_method, flexsys_printer_ip, and
# flexsys_use_local_network_access have been MOVED to flexsys_kds
# itself (models/kds_station.py there) - the proven, production-ready
# fields. This module no longer defines them at all; flexsys_kds is
# now their sole owner. Only flexsys_iot_device_placeholder remains
# here - confirmed to have zero runtime dependency anywhere (only its
# own field definition and its own view field, nothing reads or writes
# it from any JS/Python logic) - it is NOT production-proven and does
# not enter the commercial core per explicit direction.
# ---------------------------------------------------------------------


class KdsStationPoc1d(models.Model):
    _inherit = 'kds.station'

    # Placeholder only - not read or used by any print logic. A plain
    # Char (not a Many2one to any IoT-specific model, which would
    # require the 'iot' app to be installed as a hard dependency for a
    # field this POC doesn't even use yet) so the approved tab layout
    # (Direct Network / Odoo IoT switch with the corresponding fields
    # appearing) can be seen and reviewed now, ahead of the separate
    # IoT POC round.
    flexsys_iot_device_placeholder = fields.Char(
        string='IoT Printer Device (POC placeholder)',
        help="POC-1D ONLY, PLACEHOLDER: not implemented in this round. "
             "Odoo IoT printing is a separate, later POC - this field "
             "exists only so the approved tab layout is visible now.")
