from odoo import api, fields, models, _
from odoo.exceptions import UserError


class FlexSysOrderLine(models.Model):
    _name = 'flexsys.operations.order.line'
    _description = 'Operations Order Line'

    order_id = fields.Many2one('flexsys.operations.order', required=True, ondelete='cascade', index=True)
    product_id = fields.Many2one('product.product', required=True, index=True)
    name = fields.Char(string='Product Description', related='product_id.display_name', store=True)
    qty = fields.Float(default=1)
    price_unit = fields.Monetary()
    subtotal = fields.Monetary(compute='_compute_subtotal', store=True)
    currency_id = fields.Many2one(related='order_id.currency_id')
    note = fields.Char(string='Options / Add-ons')
    preparation_state = fields.Selection([
        ('new', 'New'),
        ('preparing', 'Preparing'),
        ('ready', 'Ready'),
        ('unavailable', 'Unavailable'),
        ('cancelled', 'Cancelled'),
    ], string='Preparation Status', default='new', required=True, index=True)
    unavailable_reason = fields.Selection([
        ('out_of_stock', 'Out of Stock'),
        ('equipment', 'Equipment Issue'),
        ('temporarily_stopped', 'Temporarily Stopped'),
        ('other', 'Other'),
    ], string='Unavailable Reason')
    kitchen_note = fields.Char(string='Kitchen Note')
    started_at = fields.Datetime(readonly=True, copy=False)
    ready_at = fields.Datetime(readonly=True, copy=False)

    @api.onchange('product_id')
    def _onchange_product_id(self):
        for line in self:
            if line.product_id:
                line.price_unit = line.product_id.lst_price

    @api.depends('qty', 'price_unit')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.qty * line.price_unit

    def _set_preparation_state(self, state, **extra_values):
        allowed = dict(self._fields['preparation_state'].selection)
        if state not in allowed:
            raise UserError(_('Unsupported preparation state: %s') % state)
        now = fields.Datetime.now()
        values = {'preparation_state': state, **extra_values}
        if state == 'preparing':
            values.setdefault('started_at', now)
            values.setdefault('ready_at', False)
        elif state == 'ready':
            values.setdefault('ready_at', now)
        elif state == 'new':
            values.setdefault('started_at', False)
            values.setdefault('ready_at', False)
            values.setdefault('unavailable_reason', False)
        elif state != 'unavailable':
            values.setdefault('unavailable_reason', False)
        previous_states = {line.id: line.preparation_state for line in self}
        result = self.write(values)
        orders = self.mapped('order_id')
        orders._sync_state_from_lines()
        if not self.env.context.get('skip_operation_event'):
            for line in self:
                old_state = previous_states.get(line.id)
                if old_state != line.preparation_state:
                    line.order_id._emit_event('order_line.state_changed', {
                        'line_id': line.id,
                        'product_id': line.product_id.id,
                        'product': line.product_id.display_name,
                        'from': old_state,
                        'to': line.preparation_state,
                        'unavailable_reason': line.unavailable_reason or False,
                    })
        return result

    def action_start_preparation(self):
        return self._set_preparation_state('preparing')

    def action_mark_ready(self):
        return self._set_preparation_state('ready')

    def action_mark_unavailable(self):
        return self._set_preparation_state('unavailable')

    def action_cancel_line(self):
        return self._set_preparation_state('cancelled')

    def action_reset_preparation(self):
        return self._set_preparation_state('new')
