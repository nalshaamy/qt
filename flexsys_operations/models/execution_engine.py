from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class FlexSysExecutionStation(models.Model):
    _name = 'flexsys.execution.station'
    _description = 'Execution Station'
    _order = 'sequence, name, id'

    name = fields.Char(required=True, index=True)
    code = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company, index=True
    )
    pos_config_ids = fields.Many2many(
        'pos.config',
        'flexsys_station_pos_config_rel',
        'station_id',
        'pos_config_id',
        string='Branches / Points of Sale',
    )
    status = fields.Selection([
        ('active', 'Active'),
        ('paused', 'Paused'),
        ('offline', 'Offline'),
    ], default='active', required=True, index=True)
    capacity = fields.Integer(
        default=0,
        help='Maximum active tasks. Set to 0 for unlimited capacity.',
    )
    queue_mode = fields.Selection([
        ('fifo', 'First In, First Out'),
        ('priority', 'Priority First'),
        ('requested_time', 'Requested Time First'),
        ('balanced', 'Balanced'),
    ], default='balanced', required=True,
        help='Controls how waiting tasks are ordered inside this station.')
    default_estimated_minutes = fields.Integer(
        string='Default Estimated Minutes',
        default=10,
        help='Default target duration used when a routing rule has no specific estimate.',
    )
    resource_ids = fields.One2many('flexsys.execution.resource', 'station_id', string='Resources')
    available_resource_count = fields.Integer(compute='_compute_metrics')
    busy_resource_count = fields.Integer(compute='_compute_metrics')
    effective_capacity = fields.Integer(compute='_compute_metrics')
    assigned_user_ids = fields.Many2many(
        'flexsys.platform.user',
        'flexsys_station_platform_user_rel',
        'station_id',
        'user_id',
        string='Assigned FlexSys Users',
    )
    enable_kds = fields.Boolean(
        string='Enable KDS',
        default=True,
        help='Display this station and its tasks in the kitchen/station workspace.',
    )
    enable_printing = fields.Boolean(
        string='Enable Station Printing',
        default=False,
        help='Allow station tickets to be generated for tasks assigned to this station.',
    )
    auto_print = fields.Boolean(
        string='Auto Print Request',
        default=False,
        help='Create a print request automatically when a task reaches this station. '
             'A printer connector can consume the request; the task remains available if printing fails.',
    )
    print_copies = fields.Integer(string='Copies', default=1)
    ticket_template = fields.Selection([
        ('station', 'Station Ticket'),
        ('packing', 'Packing Ticket'),
    ], string='Ticket Template', default='station', required=True)
    ticket_show_customer = fields.Boolean(string='Show Customer', default=True)
    ticket_show_notes = fields.Boolean(string='Show Notes', default=True)
    ticket_show_qr = fields.Boolean(string='Show QR Code', default=False)
    task_ids = fields.One2many('flexsys.execution.task', 'station_id')
    active_task_count = fields.Integer(compute='_compute_metrics')
    waiting_task_count = fields.Integer(compute='_compute_metrics')
    delayed_task_count = fields.Integer(compute='_compute_metrics')
    completed_task_count = fields.Integer(compute='_compute_metrics')
    load_percent = fields.Float(compute='_compute_metrics')
    average_duration_minutes = fields.Float(compute='_compute_metrics')
    health = fields.Selection([
        ('healthy', 'Healthy'),
        ('warning', 'Warning'),
        ('critical', 'Critical'),
        ('offline', 'Offline'),
    ], compute='_compute_metrics', store=False)

    _code_company_unique = models.Constraint(
        'UNIQUE(code, company_id)',
        'Station code must be unique per company.',
    )

    @api.depends(
        'task_ids.state',
        'task_ids.is_delayed',
        'task_ids.actual_minutes',
        'resource_ids.status',
        'resource_ids.capacity',
        'capacity',
        'status',
    )
    def _compute_metrics(self):
        for station in self:
            waiting = station.task_ids.filtered(lambda task: task.state == 'new')
            active = station.task_ids.filtered(lambda task: task.state == 'preparing')
            delayed = station.task_ids.filtered(lambda task: task.is_delayed)
            completed = station.task_ids.filtered(lambda task: task.state == 'ready')
            durations = completed.mapped('actual_minutes')
            station.waiting_task_count = len(waiting)
            station.active_task_count = len(active)
            station.delayed_task_count = len(delayed)
            station.completed_task_count = len(completed)
            available_resources = station.resource_ids.filtered(lambda resource: resource.status == 'available')
            busy_resources = station.resource_ids.filtered(lambda resource: resource.status == 'busy')
            operational_resources = station.resource_ids.filtered(lambda resource: resource.status in ('available', 'busy'))
            station.available_resource_count = len(available_resources)
            station.busy_resource_count = len(busy_resources)
            resource_capacity = sum(operational_resources.mapped('capacity'))
            station.effective_capacity = resource_capacity if station.resource_ids else station.capacity
            station.load_percent = (
                (len(active) / station.effective_capacity) * 100.0
                if station.effective_capacity else (100.0 if active else 0.0)
            )
            station.average_duration_minutes = (
                sum(durations) / len(durations) if durations else 0.0
            )
            if station.status != 'active':
                station.health = 'offline'
            elif delayed or (station.effective_capacity and len(active) >= station.effective_capacity):
                station.health = 'critical'
            elif station.effective_capacity and len(active) >= max(1, int(station.effective_capacity * 0.75)):
                station.health = 'warning'
            else:
                station.health = 'healthy'

    def _queue_sort_key(self, task):
        """Return a deterministic queue key for a waiting task."""
        self.ensure_one()
        priority_rank = {'urgent': 0, 'high': 1, 'normal': 2}.get(task.priority, 2)
        requested = fields.Datetime.to_datetime(task.requested_time) if task.requested_time else None
        created = fields.Datetime.to_datetime(task.create_date) if task.create_date else fields.Datetime.now()
        far_future = fields.Datetime.to_datetime('9999-12-31 23:59:59')
        if self.queue_mode == 'fifo':
            return (created, task.id)
        if self.queue_mode == 'priority':
            return (priority_rank, created, task.id)
        if self.queue_mode == 'requested_time':
            return (requested or far_future, priority_rank, created, task.id)
        # Balanced: urgent first, then requested time, then age.
        return (priority_rank, requested or far_future, created, task.id)

    def _ordered_waiting_tasks(self):
        self.ensure_one()
        tasks = self.task_ids.filtered(lambda task: task.state == 'new')
        return tasks.sorted(key=self._queue_sort_key)

    def action_rebuild_queue(self):
        """Persist the current queue order without changing task ownership."""
        for station in self:
            for position, task in enumerate(station._ordered_waiting_tasks(), start=1):
                target_sequence = position * 10
                if task.sequence != target_sequence:
                    task.sequence = target_sequence
        return True

    def action_activate(self):
        self.write({'status': 'active'})
        return True

    def action_pause(self):
        self.write({'status': 'paused'})
        return True

    def action_offline(self):
        self.write({'status': 'offline'})
        return True

    def can_start_task(self):
        self.ensure_one()
        if self.status != 'active':
            return False
        capacity = self.effective_capacity
        return bool(capacity and self.active_task_count < capacity) if self.resource_ids else (not self.capacity or self.active_task_count < self.capacity)

    @api.constrains('capacity')
    def _check_capacity(self):
        for station in self:
            if station.capacity < 0:
                raise UserError(_('Station capacity cannot be negative.'))
            if station.default_estimated_minutes < 0:
                raise UserError(_('Default estimated minutes cannot be negative.'))


    @api.constrains('company_id', 'pos_config_ids', 'assigned_user_ids')
    def _check_scope_consistency(self):
        for station in self:
            if any(pos.company_id != station.company_id for pos in station.pos_config_ids):
                raise UserError(_('All points of sale must belong to the station company.'))
            invalid_users = station.assigned_user_ids.filtered(
                lambda user: station.company_id not in user.company_ids
            )
            if invalid_users:
                raise UserError(_('All assigned users must have access to the station company.'))


class FlexSysExecutionResource(models.Model):
    _name = 'flexsys.execution.resource'
    _description = 'Execution Resource'
    _order = 'station_id, sequence, name, id'

    name = fields.Char(required=True, index=True)
    code = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    resource_type = fields.Selection([
        ('employee', 'Employee'),
        ('machine', 'Machine'),
        ('printer', 'Printer'),
        ('display', 'Display'),
        ('external', 'External Service'),
    ], default='employee', required=True, index=True)
    status = fields.Selection([
        ('available', 'Available'),
        ('busy', 'Busy'),
        ('break', 'On Break'),
        ('offline', 'Offline'),
        ('maintenance', 'Maintenance'),
    ], default='available', required=True, index=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company, index=True
    )
    station_id = fields.Many2one(
        'flexsys.execution.station', required=True, ondelete='cascade', index=True
    )
    platform_user_id = fields.Many2one(
        'flexsys.platform.user', string='FlexSys User', ondelete='set null', index=True
    )
    capacity = fields.Integer(
        default=1,
        help='Number of concurrent tasks this resource can support when available.',
    )
    skills = fields.Char(
        help='Comma-separated operational skills used as a lightweight routing hint.',
    )
    task_ids = fields.One2many('flexsys.execution.task', 'assigned_resource_id')
    active_task_count = fields.Integer(compute='_compute_task_count')

    _code_company_unique = models.Constraint(
        'UNIQUE(code, company_id)',
        'Resource code must be unique per company.',
    )

    @api.depends('task_ids.state')
    def _compute_task_count(self):
        for resource in self:
            resource.active_task_count = len(
                resource.task_ids.filtered(lambda task: task.state == 'preparing')
            )

    def action_available(self):
        self.write({'status': 'available'})
        return True

    def action_break(self):
        self.write({'status': 'break'})
        return True

    def action_offline(self):
        self.write({'status': 'offline'})
        return True

    def action_maintenance(self):
        self.write({'status': 'maintenance'})
        return True

    @api.constrains('capacity')
    def _check_capacity(self):
        for resource in self:
            if resource.capacity < 1:
                raise UserError(_('Resource capacity must be at least one.'))

    @api.constrains('company_id', 'station_id', 'platform_user_id')
    def _check_scope(self):
        for resource in self:
            if resource.station_id.company_id != resource.company_id:
                raise UserError(_('The resource and station must belong to the same company.'))
            if resource.platform_user_id and resource.company_id not in resource.platform_user_id.company_ids:
                raise UserError(_('The selected FlexSys user does not have access to this company.'))

    def _can_accept_task(self):
        self.ensure_one()
        return self.status in ('available', 'busy') and self.active_task_count < self.capacity



class FlexSysExecutionRoute(models.Model):
    _name = 'flexsys.execution.route'
    _description = 'Execution Route'
    _order = 'sequence, id'

    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company, index=True
    )
    pos_config_id = fields.Many2one(
        'pos.config', string='Branch / Point of Sale', required=True, index=True
    )
    product_tmpl_id = fields.Many2one(
        'product.template', string='Product', required=True, ondelete='cascade', index=True
    )
    station_id = fields.Many2one(
        'flexsys.execution.station', required=True, ondelete='restrict', index=True
    )
    estimated_minutes = fields.Integer(
        default=0,
        help='Specific target duration for this product route. Zero uses the station default.',
    )

    @api.constrains('company_id', 'pos_config_id', 'station_id', 'estimated_minutes')
    def _check_company_consistency(self):
        for route in self:
            if route.pos_config_id.company_id != route.company_id:
                raise UserError(_('The point of sale must belong to the selected company.'))
            if route.station_id.company_id != route.company_id:
                raise UserError(_('The station must belong to the selected company.'))
            if route.pos_config_id not in route.station_id.pos_config_ids:
                raise UserError(_('The selected station is not assigned to this point of sale.'))
            if route.estimated_minutes < 0:
                raise UserError(_('Estimated minutes cannot be negative.'))


class FlexSysExecutionTask(models.Model):
    _name = 'flexsys.execution.task'
    _description = 'Execution Task'
    _order = 'priority desc, sequence, create_date, id'

    name = fields.Char(default=lambda self: _('New'), required=True, copy=False, readonly=True)
    sequence = fields.Integer(default=10)
    order_id = fields.Many2one(
        'qtcafe.qr.order', required=True, ondelete='cascade', index=True
    )
    order_line_id = fields.Many2one(
        'qtcafe.qr.order.line', required=True, ondelete='cascade', index=True
    )
    station_id = fields.Many2one(
        'flexsys.execution.station', ondelete='restrict', index=True
    )
    assigned_resource_id = fields.Many2one(
        'flexsys.execution.resource', string='Assigned Resource', ondelete='restrict', index=True
    )
    company_id = fields.Many2one(
        related='order_id.pos_config_id.company_id', store=True, index=True, readonly=True
    )
    pos_config_id = fields.Many2one(
        related='order_id.pos_config_id', store=True, index=True, readonly=True
    )
    product_id = fields.Many2one(
        related='order_line_id.product_id', store=True, index=True, readonly=True
    )
    qty = fields.Float(related='order_line_id.qty', store=True, readonly=True)
    priority = fields.Selection(related='order_id.priority', store=True, index=True, readonly=True)
    state = fields.Selection(
        related='order_line_id.preparation_state',
        string='Execution Status',
        store=True,
        index=True,
        readonly=True,
    )
    requested_time = fields.Datetime(related='order_id.requested_time', store=True, index=True)
    started_at = fields.Datetime(related='order_line_id.started_at', store=True, readonly=True)
    ready_at = fields.Datetime(related='order_line_id.ready_at', store=True, readonly=True)
    estimated_minutes = fields.Integer(default=0, readonly=True)
    deadline_at = fields.Datetime(compute='_compute_timing', store=True, index=True)
    actual_minutes = fields.Float(compute='_compute_timing', store=True)
    is_delayed = fields.Boolean(compute='_compute_timing', store=True, index=True)
    note = fields.Char(related='order_line_id.kitchen_note', readonly=False)
    queue_position = fields.Integer(compute='_compute_queue_info')
    waiting_minutes = fields.Float(compute='_compute_queue_info')
    can_start = fields.Boolean(compute='_compute_queue_info')
    print_status = fields.Selection([
        ('not_required', 'Not Required'),
        ('pending', 'Pending'),
        ('printed', 'Printed'),
        ('failed', 'Failed'),
    ], default='not_required', required=True, copy=False, index=True)
    print_count = fields.Integer(default=0, readonly=True, copy=False)
    last_printed_at = fields.Datetime(readonly=True, copy=False)

    @api.depends('station_id', 'station_id.task_ids.state', 'station_id.task_ids.sequence',
                 'state', 'sequence', 'create_date')
    def _compute_queue_info(self):
        now = fields.Datetime.to_datetime(fields.Datetime.now())
        station_positions = {}
        for station in self.mapped('station_id'):
            station_positions[station.id] = {
                task.id: position
                for position, task in enumerate(station._ordered_waiting_tasks(), start=1)
            }
        for task in self:
            created = fields.Datetime.to_datetime(task.create_date) if task.create_date else now
            task.waiting_minutes = max((now - created).total_seconds() / 60.0, 0.0) if task.state == 'new' else 0.0
            task.queue_position = station_positions.get(task.station_id.id, {}).get(task.id, 0)
            task.can_start = bool(
                task.state == 'new'
                and task.station_id
                and task.queue_position == 1
                and task.station_id.can_start_task()
            )

    @api.depends('started_at', 'ready_at', 'estimated_minutes', 'state')
    def _compute_timing(self):
        now = fields.Datetime.now()
        for task in self:
            start = fields.Datetime.to_datetime(task.started_at) if task.started_at else False
            ready = fields.Datetime.to_datetime(task.ready_at) if task.ready_at else False
            estimate = max(task.estimated_minutes or 0, 0)
            task.deadline_at = start + timedelta(minutes=estimate) if start and estimate else False
            task.actual_minutes = (
                ((ready or fields.Datetime.to_datetime(now)) - start).total_seconds() / 60.0
                if start else 0.0
            )
            task.is_delayed = bool(
                start and estimate and task.state not in ('ready', 'cancelled', 'unavailable')
                and fields.Datetime.to_datetime(now) > start + timedelta(minutes=estimate)
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'flexsys.execution.task'
                ) or _('New')
        for vals in vals_list:
            if not vals.get('estimated_minutes'):
                station = self.env['flexsys.execution.station'].browse(vals.get('station_id'))
                vals['estimated_minutes'] = station.default_estimated_minutes if station else 0
        tasks = super().create(vals_list)
        for task in tasks:
            task.order_id._emit_event('task.created', {
                'task_id': task.id,
                'task': task.name,
                'line_id': task.order_line_id.id,
                'product_id': task.product_id.id,
                'station_id': task.station_id.id if task.station_id else False,
            })
            if task.station_id.enable_printing and task.station_id.auto_print:
                task.print_status = 'pending'
                task.order_id._emit_event('station.print_requested', {
                    'task_id': task.id,
                    'station_id': task.station_id.id,
                'resource_id': resource.id if resource else False,
                    'template': task.station_id.ticket_template,
                    'copies': task.station_id.print_copies,
                    'automatic': True,
                })
        tasks.mapped('station_id').action_rebuild_queue()
        return tasks


    def _assign_available_resource(self):
        """Assign the first available resource with free capacity."""
        self.ensure_one()
        if self.assigned_resource_id and self.assigned_resource_id._can_accept_task():
            return self.assigned_resource_id
        resource = self.station_id.resource_ids.filtered(lambda item: item._can_accept_task())[:1]
        if self.station_id.resource_ids and not resource:
            raise UserError(_('No available resource can start this task at station %s.') % self.station_id.display_name)
        if resource:
            self.assigned_resource_id = resource
        return resource

    def _release_resource_if_idle(self):
        for task in self:
            resource = task.assigned_resource_id
            if resource and not resource.task_ids.filtered(lambda item: item.state == 'preparing'):
                resource.status = 'available'

    def action_start(self):
        for task in self:
            if not task.station_id:
                raise UserError(_('Assign a station before starting the task.'))
            if not task.station_id.can_start_task():
                raise UserError(_('Station %s is paused, offline, or at full capacity.') % task.station_id.display_name)
            resource = task._assign_available_resource()
            ordered = task.station_id._ordered_waiting_tasks()
            if ordered and ordered[0] != task:
                raise UserError(_('Task %s is not first in the station queue.') % task.display_name)
            task.order_line_id.action_start_preparation()
            if resource:
                resource.status = 'busy'
            task.order_id._emit_event('station.task_started', {
                'task_id': task.id,
                'station_id': task.station_id.id,
            })
        self.mapped('station_id').action_rebuild_queue()
        return True

    def action_ready(self):
        for task in self:
            task.order_line_id.action_mark_ready()
            task.order_id._emit_event('station.task_completed', {
                'task_id': task.id,
                'station_id': task.station_id.id if task.station_id else False,
                'actual_minutes': task.actual_minutes,
                'resource_id': task.assigned_resource_id.id if task.assigned_resource_id else False,
            })
        self._release_resource_if_idle()
        self.mapped('station_id').action_rebuild_queue()
        return True

    def action_unavailable(self):
        for task in self:
            task.order_line_id.action_mark_unavailable()
        self._release_resource_if_idle()
        self.mapped('station_id').action_rebuild_queue()
        return True

    def action_reset(self):
        for task in self:
            task.order_line_id.action_reset_preparation()
        self._release_resource_if_idle()
        self.mapped('station_id').action_rebuild_queue()
        return True

    def action_print_station_ticket(self):
        """Generate the station ticket and record a traceable print event."""
        self.ensure_one()
        station = self.station_id
        if not station or not station.enable_printing:
            raise UserError(_('Station printing is not enabled for this task.'))
        self.write({
            'print_status': 'printed',
            'print_count': self.print_count + max(station.print_copies or 1, 1),
            'last_printed_at': fields.Datetime.now(),
        })
        self.order_id._emit_event('station.printed', {
            'task_id': self.id,
            'station_id': station.id,
            'template': station.ticket_template,
            'copies': max(station.print_copies or 1, 1),
            'print_count': self.print_count,
        })
        return self.env.ref('flexsys_operations.action_report_station_ticket').report_action(self)

    def action_mark_print_failed(self):
        for task in self:
            if not task.station_id or not task.station_id.enable_printing:
                continue
            task.print_status = 'failed'
            task.order_id._emit_event('station.print_failed', {
                'task_id': task.id,
                'station_id': task.station_id.id,
            })
        return True

