# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

MAX_AUTO_RETRY = 2
# How long a claim holds exclusive rights to a job before it's considered
# abandoned (agent crashed mid-print, lost network, etc.) and becomes
# claimable again by any agent. Audit finding "Printing Agent Atomic
# Claim/Lease" (HIGH) - "must be safe against retries and network
# timeouts" specifically requires this expiry, not just the atomicity.
DEFAULT_LEASE_SECONDS = 90


class KdsPrintJob(models.Model):
    _name = 'kds.print.job'
    _inherit = ['kds.access.mixin']
    _description = 'FlexSys KDS Print Job'
    _order = 'create_date desc'

    name = fields.Char(compute='_compute_name', store=True)
    order_id = fields.Many2one('kds.order', string='Order', required=True, ondelete='cascade')
    station_id = fields.Many2one('kds.station', string='Station', required=True)
    printer_id = fields.Many2one('kds.printer', string='Printer')
    user_id = fields.Many2one('res.users', default=lambda self: self.env.user)

    job_type = fields.Selection([
        ('auto', 'Auto Print'),
        ('manual', 'Manual Print'),
        ('reprint', 'Reprint'),
    ], default='auto', required=True)

    scope = fields.Selection([
        ('full_order', 'Full Order'),
        ('station_items', 'Station Items Only'),
    ], default='station_items', required=True)

    # Point 5: print delivery lifecycle. `pending` jobs are picked up by a
    # local print agent/bridge (see the /flexsys_kds/print/agent/* routes),
    # which dispatches to the physical printer, then reports back an
    # acknowledgement and finally a printed/failed result. This models a
    # realistic architecture where Odoo itself cannot talk raw ESC/POS to a
    # LAN thermal printer without either an IoT Box or an external agent.
    status = fields.Selection([
        ('pending', 'Pending'),
        ('dispatched', 'Dispatched'),
        ('printed', 'Printed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ], default='pending', required=True)

    dispatched_at = fields.Datetime()
    acknowledged_at = fields.Datetime(
        string='Acknowledged At',
        help="Set when the print agent confirms it received the job "
             "(before actual printing completes).")
    printed_at = fields.Datetime()

    # ATOMIC CLAIM/LEASE FIX (audit finding, HIGH): these three fields
    # back the claim mechanism in _claim_pending_jobs() below - see its
    # docstring for the full race-condition this replaces.
    claimed_by_agent = fields.Char(
        string='Claimed By (Agent/Device ID)', copy=False,
        help="Identifier the print agent process itself supplies when "
             "claiming this job - not the printer's own identity (a "
             "printer could in principle be served by more than one "
             "agent process/device over its lifetime).")
    claimed_at = fields.Datetime(copy=False)
    lease_expires_at = fields.Datetime(
        copy=False,
        help="Once past this time, an unresolved 'dispatched' job is "
             "treated as abandoned and becomes claimable again by any "
             "agent - handles a crashed agent or a lost network "
             "connection without needing a human to intervene.")

    copies = fields.Integer(
        default=1,
        help="Number of physical copies the print agent should produce "
             "for this job (e.g. two copies of a delivery ticket).")

    escalated = fields.Boolean(
        help="True once retries and fallback printer have both been exhausted "
             "and a manager alert event has been logged.")
    retry_count = fields.Integer(default=0)
    error = fields.Char()

    reason = fields.Selection([
        ('printer_error', 'Printer Error'),
        ('lost_ticket', 'Lost Ticket'),
        ('kitchen_request', 'Kitchen Request'),
        ('customer_change', 'Customer Change'),
        ('manager_request', 'Manager Request'),
        ('other', 'Other'),
    ], string='Reprint Reason')
    reason_note = fields.Char(string='Reason Note')

    @api.depends('order_id', 'job_type', 'station_id')
    def _compute_name(self):
        for job in self:
            job.name = "%s / %s / %s" % (
                job.order_id.name or '-', job.station_id.name or '-', job.job_type)

    # ---------------- print agent lifecycle ----------------

    @api.model
    def _claim_pending_jobs(self, printer, agent_id, limit=20, lease_seconds=DEFAULT_LEASE_SECONDS):
        """Atomically claim up to `limit` jobs for `printer`, replacing the
        old two-step "list pending, then dispatch by id" flow.

        ATOMIC CLAIM/LEASE FIX (audit finding, HIGH): the old flow fetched
        the pending list (read-only) and dispatched a specific job id in a
        *separate*, later call - between those two calls, nothing stopped
        two different agent processes (or the same agent racing a retry
        against itself after a slow/timed-out response) from both seeing
        the same job as available and both successfully calling dispatch
        on it, since action_dispatch() was an unconditional write with no
        "was this actually still pending" check baked into the same
        atomic operation. That's a real double-print risk under exactly
        the conditions the audit calls out: concurrent agents, retries,
        network timeouts.

        Fixed with a single UPDATE ... WHERE ... RETURNING statement using
        Postgres's `FOR UPDATE SKIP LOCKED` - the standard, well-established
        pattern for a job queue's "claim work atomically, without two
        workers ever grabbing the same row" requirement. Two concurrent
        calls to this method for the same printer are guaranteed by the
        database's own row-level locking to never return the same job id
        to both callers, with no explicit application-level locking code
        needed. Jobs whose previous lease has expired (an agent claimed
        them and then never followed up - crash, lost connection, etc.)
        are eligible again automatically, satisfying the "safe against
        retries and network timeouts" requirement without any separate
        cleanup/expiry cron.

        Caveat, stated plainly: `FOR UPDATE SKIP LOCKED` requires
        PostgreSQL (been available since PG 9.5, so this is a very safe
        assumption for any current Odoo install, which requires
        PostgreSQL specifically) - not tested against a live Odoo 19
        database, but this is a well-known, widely-used SQL pattern
        rather than something version-specific to Odoo itself.
        """
        self.env.cr.execute("""
            UPDATE kds_print_job
            SET status = 'dispatched',
                dispatched_at = NOW() AT TIME ZONE 'UTC',
                claimed_by_agent = %(agent_id)s,
                claimed_at = NOW() AT TIME ZONE 'UTC',
                lease_expires_at = (NOW() AT TIME ZONE 'UTC') + make_interval(secs => %(lease_seconds)s)
            WHERE id IN (
                SELECT id FROM kds_print_job
                WHERE printer_id = %(printer_id)s
                  AND (
                      status = 'pending'
                      OR (status = 'dispatched' AND (
                          lease_expires_at IS NULL OR lease_expires_at < (NOW() AT TIME ZONE 'UTC')
                      ))
                  )
                ORDER BY create_date
                LIMIT %(limit)s
                FOR UPDATE SKIP LOCKED
            )
            RETURNING id
        """, {
            'printer_id': printer.id,
            'agent_id': agent_id,
            'lease_seconds': lease_seconds,
            'limit': limit,
        })
        claimed_ids = [row[0] for row in self.env.cr.fetchall()]
        return self.browse(claimed_ids)

    def _print_payload(self):
        """Build the versioned JSON contract the print agent needs to
        generate a complete kitchen ticket without any further, unsafe
        model access of its own (audit finding "Complete Print Payload",
        HIGH - the old payload was just {id, job_type, scope, order_name},
        nowhere near enough to actually print a ticket).

        `contract_version` is bumped whenever this shape changes in a way
        that isn't purely additive, so an already-deployed print agent can
        detect and refuse to blindly trust a payload shape it wasn't
        built against, rather than silently producing a malformed ticket.
        """
        self.ensure_one()
        order = self.order_id
        pos_order = order.pos_order_id
        table_label = ''
        table = getattr(pos_order, 'table_id', False)
        if table:
            floor_name = getattr(getattr(table, 'floor_id', False), 'name', '') or ''
            table_num = getattr(table, 'table_number', '') or getattr(table, 'name', '') or ''
            table_label = f"{floor_name} / {table_num}" if floor_name and table_num else (table_num or floor_name)

        if self.scope == 'full_order':
            lines = order.line_ids.filtered(lambda l: l.state != 'cancelled')
        else:
            lines = order.line_ids.filtered(
                lambda l: l.state != 'cancelled' and l.station_id == self.station_id)

        return {
            'contract_version': 1,
            'job_id': self.id,
            'job_type': self.job_type,
            'print_scope': self.scope,
            'copies': self.copies,
            'order_number': getattr(pos_order, 'pos_reference', '') or order.name,
            'order_reference': order.name,
            'station': self.station_id.name,
            'order_type': order.order_type,
            'order_type_label': dict(order._fields['order_type'].selection).get(order.order_type),
            'table': table_label,
            'customer_name': order.customer_name or '',
            'created_at': order.created_time and order.created_time.isoformat() + 'Z',
            'items': [{
                'qty': line.qty,
                'product': line.product_name,
                'variant_info': line.variant_info or '',
                'note': line.note or '',
                'station': line.station_id.name,
                'line_change': line.line_change,
            } for line in lines],
        }

    def action_dispatch(self):
        """Kept for any caller that still wants to explicitly mark a
        specific, already-known job as dispatched (e.g. the backend UI
        manually retrying one job) - the print agent's own polling flow
        no longer uses this directly, it goes through the atomic
        _claim_pending_jobs() above instead."""
        self.write({'status': 'dispatched', 'dispatched_at': fields.Datetime.now()})

    def action_acknowledge(self):
        """Called by the print agent once the printer confirms receipt."""
        self.write({'acknowledged_at': fields.Datetime.now()})

    def action_mark_printed(self):
        self.write({'status': 'printed', 'printed_at': fields.Datetime.now()})

    def action_mark_failed(self, error_msg='Unknown error'):
        for job in self:
            job.error = error_msg
            if job.retry_count < MAX_AUTO_RETRY:
                # Retry on the same printer first.
                job.write({'status': 'pending', 'retry_count': job.retry_count + 1})
                self.env['kds.event'].log(
                    job.order_id, event_type='override', station=job.station_id,
                    note=_("Print job retry %(n)d/%(max)d after failure: %(error)s")
                         % {'n': job.retry_count, 'max': MAX_AUTO_RETRY, 'error': error_msg})
                continue

            backup = job.station_id.printer_ids.filtered('is_backup')[:1]
            if backup and job.printer_id != backup:
                self.env['kds.print.job'].create({
                    'order_id': job.order_id.id,
                    'station_id': job.station_id.id,
                    'printer_id': backup.id,
                    'job_type': job.job_type,
                    'scope': job.scope,
                    'copies': job.copies,
                    'user_id': job.user_id.id,
                })
                job.write({'status': 'failed', 'escalated': True})
                self.env['kds.event'].log(
                    job.order_id, event_type='override', station=job.station_id,
                    note=_("Fallback to backup printer '%s' after repeated failures") % backup.name)
            else:
                job.write({'status': 'failed', 'escalated': True})
                self.env['kds.event'].log(
                    job.order_id, event_type='override', station=job.station_id,
                    note=_("MANAGER ALERT: print job failed with no backup printer "
                           "available (%s)") % error_msg)

    @api.model
    def create_reprint(self, order, station, reason, reason_note=False,
                        scope='station_items', bypass_check=False):
        if not reason:
            raise ValidationError(_("A reason is required to reprint a FlexSys KDS ticket."))
        job_model = self.env['kds.print.job']
        job_model._kds_check_action('reprint', station=station, bypass=bypass_check)
        printer = station.printer_ids.filtered('is_default')[:1] or station.printer_ids[:1]
        job = job_model.create({
            'order_id': order.id,
            'station_id': station.id,
            'printer_id': printer.id,
            'job_type': 'reprint',
            'scope': scope,
            'reason': reason,
            'reason_note': reason_note,
        })
        self.env['kds.event'].log(
            order, event_type='reprint', station=station,
            note=_("Reprint requested (%(reason)s)%(note)s") % {
                'reason': reason, 'note': ': ' + reason_note if reason_note else ''}
        )
        return job
