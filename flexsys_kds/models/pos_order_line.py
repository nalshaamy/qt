# -*- coding: utf-8 -*-
from odoo import _, api, models


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
            order.sudo()._flexsys_kds_diff_lines()
        return lines

    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in ('qty', 'note', 'product_id')):
            orders = self.sudo().mapped('order_id').filtered('kds_order_id')
            for order in orders:
                order.sudo()._flexsys_kds_diff_lines()
        return res

    def unlink(self):
        # kds.order.line.pos_order_line_id is ondelete='set null', so once
        # super().unlink() runs we can no longer match these rows back to
        # their kds.order.line via that FK - cancel them first.
        kds_lines = self.env['kds.order.line'].sudo().search([
            ('pos_order_line_id', 'in', self.ids),
            ('state', 'not in', ('completed', 'cancelled')),
        ])
        for kline in kds_lines:
            kline.action_cancel(reason=_('Removed from POS order after send'), bypass_check=True)
        return super().unlink()
