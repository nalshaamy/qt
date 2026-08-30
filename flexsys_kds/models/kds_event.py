# -*- coding: utf-8 -*-
from odoo import api, fields, models


class KdsEvent(models.Model):
    _name = 'kds.event'
    _description = 'FlexSys KDS Audit Log'
    _order = 'create_date desc'

    order_id = fields.Many2one('kds.order', required=True, ondelete='cascade')
    station_id = fields.Many2one('kds.station')
    user_id = fields.Many2one('res.users', default=lambda self: self.env.user)

    event_type = fields.Selection([
        ('order_created', 'Order Created'),
        ('order_routed', 'Order Routed'),
        ('station_received', 'Station Received'),
        ('preparation_started', 'Preparation Started'),
        ('line_ready', 'Line Ready'),
        ('line_added', 'Line Added'),
        ('line_removed', 'Line Removed / Cancelled'),
        ('order_updated', 'Order Updated'),
        ('status_changed', 'Status Changed'),
        ('order_reopened', 'Order Reopened'),
        ('order_completed', 'Order Completed'),
        ('reprint', 'Reprint'),
        ('station_moved', 'Moved Between Stations'),
        ('priority_changed', 'Priority Changed'),
        # UI/DATA FIX ("Master Change Request", item 19, "Audit Log
        # Event Types"): "بدل استخدام Override العام لأحداث الطباعة،
        # استخدم أسماء أوضح مثل: Print Retry, Printer Fallback."
        # Confirmed live: models/kds_print_job.py's own
        # action_mark_failed() and models/kds_order.py's own/
        # models/pos_order.py's own no-printer-configured paths all
        # logged the same generic 'override' value, giving no way to
        # tell a routine technical print retry apart from a genuine
        # manager override (a priority change, a manual state
        # transition bypassing the normal workflow, etc.) just by
        # scanning the Event Type column. Two new, printing-specific
        # values added here - the pre-existing 'override' value itself
        # is kept completely unchanged/unremoved (still used for actual
        # manager overrides elsewhere, e.g. kds_order_line.py's own
        # cross-station moves) so no historical record's own stored
        # value is reinterpreted or orphaned by this addition; only the
        # NEW writes below (this same version onward) use the new,
        # clearer values instead.
        ('print_retry', 'Print Retry'),
        ('printer_fallback', 'Printer Fallback'),
        ('override', 'Override'),
    ], required=True)

    old_value = fields.Char()
    new_value = fields.Char()
    note = fields.Char()

    @api.model
    def log(self, order, event_type, station=False, old_value=False, new_value=False, note=False):
        return self.create({
            'order_id': order.id,
            'station_id': station.id if station else False,
            'event_type': event_type,
            'old_value': old_value,
            'new_value': new_value,
            'note': note,
        })
