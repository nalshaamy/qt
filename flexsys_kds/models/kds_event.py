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
