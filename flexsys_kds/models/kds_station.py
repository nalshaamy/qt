# -*- coding: utf-8 -*-
import secrets

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class KdsStation(models.Model):
    _name = 'kds.station'
    _description = 'FlexSys KDS Station'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    code = fields.Char(required=True, help="Short technical code, e.g. KITCHEN")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    company_id = fields.Many2one(
        'res.company', string='Branch / Company',
        default=lambda self: self.env.company, required=True,
        help="FlexSys KDS uses res.company as the Branch entity for MVP scope."
    )

    operating_mode = fields.Selection([
        ('kds_only', 'KDS Only'),
        ('printer_only', 'Printer Only'),
        ('kds_printer', 'KDS + Printer'),
    ], default='kds_printer', required=True)

    pos_config_ids = fields.Many2many(
        'pos.config', string='POS Configs',
        help="POS points of sale this station receives orders from. Empty = all."
    )

    is_expeditor = fields.Boolean(
        string='Is Expeditor / Packing Station',
        help="Marks this station as the final assembly/packing stage. "
             "An order is only Ready for pickup once all required stations are done."
    )

    auto_accept_orders = fields.Boolean(default=False)
    auto_print = fields.Boolean(default=False)

    target_prep_time = fields.Integer(
        string='Target Preparation Time (min)', default=10,
        help="Used by the SLA engine to compute Normal / Warning / Late."
    )
    warning_threshold_pct = fields.Integer(default=80, string='Warning Threshold (%)')
    late_threshold_pct = fields.Integer(default=100, string='Late Threshold (%)')

    # SECURITY/DATA-INTEGRITY FIX (audit finding "SLA Validation", HIGH):
    # nothing previously stopped target_prep_time=0 (every order would
    # instantly be Late), negative values, or a Warning threshold set
    # above Late (making the "Warning" stage unreachable) - all of which
    # would silently corrupt the SLA engine's output rather than erroring
    # visibly at configuration time.
    @api.constrains('target_prep_time', 'warning_threshold_pct', 'late_threshold_pct')
    def _check_sla_config(self):
        for station in self:
            if station.target_prep_time <= 0:
                raise ValidationError(_(
                    "Station '%s': Target Preparation Time must be greater than 0 minutes."
                ) % station.name)
            if station.warning_threshold_pct <= 0:
                raise ValidationError(_(
                    "Station '%s': Warning Threshold must be greater than 0%%."
                ) % station.name)
            if station.late_threshold_pct <= station.warning_threshold_pct:
                raise ValidationError(_(
                    "Station '%(station)s': Late Threshold (%(late)s%%) must be greater "
                    "than the Warning Threshold (%(warning)s%%)."
                ) % {
                    'station': station.name,
                    'late': station.late_threshold_pct,
                    'warning': station.warning_threshold_pct,
                })

    printer_ids = fields.One2many('kds.printer', 'station_id', string='Printers')
    printer_count = fields.Integer(compute='_compute_counts')
    user_ids = fields.Many2many(
        'res.users', 'kds_station_user_rel', 'station_id', 'user_id',
        string='Assigned Users',
        help="Users linked to this station only see orders/lines routed to it."
    )

    order_line_ids = fields.One2many('kds.order.line', 'station_id', string='Order Lines')
    active_order_count = fields.Integer(compute='_compute_counts')
    late_order_count = fields.Integer(compute='_compute_counts')
    avg_prep_time = fields.Float(compute='_compute_counts', string='Avg. Prep Time (min)')

    status = fields.Selection([
        ('online', 'Online'),
        ('offline', 'Offline'),
    ], default='online', compute='_compute_status', store=True)

    description = fields.Text()

    # ---------------------------------------------------------------
    # Public, unauthenticated kiosk access. A device visiting
    # /flexsyskds/public/<code>/<kiosk_token> gets the KDS screen for
    # this station with NO Odoo login at all - the token itself is the
    # credential (possession of the URL = authorization), which is why
    # it must be treated like a password: admin-only visibility, shown
    # once as a copyable URL, and regenerable to instantly invalidate
    # any leaked link. This is deliberately a *separate*, narrower
    # surface from the authenticated /flexsyskds/<code> kiosk redirect
    # (which still requires a normal Odoo login) - the public API it
    # talks to only allows Accept/Start/Ready on this station's own
    # lines, nothing else (no cancel, no reprint, no other stations).
    # ---------------------------------------------------------------
    kiosk_token = fields.Char(
        string='Public Kiosk Token', copy=False, groups='flexsys_kds.group_kds_administrator',
        help="Secret embedded in this station's public kiosk URL. Anyone "
             "with the full URL can view and operate this station's "
             "screen without logging into Odoo. Regenerate immediately "
             "invalidates the old URL if you suspect it leaked."
    )
    kiosk_url = fields.Char(
        string='Public Kiosk URL', compute='_compute_kiosk_url',
        groups='flexsys_kds.group_kds_administrator',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault('kiosk_token', secrets.token_urlsafe(24))
        return super().create(vals_list)

    def action_regenerate_kiosk_token(self):
        for station in self:
            station.kiosk_token = secrets.token_urlsafe(24)

    def _compute_kiosk_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        for station in self:
            if station.kiosk_token and station.code:
                station.kiosk_url = "%s/flexsyskds/public/%s/%s" % (
                    base_url, station.code, station.kiosk_token)
            else:
                station.kiosk_url = False

    # AUDIT FIX ("Station KPI Refresh", MEDIUM): this was declared as
    # depending only on `printer_ids`, which is only actually true for
    # printer_count - active_order_count/late_order_count/avg_prep_time
    # all depend on kds.order.line data instead, so Odoo's ORM had no
    # correct signal for when to invalidate/recompute them, only
    # recomputing when a printer was added/removed rather than when an
    # order actually arrived, changed state, or went Late. Declaring the
    # real field paths (order_line_ids.state/.sla_status/.prep_duration)
    # fixes the invalidation trigger correctly - the method body still
    # uses bounded search() calls internally (not station.order_line_ids
    # directly, which is the *entire unbounded historical relation* with
    # no domain), so this doesn't turn into scanning a station's complete
    # history on every KDS screen refresh - only the current active-line
    # set and the last 200 completed lines, exactly as before.
    @api.depends('printer_ids', 'order_line_ids.state', 'order_line_ids.sla_status',
                  'order_line_ids.prep_duration')
    def _compute_counts(self):
        for station in self:
            lines = self.env['kds.order.line'].search([
                ('station_id', '=', station.id),
                ('state', 'not in', ('completed', 'cancelled')),
            ])
            station.printer_count = len(station.printer_ids)
            station.active_order_count = len(lines.mapped('order_id'))
            station.late_order_count = len(lines.filtered(lambda l: l.sla_status == 'late').mapped('order_id'))
            done_lines = self.env['kds.order.line'].search([
                ('station_id', '=', station.id),
                ('state', '=', 'ready'),
                ('prep_duration', '>', 0),
            ], limit=200, order='id desc')
            station.avg_prep_time = (
                sum(done_lines.mapped('prep_duration')) / len(done_lines) if done_lines else 0.0
            )

    @api.depends('printer_ids.status', 'active')
    def _compute_status(self):
        for station in self:
            station.status = 'online' if station.active else 'offline'

    _sql_constraints = [
        ('code_company_uniq', 'unique(code, company_id)', 'Station code must be unique per branch.'),
    ]

    def action_view_printers(self):
        """Stat-button target: open this station's printers only (not
        every printer in the system). Uses type="object" + a Python
        method returning the action dict, rather than a stat button
        pointed straight at an %(xmlid)d action - the latter needs
        type="action", and mixing that up with type="object" produces a
        confusing "<id> is not a valid action" error at install time."""
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('flexsys_kds.action_kds_printer')
        action['domain'] = [('station_id', '=', self.id)]
        action['context'] = {'default_station_id': self.id}
        return action
