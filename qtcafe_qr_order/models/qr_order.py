from odoo import api, fields, models, _
from odoo.exceptions import UserError


class QtCafeQrOrder(models.Model):

    def write(self, vals):
        # Prevent duplicated accept/load actions from causing unnecessary concurrent state writes.
        if vals.get('state') == 'accepted':
            self = self.filtered(lambda o: o.state not in ('accepted', 'preparing', 'ready', 'cancelled'))
            if not self:
                return True
        return super().write(vals)

    pos_order_id = fields.Many2one('pos.order', string='POS Order', readonly=True, copy=False)
    loaded_to_pos = fields.Boolean(string='Loaded to POS', readonly=True, copy=False)
    _name = 'qtcafe.qr.order'
    _description = 'QT Cafe QR Order'

    pos_config_id = fields.Many2one('pos.config', string='Point of Sale', index=True, help='POS configuration that should receive this QR order.')
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(default=lambda self: _('New'), copy=False, readonly=True, tracking=True)
    partner_id = fields.Many2one(
        'res.partner',
        string='Registered Customer',
        index=True,
        tracking=True,
        ondelete='set null',
    )
    customer_name = fields.Char(tracking=True)
    customer_mobile = fields.Char(tracking=True)
    source = fields.Selection([
        ('qr', 'QR Menu'),
        ('cashier', 'Cashier'),
    ], default='qr', required=True, tracking=True)
    state = fields.Selection([
        ('new', 'New'),
        ('accepted', 'Accepted'),
        ('preparing', 'Preparing'),
        ('ready', 'Ready'),
        ('cancelled', 'Cancelled'),
    ], default='new', required=True, tracking=True)
    line_ids = fields.One2many('qtcafe.qr.order.line', 'order_id', string='Order Lines')
    amount_total = fields.Monetary(compute='_compute_amount_total', store=True)
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    note = fields.Text()
    payment_method = fields.Selection([
        ('cash', 'Cash'),
        ('card', 'Card'),
        ('wallet', 'Electronic Wallet'),
    ], string='Payment Method', required=True, default='cash', tracking=True)
    order_type = fields.Selection([
        ('dine_in', 'Dine In'),
        ('takeaway', 'Takeaway'),
        ('car', 'Car Order'),
        ('delivery', 'Delivery'),
    ], string='Order Type', required=True, default='takeaway', tracking=True)
    table_id = fields.Many2one('qtcafe.table', string='Table', ondelete='set null', tracking=True)
    car_details = fields.Char(string='Car Details', tracking=True)
    delivery_latitude = fields.Float(digits=(10, 7), tracking=True)
    delivery_longitude = fields.Float(digits=(10, 7), tracking=True)
    delivery_distance_km = fields.Float(digits=(10, 2), tracking=True)
    delivery_google_maps_url = fields.Char(string='Delivery Map Link', readonly=True)
    accepted_user_id = fields.Many2one('res.users', readonly=True)
    accepted_date = fields.Datetime(readonly=True)
    ready_date = fields.Datetime(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('qtcafe.qr.order') or _('New')
        return super().create(vals_list)

    @api.depends('line_ids.subtotal')
    def _compute_amount_total(self):
        for order in self:
            order.amount_total = sum(order.line_ids.mapped('subtotal'))

    def _get_receipt_text(self):
        self.ensure_one()
        config = self.env['qtcafe.qr.printer.config']._get_active_config()
        lines = []
        lines.append(config.shop_name or 'QT Cafe')
        lines.append('QR Order')
        lines.append('-' * 32)
        lines.append('Order: %s' % self.name)
        lines.append('Date: %s' % fields.Datetime.context_timestamp(self, self.create_date).strftime('%Y-%m-%d %H:%M'))
        if self.customer_name:
            lines.append('Customer: %s' % self.customer_name)
        if self.customer_mobile:
            lines.append('Mobile: %s' % self.customer_mobile)
        lines.append('Order Type: %s' % dict(self._fields['order_type'].selection).get(self.order_type, self.order_type))
        lines.append('Payment: %s' % dict(self._fields['payment_method'].selection).get(self.payment_method, self.payment_method))
        if self.table_id:
            lines.append('Table: %s' % self.table_id.display_name)
        if self.car_details:
            lines.append('Car: %s' % self.car_details)
        if self.delivery_google_maps_url:
            lines.append('Location: %s' % self.delivery_google_maps_url)
        lines.append('-' * 32)
        for line in self.line_ids:
            lines.append('%s x %s' % (line.qty, line.product_id.display_name))
            if line.note:
                lines.append('  %s' % line.note)
            lines.append('  %.2f' % (line.subtotal or 0.0))
        lines.append('-' * 32)
        lines.append('Total: %.2f %s' % (self.amount_total or 0.0, self.currency_id.name or ''))
        if self.note:
            lines.append('Note: %s' % self.note)
        lines.append('Thank you')
        return '\n'.join(lines)

    def action_print_receipt(self):
        config = self.env['qtcafe.qr.printer.config']._get_active_config()
        for order in self:
            config.print_text(order._get_receipt_text())
            order.message_post(body=_('Receipt sent to cashier printer.'))
        return True

    def action_accept(self):
        for order in self:
            if order.state not in ('accepted', 'preparing', 'ready', 'cancelled'):
                order.write({
                    'state': 'accepted',
                    'accepted_user_id': self.env.user.id,
                    'accepted_date': fields.Datetime.now(),
                })
            if order.pos_config_id and not order.pos_order_id:
                try:
                    order.action_create_pos_order()
                except Exception as exc:
                    order.message_post(body=_('Creating POS order failed: %s') % exc)
        config = self.env['qtcafe.qr.printer.config']._get_active_config()
        if config.auto_print_on_accept:
            for order in self:
                try:
                    config.print_text(order._get_receipt_text())
                    order.message_post(body=_('Receipt printed automatically.'))
                except Exception as exc:
                    order.message_post(body=_('Automatic receipt printing failed: %s') % exc)

    def action_prepare(self):
        self.write({'state': 'preparing'})

    def action_ready(self):
        self.write({'state': 'ready', 'ready_date': fields.Datetime.now()})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def _get_open_pos_session(self):
        self.ensure_one()
        if not self.pos_config_id:
            raise UserError(_("Please select a Point of Sale for this QR order."))
        session = self.env['pos.session'].search([
            ('config_id', '=', self.pos_config_id.id),
            ('state', 'in', ['opened', 'opening_control']),
        ], limit=1, order='id desc')
        if not session:
            raise UserError(_("No open POS session found for %s.") % self.pos_config_id.display_name)
        return session

    def action_create_pos_order(self):
        """Create a real backend POS order linked to the open POS session.

        This makes QR orders visible in the POS Orders/Ticket screen. Payment remains
        zero until the cashier opens the POS order and completes payment normally.
        """
        PosOrder = self.env['pos.order'].sudo()
        for order in self:
            if order.pos_order_id:
                if order.partner_id and not order.pos_order_id.partner_id:
                    order.pos_order_id.sudo().write({'partner_id': order.partner_id.id})
                order.loaded_to_pos = True
                continue

            session = order._get_open_pos_session()
            lines = []
            amount_total = 0.0

            for line in order.line_ids:
                product = line.product_id
                if not product:
                    continue
                qty = float(line.qty or 1.0)
                price = float(line.price_unit or product.lst_price or 0.0)
                subtotal = qty * price
                amount_total += subtotal
                lines.append((0, 0, {
                    'product_id': product.id,
                    'qty': qty,
                    'price_unit': price,
                    'discount': 0.0,
                    'full_product_name': product.display_name,
                    'tax_ids': [(6, 0, product.taxes_id.ids)],
                    'price_subtotal': subtotal,
                    'price_subtotal_incl': subtotal,
                    'customer_note': line.note or '',
                }))

            if not lines:
                raise UserError(_("This QR order has no valid products to load into POS."))

            pos_order_vals = {
                'name': order.name,
                'tracking_number': order.name,
                'floating_order_name': order.name,
                'session_id': session.id,
                'config_id': session.config_id.id,
                'user_id': self.env.user.id,
                'company_id': session.company_id.id,
                'partner_id': order.partner_id.id if order.partner_id else False,
                'pos_reference': order.name,
                'qtcafe_qr_order_id': order.id,
                'lines': lines,
                'amount_tax': 0.0,
                'amount_total': amount_total,
                'amount_paid': 0.0,
                'amount_return': 0.0,
                'state': 'draft',
            }
            pos_order = PosOrder.create(pos_order_vals)

            # Keep the Odoo-generated POS order name; store link on QR order.
            vals = {
                'pos_order_id': pos_order.id,
                'loaded_to_pos': True,
            }
            if order.state == 'new':
                vals.update({
                    'state': 'accepted',
                    'accepted_user_id': self.env.user.id,
                    'accepted_date': fields.Datetime.now(),
                })
            order.write(vals)
            order.message_post(body=_('POS order created: %s') % pos_order.display_name)
        return True

