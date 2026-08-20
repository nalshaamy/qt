# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

MAX_AUTO_RETRY = 2


class NoPrinterConfiguredError(UserError):
    """UI/DATA FIX ("Printing Cleanup & Job History - Final Request"),
    item 3: raised instead of ever creating a kds.print.job with an
    empty/false printer_id - "قبل إنشاء أي kds.print.job... فقط إذا
    وُجد Printer صالح، يتم إنشاء Print Job... لا تسجل العملية كـFailed
    Print Job؛ لأن الطباعة لم تبدأ أصلًا."

    A plain subclass of UserError (not a wholly new exception
    hierarchy) so every existing `except UserError` in this codebase
    still correctly catches it without modification - the one addition
    is `error_code`, a stable, non-translated string a caller (a
    controller, in this case) can check to distinguish this specific,
    expected condition from any other UserError, without ever having to
    pattern-match the translated message text itself.
    """
    error_code = 'no_printer'

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

    # UI/DATA FIX ("Printing UI & Job History - Final Cleanup Before
    # Testing"), items 3-6: the raw `job_type` above (auto/manual/
    # reprint) is a technical distinction this project's own printing
    # engine needs internally (auto-print-on-Send vs an explicit manual
    # reprint action) and is left completely unchanged - but it does
    # NOT, on its own, tell a person looking at the job history "was
    # this the FIRST time this station's ticket printed, or a repeat" -
    # an order auto-printed once, then manually reprinted three times,
    # sorted by the list's own default create_date desc, showed three
    # 'Reprint' rows at the top with the original 'Auto Print' row
    # scrolled out of immediate view below them - exactly the reported
    # symptom ("نفس الطلب يظهر بعدة سجلات Reprint... ولا يظهر سجل Print
    # الأصلي"). The data itself was never wrong; the history simply had
    # no field that stated the real print sequence plainly.
    #
    # print_number: computed once per (order_id, station_id) pair,
    # counting this job's own position among every kds.print.job that
    # shares that same order+station, ordered by create_date - the
    # very first print (job_type auto OR manual, whichever happens
    # first for a given order+station - there is no requirement that
    # the first print specifically be 'auto') is always 1; every
    # subsequent one for that same order+station, regardless of its own
    # job_type, is 2, 3, 4... This is exactly "كل طلب إعادة طباعة يدوي
    # ينشئ سجلًا جديدًا: Print # = 2, 3, 4...".
    print_number = fields.Integer(
        string='Print #', compute='_compute_print_number', store=True)
    # display_job_type: the simplified Print/Reprint label item 7's own
    # column list asks for - print_number == 1 is 'Print', anything
    # else is 'Reprint'. Deliberately a SEPARATE field from job_type,
    # not a relabeling of it - job_type keeps its own, different
    # meaning (how this specific job was triggered: automatically on
    # Send, or manually) untouched for every other part of this module
    # that already depends on it; display_job_type answers a different
    # question (where does this job fall in the print sequence for its
    # own order+station) that nothing in this codebase computed before
    # this fix.
    display_job_type = fields.Selection([
        ('print', 'Print'),
        ('reprint', 'Reprint'),
    ], compute='_compute_print_number', store=True)

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

    @api.depends('order_id', 'station_id')
    def _compute_print_number(self):
        """UI/DATA FIX ("Printing UI & Job History"): counts each job's
        own position among every kds.print.job sharing the same
        (order_id, station_id) pair, ordered by database id (more
        reliable than create_date, which can collide for two jobs
        created within the same second/transaction). Only THIS job's
        own position is computed and stored here - an earlier sibling's
        own already-correct, already-stored print_number is never
        recomputed just because a later one was created (its own
        position in the sequence never changes), matching Odoo's own
        standard compute/depends semantics: only records whose own
        `order_id`/`station_id` genuinely changed are recomputed at
        all.
        """
        for job in self:
            if not job.order_id or not job.station_id or not job.id:
                job.print_number = 1
                job.display_job_type = 'print'
                continue
            position = self.env['kds.print.job'].sudo().search_count([
                ('order_id', '=', job.order_id.id),
                ('station_id', '=', job.station_id.id),
                ('id', '<=', job.id),
            ])
            job.print_number = position or 1
            job.display_job_type = 'print' if position <= 1 else 'reprint'

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

        REAL BUG FIX, confirmed live on Odoo.sh ("job.status remains
        pending" / "claimed_by_agent remains unset after re-claim"):
        this raw SQL UPDATE was missing the two things any raw-SQL
        write alongside the ORM always needs. (1) Flush first: any
        pending ORM-buffered write on this table (e.g. a job just
        created via .create() earlier in the same transaction, not yet
        physically written to the table) was invisible to this SQL
        query, since the ORM only writes to the actual table lazily, at
        flush time - not immediately on every .create()/.write() call.
        (2) Invalidate after: the ORM's own in-memory cache for these
        exact fields has no way to know this raw SQL UPDATE happened at
        all - a caller re-reading job.status via the ORM straight after
        this method returns got back the STALE pre-claim cached value,
        not what the database was actually just updated to. Both are
        now handled explicitly rather than relying on implicit ORM
        behavior.
        """
        self.env.flush_all()
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
        claimed = self.browse(claimed_ids)
        # See this method's own docstring, point (2): the raw SQL UPDATE
        # above is invisible to the ORM's cache until explicitly
        # invalidated - without this, job.status/claimed_by_agent/etc.
        # read via the ORM anywhere else in this same request (including
        # through a *different* recordset reference to the same ids,
        # since Odoo's cache is keyed by (model, id, field) per
        # environment, not per recordset object) would still return the
        # stale pre-claim values.
        claimed.invalidate_recordset()
        return claimed

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
        # UI/DATA FIX ("Printing Cleanup & Job History - Final
        # Request"), item 3: confirmed live - every Print/Reprint tap
        # could create a kds.print.job even with no configured/eligible
        # printer for the station, silently persisting a permanently
        # unexecutable job with printer_id=False. Fixed by resolving
        # the printer FIRST and refusing to create anything at all if
        # none is found - "Do NOT create kds.print.job. Do NOT increase
        # Print # / Reprint count." Deliberately a UserError raised
        # here, not a job created with status='failed' - "لا تسجل
        # العملية كـFailed Print Job؛ لأن الطباعة لم تبدأ أصلًا" (a
        # 'failed' status is reserved for a job that genuinely reached
        # the print agent and failed there - item 4's own, unrelated,
        # already-correct case - not for a print that was never even
        # attempted because there was nothing to send it to).
        if not printer:
            raise NoPrinterConfiguredError(
                _("No printer is configured for this station."))
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
