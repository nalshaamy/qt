# -*- coding: utf-8 -*-
from odoo import fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    # CHANGE REQUEST FIX ("POS Send-to-KDS Settings - Simplify and
    # Correct Triggers"), confirmed live: simplified from three options
    # down to the two the request explicitly asks for. The old
    # 'validation'/'submit' pair is gone - both used to trigger sync on
    # ANY backend write touching 'lines'/'state' (create, qty change,
    # product add/remove, simply viewing/re-saving the order), which is
    # exactly the "Critical Trigger Rule" violation reported: "Adding
    # products... Removing products... Changing quantities... must NOT
    # automatically synchronize the order with KDS. The synchronization
    # boundary must be the cashier's explicit action: Send or New."
    #
    # 'send' (label "On Send to KDS") replaces both - see
    # pos_order.py::_flexsys_kds_sync()'s own docstring for exactly how
    # it detects the native Send/New action rather than any backend
    # write.
    kds_send_trigger = fields.Selection([
        ('payment', 'After Payment'),
        ('send', 'On Send to KDS'),
    ], default='payment', required=True, string='Send to KDS On',
        help="When an order placed through this POS should reach the "
             "kitchen.\n\n"
             "'After Payment' (default): the original, safest behavior "
             "(unchanged) - the order reaches the kitchen once payment/"
             "order completion goes through.\n\n"
             "'On Send to KDS': uses Odoo's own native POS workflow, not "
             "a new custom button. With Preparation Display enabled, "
             "this is the native 'Send' action (Build/Edit Order -> Send "
             "-> FlexSys KDS). Without Preparation Display, this is the "
             "native 'New' action (Build/Edit Order -> New -> FlexSys "
             "KDS) - starting a new order finalizes/sends the current "
             "one. Either way, simply adding/removing products, "
             "changing quantities, or editing the order does NOT "
             "synchronize anything by itself - changes accumulate until "
             "the next Send/New, then sync as ADDED/UPDATED/CANCELLED "
             "all at once.")
