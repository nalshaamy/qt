import secrets

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class FlexSysOrder(models.Model):

    def _emit_event(self, event_type, payload=None):
        """Publish an operational event unless explicitly suppressed."""
        if self.env.context.get("skip_operation_event"):
            return self.env["flexsys.operation.event"]
        from ..services.event_service import EventService
        service = EventService(self.env)
        events = self.env["flexsys.operation.event"]
        for order in self:
            events |= service.emit(event_type, order, payload=payload or {})
        return events

    def _workflow_service(self):
        from ..services.workflow_service import WorkflowService
        return WorkflowService(self.env)

    def _transition_to(self, target_state, values=None):
        """Apply a validated order lifecycle transition."""
        return self._workflow_service().transition_order(self, target_state, values=values)

    def write(self, vals):
        if 'state' in vals and not self.env.context.get('workflow_transition'):
            service = self._workflow_service()
            for order in self:
                service.validate_order_transition(order, vals['state'])
        # Prevent duplicated accept/load actions from causing unnecessary concurrent state writes.
        if vals.get('state') == 'accepted':
            self = self.filtered(lambda o: o.state not in ('accepted', 'preparing', 'ready', 'cancelled'))
            if not self:
                return True
        previous_states = {order.id: order.state for order in self} if 'state' in vals else {}
        result = super().write(vals)
        if 'state' in vals and not self.env.context.get('skip_operation_event'):
            for order in self:
                old_state = previous_states.get(order.id)
                if old_state != order.state:
                    order._emit_event('order.state_changed', {
                        'from': old_state,
                        'to': order.state,
                        'progress': order.preparation_progress,
                    })
        return result

    pos_order_id = fields.Many2one('pos.order', string='POS Order', readonly=True, copy=False)
    loaded_to_pos = fields.Boolean(string='Loaded to POS', readonly=True, copy=False)
    _name = 'flexsys.operations.order'
    _description = 'Operations Order'

    pos_config_id = fields.Many2one('pos.config', string='Point of Sale', index=True, help='Point of Sale configuration that should receive this order.')
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
        ('self_order', 'Self Order'),
        ('qr', 'Self Order'),  # Legacy stored value kept for backward compatibility.
        ('pos', 'Point of Sale'),
        ('cashier', 'Cashier'),
        ('waiter', 'Waiter'),
        ('kiosk', 'Kiosk'),
        ('website', 'Website'),
        ('mobile', 'Mobile App'),
        ('api', 'API'),
    ], string='Order Source', default='self_order', required=True, tracking=True, index=True)
    priority = fields.Selection([
        ('normal', 'Normal'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ], default='normal', required=True, tracking=True, index=True)
    requested_time = fields.Datetime(
        string='Requested Time',
        tracking=True,
        help='Requested pickup or delivery time. Empty means as soon as possible.',
    )
    state = fields.Selection([
        ('scheduled', 'Scheduled'),
        ('new', 'New'),
        ('accepted', 'Accepted'),
        ('preparing', 'Preparing'),
        ('partially_ready', 'Partially Ready'),
        ('ready', 'Ready'),
        ('completed', 'Completed'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ], default='new', required=True, tracking=True, index=True)
    line_ids = fields.One2many('flexsys.operations.order.line', 'order_id', string='Order Lines')
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
    table_id = fields.Many2one('flexsys.operations.table', string='Table', ondelete='set null', tracking=True)
    car_details = fields.Char(string='Car Details', tracking=True)
    delivery_latitude = fields.Float(digits=(10, 7), tracking=True)
    delivery_longitude = fields.Float(digits=(10, 7), tracking=True)
    delivery_distance_km = fields.Float(digits=(10, 2), tracking=True)
    delivery_google_maps_url = fields.Char(string='Delivery Map Link', readonly=True)
    accepted_user_id = fields.Many2one('res.users', readonly=True)
    accepted_date = fields.Datetime(readonly=True)
    ready_date = fields.Datetime(readonly=True)
    completed_date = fields.Datetime(readonly=True, copy=False)
    preparation_progress = fields.Float(
        string='Preparation Progress',
        compute='_compute_preparation_progress',
        store=True,
        digits=(5, 2),
    )
    ready_line_count = fields.Integer(compute='_compute_preparation_progress', store=True)
    active_line_count = fields.Integer(compute='_compute_preparation_progress', store=True)
    unavailable_line_count = fields.Integer(compute='_compute_preparation_progress', store=True)
    task_ids = fields.One2many('flexsys.execution.task', 'order_id', string='Execution Tasks')
    task_count = fields.Integer(compute='_compute_task_count')
    tracking_token = fields.Char(
        default=lambda self: secrets.token_urlsafe(24),
        required=True,
        copy=False,
        readonly=True,
        index=True,
    )

    _tracking_token_unique = models.Constraint(
        'UNIQUE(tracking_token)',
        'Order tracking token must be unique.',
    )

    def _customer_timeline(self, language='ar'):
        """Return a fixed, customer-friendly lifecycle timeline without percentages."""
        self.ensure_one()
        events = self.env['flexsys.operation.event'].sudo().search([
            ('aggregate_model', '=', self._name),
            ('aggregate_id', '=', self.id),
            ('visibility', 'in', ('customer', 'both')),
        ], order='occurred_at asc, id asc')

        state_times = {'new': self.create_date}
        for event in events:
            if event.event_type == 'order.created' and not state_times.get('new'):
                state_times['new'] = event.occurred_at
            elif event.event_type == 'order.state_changed':
                target = (event.payload or {}).get('to')
                if target and target not in state_times:
                    state_times[target] = event.occurred_at
        if self.accepted_date:
            state_times.setdefault('accepted', self.accepted_date)
        if self.ready_date:
            state_times.setdefault('ready', self.ready_date)
        if self.completed_date:
            state_times.setdefault('completed', self.completed_date)

        labels = {
            'ar': {
                'new': 'تم استلام الطلب',
                'accepted': 'تم قبول الطلب',
                'preparing': 'قيد التحضير',
                'ready': 'جاهز للاستلام',
                'completed': 'تم التسليم',
                'cancelled': 'تم إلغاء الطلب',
                'rejected': 'تم رفض الطلب',
            },
            'en': {
                'new': 'Order received',
                'accepted': 'Order accepted',
                'preparing': 'Preparing',
                'ready': 'Ready for pickup',
                'completed': 'Delivered',
                'cancelled': 'Order cancelled',
                'rejected': 'Order rejected',
            },
        }['ar' if language == 'ar' else 'en']
        ordered_states = ['new', 'accepted', 'preparing', 'ready', 'completed']
        state_rank = {
            'scheduled': 0, 'new': 0, 'accepted': 1, 'preparing': 2,
            'partially_ready': 2, 'ready': 3, 'completed': 4,
        }
        current_rank = state_rank.get(self.state, 0)
        terminal_state = self.state if self.state in ('cancelled', 'rejected') else False

        def format_time(value):
            if not value:
                return False
            local_dt = fields.Datetime.context_timestamp(self, fields.Datetime.to_datetime(value))
            label = local_dt.strftime('%I:%M %p').lstrip('0')
            if language == 'ar':
                label = label.replace('AM', 'ص').replace('PM', 'م')
            return label

        steps = []
        for index, state in enumerate(ordered_states):
            occurred_at = state_times.get(state)
            status = 'completed' if index < current_rank else 'current' if index == current_rank else 'pending'
            if self.state == 'completed':
                status = 'completed'
            if terminal_state and index > current_rank:
                status = 'pending'
            steps.append({
                'key': state,
                'message': labels[state],
                'occurred_at': occurred_at,
                'time_label': format_time(occurred_at),
                'status': status,
            })

        if terminal_state:
            terminal_time = state_times.get(terminal_state) or self.write_date
            steps = [step for step in steps if step['status'] == 'completed']
            steps.append({
                'key': terminal_state,
                'message': labels[terminal_state],
                'occurred_at': terminal_time,
                'time_label': format_time(terminal_time),
                'status': 'cancelled',
            })
        return steps

    def _customer_tracking_payload(self, language='ar'):
        self.ensure_one()
        state_labels_ar = {
            'scheduled': 'مجدول', 'new': 'تم استلام الطلب', 'accepted': 'تم قبول الطلب',
            'preparing': 'قيد التحضير', 'partially_ready': 'قيد التحضير',
            'ready': 'جاهز للاستلام', 'completed': 'تم التسليم', 'rejected': 'مرفوض',
            'cancelled': 'ملغي',
        }
        state_labels_en = dict(self._fields['state'].selection)
        return {
            'name': self.name,
            'state': self.state,
            'state_label': (state_labels_ar if language == 'ar' else state_labels_en).get(self.state, self.state),
            'requested_time': self.requested_time,
            'create_date': self.create_date,
            'timeline': self._customer_timeline(language=language),
            'terminal': self.state in ('completed', 'cancelled', 'rejected'),
        }

    @api.model
    def _flexsys_search_results(self, session, query, limit=8):
        """Search Operations records within the active company and branch context."""
        query = (query or '').strip()
        if len(query) < 2:
            return []
        pos_configs = session.branch_id.operations_pos_config_ids if session.branch_id else session.user_id.operations_pos_config_ids.filtered(
            lambda pos: pos.company_id == session.company_id
        )
        if not pos_configs:
            return []
        domain = [
            ('pos_config_id', 'in', pos_configs.ids),
            '|', '|', '|',
            ('name', 'ilike', query),
            ('customer_name', 'ilike', query),
            ('customer_mobile', 'ilike', query),
            ('partner_id.name', 'ilike', query),
        ]
        orders = self.sudo().search(domain, order='create_date desc, id desc', limit=limit)
        state_labels = dict(self._fields['state'].selection)
        source_labels = dict(self._fields['source'].selection)
        results = []
        for order in orders:
            customer = order.partner_id.name or order.customer_name or order.customer_mobile or _('Guest')
            subtitle = '%s · %s · %s' % (
                customer,
                state_labels.get(order.state, order.state),
                source_labels.get(order.source, order.source),
            )
            results.append({
                'title': order.name,
                'subtitle': subtitle,
                'type': _('Order'),
                'icon': 'fa-receipt',
                'url': '/flexsys/operations/orders?focus_order=%s#order-%s' % (order.id, order.id),
            })
        return results

    @api.model
    def _flexsys_workspace_metrics(self, session):
        """Return Operations metrics for the active FlexSys company/branch context."""
        pos_configs = session.branch_id.operations_pos_config_ids if session.branch_id else session.user_id.operations_pos_config_ids.filtered(
            lambda pos: pos.company_id == session.company_id
        )
        domain = [('pos_config_id', 'in', pos_configs.ids)] if pos_configs else [('id', '=', 0)]
        orders = self.sudo().search(domain)
        Task = self.env['flexsys.execution.task'].sudo()
        task_domain = [('company_id', '=', session.company_id.id)]
        if pos_configs:
            task_domain.append(('pos_config_id', 'in', pos_configs.ids))
        else:
            task_domain.append(('id', '=', 0))
        return {
            'active_orders': len(orders.filtered(lambda order: order.state in ('new', 'accepted', 'preparing', 'partially_ready'))),
            'ready_orders': len(orders.filtered(lambda order: order.state == 'ready')),
            'scheduled_orders': len(orders.filtered(lambda order: order.state == 'scheduled')),
            'open_tasks': Task.search_count(task_domain + [('state', 'in', ('new', 'preparing'))]),
            'stations': self.env['flexsys.execution.station'].sudo().search_count([
                ('company_id', '=', session.company_id.id),
                ('pos_config_ids', 'in', pos_configs.ids),
                ('active', '=', True),
            ]) if pos_configs else 0,
        }

    def _compute_task_count(self):
        for order in self:
            order.task_count = len(order.task_ids)

    def _get_execution_route_for_line(self, line):
        self.ensure_one()
        if not self.pos_config_id:
            return self.env['flexsys.execution.route']
        return self.env['flexsys.execution.route'].search([
            ('active', '=', True),
            ('company_id', '=', self.pos_config_id.company_id.id),
            ('pos_config_id', '=', self.pos_config_id.id),
            ('product_tmpl_id', '=', line.product_id.product_tmpl_id.id),
        ], order='sequence, id', limit=1)

    def _get_station_for_line(self, line):
        return self._get_execution_route_for_line(line).station_id

    def _ensure_execution_tasks(self):
        Task = self.env['flexsys.execution.task']
        for order in self:
            existing_line_ids = set(order.task_ids.mapped('order_line_id').ids)
            values = []
            for line in order.line_ids.filtered(lambda item: item.id not in existing_line_ids):
                route = order._get_execution_route_for_line(line)
                station = route.station_id
                estimated_minutes = (
                    route.estimated_minutes
                    or station.default_estimated_minutes
                    if station else 0
                )
                values.append({
                    'order_id': order.id,
                    'order_line_id': line.id,
                    'station_id': station.id if station else False,
                    'estimated_minutes': estimated_minutes,
                    'sequence': line.id,
                })
            if values:
                Task.create(values)
        return True

    @api.depends('line_ids.preparation_state')
    def _compute_preparation_progress(self):
        for order in self:
            active_lines = order.line_ids.filtered(
                lambda line: line.preparation_state not in ('cancelled', 'unavailable')
            )
            ready_lines = active_lines.filtered(lambda line: line.preparation_state == 'ready')
            order.active_line_count = len(active_lines)
            order.ready_line_count = len(ready_lines)
            order.unavailable_line_count = len(
                order.line_ids.filtered(lambda line: line.preparation_state == 'unavailable')
            )
            order.preparation_progress = (
                (len(ready_lines) / len(active_lines)) * 100.0 if active_lines else 0.0
            )

    def _sync_state_from_lines(self):
        """Synchronize the order lifecycle from line-level preparation states.

        The method deliberately leaves terminal states untouched and never moves
        a newly created order forward before it has been accepted.
        """
        terminal_states = {'completed', 'cancelled', 'rejected'}
        for order in self:
            if order.state in terminal_states or order.state in ('scheduled', 'new'):
                continue
            active_lines = order.line_ids.filtered(
                lambda line: line.preparation_state not in ('cancelled', 'unavailable')
            )
            if not active_lines:
                continue
            line_states = set(active_lines.mapped('preparation_state'))
            if line_states == {'ready'}:
                values = {'state': 'ready'}
                if not order.ready_date:
                    values['ready_date'] = fields.Datetime.now()
                order.with_context(skip_line_state_sync=True)._transition_to('ready', {
                    key: value for key, value in values.items() if key != 'state'
                })
            elif 'ready' in line_states:
                order.with_context(skip_line_state_sync=True)._transition_to('partially_ready')
            elif 'preparing' in line_states:
                order.with_context(skip_line_state_sync=True)._transition_to('preparing')


    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('flexsys.operations.order') or _('New')
        orders = super().create(vals_list)
        for order in orders:
            order._emit_event('order.created', {
                'source': order.source,
                'state': order.state,
                'requested_time': fields.Datetime.to_string(order.requested_time) if order.requested_time else False,
            })
        return orders

    @api.depends('line_ids.subtotal')
    def _compute_amount_total(self):
        for order in self:
            order.amount_total = sum(order.line_ids.mapped('subtotal'))

    def _get_receipt_text(self):
        self.ensure_one()
        config = self.env['flexsys.operations.printer.config']._get_active_config()
        lines = []
        lines.append(config.shop_name or 'FlexSys')
        lines.append('Order')
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
        config = self.env['flexsys.operations.printer.config']._get_active_config()
        for order in self:
            config.print_text(order._get_receipt_text())
            order.message_post(body=_('Receipt sent to cashier printer.'))
        return True

    def action_accept(self):
        for order in self:
            if order.state not in ('accepted', 'preparing', 'ready', 'cancelled'):
                order._transition_to('accepted', {
                    'accepted_user_id': self.env.user.id,
                    'accepted_date': fields.Datetime.now(),
                })
            order._ensure_execution_tasks()
            if order.pos_config_id and not order.pos_order_id:
                try:
                    order.action_create_pos_order()
                except Exception as exc:
                    order.message_post(body=_('Creating POS order failed: %s') % exc)
        config = self.env['flexsys.operations.printer.config']._get_active_config()
        if config.auto_print_on_accept:
            for order in self:
                try:
                    config.print_text(order._get_receipt_text())
                    order.message_post(body=_('Receipt printed automatically.'))
                except Exception as exc:
                    order.message_post(body=_('Automatic receipt printing failed: %s') % exc)

    def action_prepare(self):
        self._ensure_execution_tasks()
        self._transition_to('preparing')
        lines = self.mapped('line_ids').filtered(lambda line: line.preparation_state == 'new')
        if lines:
            lines._set_preparation_state('preparing')
        return True

    def action_ready(self):
        self._transition_to('ready', {'ready_date': fields.Datetime.now()})
        lines = self.mapped('line_ids').filtered(
            lambda line: line.preparation_state not in ('ready', 'cancelled', 'unavailable')
        )
        if lines:
            lines._set_preparation_state('ready')
        return True

    def action_complete(self):
        self._transition_to('completed', {'completed_date': fields.Datetime.now()})
        return True

    def action_reject(self):
        self._transition_to('rejected')
        return True

    def action_cancel(self):
        self._transition_to('cancelled')
        lines = self.mapped('line_ids').filtered(
            lambda line: line.preparation_state not in ('ready', 'cancelled')
        )
        if lines:
            lines._set_preparation_state('cancelled')
        return True

    def _get_open_pos_session(self):
        self.ensure_one()
        if not self.pos_config_id:
            raise UserError(_("Please select a Point of Sale for this order."))
        session = self.env['pos.session'].search([
            ('config_id', '=', self.pos_config_id.id),
            ('state', 'in', ['opened', 'opening_control']),
        ], limit=1, order='id desc')
        if not session:
            raise UserError(_("No open POS session found for %s.") % self.pos_config_id.display_name)
        return session

    def action_create_pos_order(self):
        """Create a real backend POS order linked to the open POS session.

        This makes self-service orders visible in the POS Orders/Ticket screen. Payment remains
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
                raise UserError(_("This order has no valid products to load into POS."))

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
                'operations_qr_order_id': order.id,
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
            if vals.get('state') == 'accepted':
                state_values = dict(vals)
                state_values.pop('state', None)
                order._transition_to('accepted', state_values)
            else:
                order.write(vals)
            order.message_post(body=_('POS order created: %s') % pos_order.display_name)
        return True

