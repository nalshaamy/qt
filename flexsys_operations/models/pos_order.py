# -*- coding: utf-8 -*-
from odoo import fields, models


class PosOrder(models.Model):
    _inherit = 'pos.order'

    qtcafe_qr_order_id = fields.Many2one(
        'qtcafe.qr.order',
        string='Operations Order',
        readonly=True,
        copy=False,
        index=True,
    )

    def _qtcafe_sync_qr_order_ready(self):
        """Mark linked operations orders as ready once the POS order is paid/done.

        This method is intentionally idempotent so repeated POS writes do not
        create concurrent update issues or duplicate state changes.
        """
        paid_states = {'paid', 'done', 'invoiced'}
        for pos_order in self:
            qr_order = pos_order.qtcafe_qr_order_id
            if not qr_order:
                continue
            if pos_order.state not in paid_states:
                continue
            if qr_order.state in ('ready', 'cancelled'):
                continue
            qr_order.sudo().write({
                'state': 'ready',
                'ready_date': fields.Datetime.now(),
            })
            try:
                qr_order.sudo().message_post(
                    body='Order marked Ready automatically after POS payment: %s' % (
                        pos_order.display_name or pos_order.name or pos_order.pos_reference or ''
                    )
                )
            except Exception:
                # Avoid blocking payment flow because of chatter/mail issues.
                pass


    def _qtcafe_sync_qr_order_cancelled(self, force=False):
        """Mark linked operations orders as cancelled.

        ``force=True`` is used before deleting a draft POS order from the POS
        interface, because draft deletion does not necessarily set state='cancel'.
        """
        for pos_order in self:
            qr_order = pos_order.qtcafe_qr_order_id
            if not qr_order:
                continue
            if not force and pos_order.state != 'cancel':
                continue
            if qr_order.state in ('cancelled', 'ready'):
                continue

            qr_order.sudo().write({
                'state': 'cancelled',
                'ready_date': False,
            })
            try:
                qr_order.sudo().message_post(
                    body='Order marked Cancelled automatically from POS: %s' % (
                        pos_order.display_name
                        or pos_order.name
                        or pos_order.pos_reference
                        or ''
                    )
                )
            except Exception:
                pass


    def write(self, vals):
        res = super().write(vals)
        if 'state' in vals:
            self._qtcafe_sync_qr_order_ready()
            self._qtcafe_sync_qr_order_cancelled()
        return res

    def action_pos_order_paid(self):
        res = super().action_pos_order_paid()
        self._qtcafe_sync_qr_order_ready()
        return res


    def action_pos_order_cancel(self):
        res = super().action_pos_order_cancel()
        self._qtcafe_sync_qr_order_cancelled(force=True)
        return res


    def action_cancel(self):
        res = super().action_cancel()
        self._qtcafe_sync_qr_order_cancelled(force=True)
        return res


    def unlink(self):
        # The POS trash/delete action commonly removes a draft order directly.
        # Synchronize the linked QR order before the POS record disappears.
        self._qtcafe_sync_qr_order_cancelled(force=True)
        return super().unlink()
