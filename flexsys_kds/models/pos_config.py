# -*- coding: utf-8 -*-
from odoo import fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    # AUDIT FIX ("POS -> KDS Send Trigger", HIGH): the old sync gate was
    # hardcoded to `state in ('paid', 'done', 'invoiced')` - meaning
    # kitchen preparation could never start before payment, which doesn't
    # match a real dine-in flow (customer eats, pays at the end; the
    # kitchen needs the ticket the moment the order is placed, not once
    # the bill is settled).
    kds_send_trigger = fields.Selection([
        ('payment', 'Payment (default, matches previous behavior)'),
        ('validation', 'Order Validation'),
        ('submit', 'POS Submit / Send to Kitchen'),
    ], default='payment', required=True, string='Send to KDS On',
        help="When an order placed through this POS should reach the "
             "kitchen. 'Payment' is the original, safest behavior "
             "(unchanged from before this setting existed) - the other "
             "two let a Dine-In order reach the kitchen before payment, "
             "for a real table-service flow.\n\n"
             "Implementation note on 'Order Validation' vs 'POS Submit': "
             "both currently trigger sync as soon as a pos.order record "
             "with at least one line exists in the backend and isn't "
             "cancelled - Odoo's exact signal for 'sent to kitchen "
             "specifically' vs 'validated at the register' varies enough "
             "across versions/configurations (with vs. without the "
             "Restaurant module's table-order flow) that collapsing them "
             "to one trigger point was the safer choice over guessing at "
             "a specific field/state that might not exist in every "
             "setup. If your restaurant flow exposes a more precise "
             "signal you want used instead, it's a small, well-scoped "
             "follow-up to wire in exactly.")
