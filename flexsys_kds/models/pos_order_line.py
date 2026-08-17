# -*- coding: utf-8 -*-
from odoo import api, models


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    # Same reasoning as pos_order.py._flexsys_kds_sync(): this hook fires
    # for whichever user is editing the POS line (a cashier), who has no
    # reason to be personally assigned to a FlexSys KDS station. All three
    # methods below run as sudo() so the automated KDS sync isn't gated by
    # a station assignment that has nothing to do with the person ringing
    # up the sale.

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        orders = lines.sudo().mapped('order_id').filtered('kds_order_id')
        for order in orders:
            # REAL BUG FIX ("Change Request After BUG-11", item 3: "On
            # Send to KDS... Critical Trigger Rule"), confirmed live:
            # this used to call _flexsys_kds_diff_lines() directly,
            # completely bypassing _flexsys_kds_sync()'s own trigger
            # gate - meaning "On Send to KDS" mode still synced
            # immediately on every single line add/edit regardless, the
            # exact violation this whole change request exists to fix.
            # Routed through _flexsys_kds_sync() instead - is_send_write
            # is always False from THIS specific hook (a line-level
            # create/write alone is never itself the Send/New signal;
            # see pos_order.py's own write() override, which passes
            # True only when last_order_preparation_change is part of
            # the SAME transaction's order-level write - the two happen
            # as separate write() calls within one overall _process_
            # order() request, per Odoo core's own pos_order.py) -
            # 'payment' mode is unaffected either way (its own gate
            # checks payment state, not is_send_write), and 'send' mode
            # now correctly defers to the later order-level write that
            # actually carries the Send/New signal, letting changes
            # accumulate exactly as required.
            order.sudo()._flexsys_kds_sync(is_send_write=False)
        return lines

    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in ('qty', 'note', 'product_id')):
            orders = self.sudo().mapped('order_id').filtered('kds_order_id')
            for order in orders:
                # Same fix as create() above - see that method's own
                # detailed comment.
                order.sudo()._flexsys_kds_sync(is_send_write=False)
        return res

    def unlink(self):
        # kds.order.line.pos_order_line_id is ondelete='set null', so once
        # super().unlink() runs we can no longer match these rows back to
        # their kds.order.line via that FK - flag them first, before that
        # happens.
        #
        # REAL BUG FIX ("POS Send-to-KDS Settings... verify this against
        # real Odoo 19 POS behavior or redesign the removal sync so it
        # cannot leak early"), confirmed live: this used to call
        # action_cancel() immediately here - correctness rested entirely
        # on an UNVERIFIED assumption (that a backend unlink() only ever
        # arrives as part of the same batched request that also carries
        # the Send/New signal). Redesigned so correctness no longer
        # depends on that assumption at all, regardless of how POS's own
        # frontend actually batches its requests: this now only sets
        # pending_removal=True (see kds_order_line.py's own field
        # docstring) - a plain write touching neither `state` nor
        # anything a KDS screen renders, so nothing becomes visible yet.
        # The real, audited cancellation is applied later, by
        # _flexsys_kds_diff_lines() (pos_order.py) - which only ever
        # runs at the correct sync boundary for whichever trigger mode
        # is configured ('payment': at payment; 'send': only on a
        # genuine Send/New write) - never here, never early.
        # REAL BUG FIX (found while implementing the redesign above):
        # this must NOT exclude 'completed' the way the old immediate-
        # cancel version's own search did - excluding it here would
        # mean a POS line deleted after its KDS line already reached
        # Completed (the exact scenario the earlier "Change Request
        # After BUG-11" item 1 fix - _system_cancel_after_completion() -
        # exists for) would never even get flagged at all, silently
        # losing that capability entirely. Only 'cancelled' is excluded
        # here (nothing further to do for an already-cancelled line);
        # _flexsys_kds_diff_lines() below decides HOW to handle each
        # remaining state - Completed via _system_cancel_after_completion(),
        # anything else via the normal action_cancel().
        kds_lines = self.env['kds.order.line'].sudo().search([
            ('pos_order_line_id', 'in', self.ids),
            ('state', '!=', 'cancelled'),
        ])
        kds_lines.write({'pending_removal': True})
        return super().unlink()
