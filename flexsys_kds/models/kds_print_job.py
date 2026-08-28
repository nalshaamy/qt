# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

MAX_AUTO_RETRY = 2

# PHASE 2 CLOSEOUT: how long a 'direct_network' job waits for the
# browser's own /print/result (or the Internal KDS equivalent ORM
# call) before _cron_timeout_stale_direct_jobs() below considers the
# attempt abandoned. Generous enough to cover a slow Local Network
# Access permission prompt (a real, user-facing pause the Direct ePOS
# Transport's own LNA flow can introduce) on top of the Adapter's own
# 15-second fetch() timeout, without being so long that a genuinely
# crashed/closed browser tab leaves its own job silently stuck in
# "Printing" for an operationally confusing length of time.
DIRECT_RESULT_TIMEOUT_SECONDS = 60


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

    # ---------------------------------------------------------------
    # PHASE 2 ("Direct Printing <-> kds.print.job Integration"):
    # kds.print.job becomes Transport-Neutral. `transport` is the ONE
    # new field distinguishing HOW a job is/was executed - deliberately
    # separate from job_type (WHAT kind of print request this is:
    # auto/manual/reprint, unchanged) and from printer_id (WHICH
    # kds.printer record, still only meaningful for the 'agent'
    # transport - printer_id was already NOT required=True at the
    # field level; the only place that ever effectively required one
    # was create_reprint()'s own explicit check below, which is
    # unchanged and still Agent-only). default='agent' so every
    # existing job (created before this field existed) is correctly
    # classified as the legacy path with zero migration/backfill
    # needed - Odoo applies a field's own default to existing rows
    # automatically when a new column is added.
    transport = fields.Selection([
        ('agent', 'Legacy Agent'),
        ('direct_network', 'Direct Network'),
        ('iot', 'Odoo IoT'),
    ], default='agent', required=True,
        help="How this job is/was actually executed - never assumed "
             "from printer_id's own presence/absence. 'Legacy Agent' "
             "is the original kds.printer/Print Agent path, unchanged. "
             "'Direct Network' is the browser-executed Epson ePOS path "
             "- printer_id is not set for these; see printer_target "
             "instead. 'Odoo IoT' is reserved, not yet implemented.")

    # A snapshot of the printer IP actually used for a 'direct_network'
    # job, captured at creation time - so the job's own history record
    # stays accurate even if the station's own Printer IP is later
    # changed or the station reconfigured to a different transport
    # entirely. Not a secret (a printer IP is deliberately not treated
    # as sensitive elsewhere in this codebase either - see the "no
    # secrets exposed" note on the Public Kiosk's own printing-config
    # bootstrap). Empty for every 'agent'/'iot' job.
    printer_target = fields.Char(
        string='Printer Target',
        help="Snapshot of the printer IP address used for a Direct "
             "Network job at the time it was created - kept even if "
             "the station's own configured IP changes later.")

    # PHASE 2 CLOSEOUT: which screen actually originated a
    # 'direct_network' job - only meaningful for that transport; left
    # unset (False) for 'agent'/'iot' jobs, which have no equivalent
    # concept today. Distinguishes an Internal KDS print (a real,
    # logged-in user - see user_id above) from a Public Kiosk print (no
    # logged-in user at all - user_id is explicitly False for these,
    # never invented).
    source = fields.Selection([
        ('internal_kds', 'Internal KDS'),
        ('public_kiosk', 'Public Kiosk'),
    ], help="Which screen created this job - only set for "
            "'direct_network' jobs.")

    # PHASE 2 CLOSEOUT: a dedicated, separate timestamp for when a job
    # reached its own final 'failed' status - deliberately NOT reusing
    # printed_at (which specifically means success) and NOT added to
    # action_mark_failed() (the Legacy Agent's own multi-attempt
    # retry/backup method, which has no single clean "this is THE
    # final failure moment" the same way a Direct attempt does, and is
    # explicitly not to be changed this round). Only
    # action_mark_direct_failed() below sets this - a Legacy Agent job
    # correctly leaves it empty.
    failed_at = fields.Datetime()

    # PHASE 2 CLOSEOUT: the machine-readable error code, kept
    # separate from `error` (the human-readable message below) so a
    # caller/report can filter or branch on the code (e.g.
    # 'RESULT_TIMEOUT') without parsing free text. Only meaningfully
    # set for 'direct_network' jobs today.
    error_code = fields.Char(
        help="Machine-readable failure code (e.g. 'RESULT_TIMEOUT', "
             "'LNA_DENIED', 'NETWORK_ERROR') - only set for Direct "
             "Network jobs.")

    # PHASE 2 CLOSEOUT: the deadline by which a browser-executed
    # 'direct_network' job must report its own result
    # (/print/result, or the Internal KDS equivalent ORM call) before
    # a periodic cron considers it abandoned (browser/tab crashed,
    # closed, or lost its connection before ever reporting back) and
    # marks it 'failed' with error_code='RESULT_TIMEOUT' - see
    # _cron_timeout_stale_direct_jobs() below. Deliberately a
    # completely separate mechanism from the Legacy Agent's own
    # lease_expires_at (a different concept: that one governs which
    # AGENT PROCESS currently holds exclusive claim to re-attempt a
    # PENDING job; this one simply detects a Direct job stuck waiting
    # for a result that will now never arrive). Only set for
    # 'direct_network' jobs.
    dispatch_deadline = fields.Datetime(
        help="Deadline for this Direct Network job's own browser-side "
             "print attempt to report a result before it is "
             "considered abandoned and automatically marked Failed.")

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

    # ---------------------------------------------------------------
    # CORRECTION ("Phase 2 - Final Corrections Before Regression
    # Test"), item 2: error_code and failed_at were accepted as
    # parameters by action_mark_direct_failed() but never actually
    # persisted, and no explicit failure timestamp existed at all
    # (write_date is not a substitute - it changes on ANY write to the
    # record, not specifically a failure). Both fields apply to any
    # transport, not only Direct Network - kept generic rather than
    # Direct-only, since a stable, non-translated error_code is a
    # genuinely useful concept for the Legacy Agent path too, even
    # though no current Agent code path sets it yet (nothing about the
    # Legacy Agent's own logic is changed this round).
    # ---------------------------------------------------------------
    error_code = fields.Char(
        string='Error Code',
        help="A stable, non-translated code identifying why this job "
             "failed (e.g. TIMEOUT, NETWORK_ERROR, LNA_DENIED) - for "
             "programmatic handling, distinct from the human-readable "
             "error message.")
    failed_at = fields.Datetime(
        string='Failed At',
        help="When this job's own status last became 'failed' - never "
             "inferred from write_date, which changes on any update to "
             "this record, not specifically a failure.")

    # CORRECTION, item 4: distinguishes which screen actually requested
    # this print, independent of user_id (which is False for a Public
    # Kiosk job - there is no logged-in internal user on that
    # standalone page, and one must never be invented/defaulted to the
    # calling context's own env.user, which would incorrectly attribute
    # a public request to whichever user happens to run the request,
    # e.g. an Administrator/Superuser context).
    source = fields.Selection([
        ('internal_kds', 'Internal KDS'),
        ('public_kiosk', 'Public Kiosk'),
    ], string='Source',
        help="Which screen actually requested this print. Independent "
             "of user_id, which is genuinely empty for a Public Kiosk "
             "job rather than attributed to any internal user.")

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
        on it, since the old dispatch path was an unconditional write with no
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
                # UI/DATA FIX ("Master Change Request", item 19,
                # "Audit Log Event Types"): 'print_retry' replaces the
                # generic 'override' here - a technical retry of the
                # SAME job on the SAME printer, distinct from a genuine
                # manager override. No change to the retry logic itself
                # - only which event_type value this specific write
                # records.
                self.env['kds.event'].log(
                    job.order_id, event_type='print_retry', station=job.station_id,
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
                # UI/DATA FIX ("Master Change Request", item 19):
                # 'printer_fallback' replaces 'override' - a genuine
                # escalation to the station's own backup printer, the
                # exact scenario the request names by example.
                self.env['kds.event'].log(
                    job.order_id, event_type='printer_fallback', station=job.station_id,
                    note=_("Fallback to backup printer '%s' after repeated failures") % backup.name)
            else:
                job.write({'status': 'failed', 'escalated': True})
                # UI/DATA FIX ("Master Change Request", item 19): also
                # 'printer_fallback' - this is the SAME fallback attempt
                # as above, just one that couldn't complete because no
                # backup printer was actually configured for this
                # station; grouping it under the same, more specific
                # event type (rather than the generic 'override') keeps
                # every "the engine tried to escalate to a backup
                # printer" event queryable together, succeeded or not -
                # the note text itself still says plainly which
                # happened.
                self.env['kds.event'].log(
                    job.order_id, event_type='printer_fallback', station=job.station_id,
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

    # ---------------------------------------------------------------
    # PHASE 2 ("Direct Printing <-> kds.print.job Integration"): the
    # Direct Network counterpart to create_reprint() above - a fully
    # SEPARATE method, not a modification of it (create_reprint() and
    # its own Agent-only printer_ids assumption are completely
    # untouched, per the explicit "do not break Legacy Agent"
    # direction). Same permission level (_kds_check_action('reprint',
    # ...)) as create_reprint() - this is the same Print button's own
    # request, just executed over a different transport, so it must
    # not be held to a different (weaker) permission bar than the path
    # it replaces.
    # ---------------------------------------------------------------
    @api.model
    def create_direct_print_job(self, order_id, station_id, job_type='manual',
                                 reason=False, reason_note=False,
                                 scope='station_items', bypass_check=False,
                                 source='internal_kds'):
        """Creates a kds.print.job for the Direct Network transport -
        never requires station.printer_ids (the Legacy Agent-only
        assumption audited and confirmed in create_reprint() above),
        only that the station itself is genuinely configured for
        Direct Network with a printer IP set. Returns the job already
        in 'dispatched' status - the browser is about to execute the
        actual print immediately after this call returns, not queue it
        for a separate agent process to pick up later, so 'pending'
        (which specifically means "waiting for an agent to claim it")
        would be inaccurate here.

        Takes order_id/station_id (plain integer ids), NOT recordsets,
        deliberately unlike create_reprint() above - this method is
        designed to be called directly over ORM/RPC from the frontend
        (Internal KDS's own onPrintClick, and the Public Kiosk
        controller's own prepare-print route below), which can only
        ever pass plain ids, never a live Python recordset object.

        `source` distinguishes which screen requested this print. For
        'public_kiosk' specifically, user_id is set to False EXPLICITLY
        in the create() call below, rather than left to fall through
        to the field's own default=lambda: self.env.user - that
        default exists for the normal, internal-user call sites
        (Internal KDS, and every other job-creating method in this
        model), and must not be allowed to silently attribute a
        public, unauthenticated kiosk request to whichever technical
        user happens to be running that request's own env context
        (e.g. sudo()'s own caller identity) - a public request
        genuinely has no requesting internal user, and must record
        that honestly rather than inventing one.

        dispatch_deadline is set here so
        _cron_timeout_stale_direct_jobs() below can later detect and
        fail a job whose own browser tab crashed/closed before ever
        reporting a result - see that method's own docstring.
        """
        order = self.env['kds.order'].browse(order_id)
        station = self.env['kds.station'].browse(station_id)
        if not order.exists() or not station.exists():
            raise ValidationError(_("Order or Station not found."))

        job_model = self.env['kds.print.job']
        job_model._kds_check_action('reprint', station=station, bypass=bypass_check)
        if station.flexsys_printing_method != 'direct_network' or not station.flexsys_printer_ip:
            # Server-side enforcement of the same Compatibility Guard
            # already applied client-side (kds_app.js/kds_kiosk.py) -
            # the server must never trust the client's own routing
            # decision alone. Same exception class/error_code as the
            # Legacy Agent's own "no printer configured" case, since
            # from an operator's own point of view it is the identical
            # situation: nothing to print to.
            raise NoPrinterConfiguredError(
                _("No printer is configured for this station."))
        now = fields.Datetime.now()
        job_vals = {
            'order_id': order.id,
            'station_id': station.id,
            'transport': 'direct_network',
            'printer_target': station.flexsys_printer_ip,
            'job_type': job_type,
            'scope': scope,
            'reason': reason,
            'reason_note': reason_note,
            'status': 'dispatched',
            'dispatched_at': now,
            'source': source,
            'dispatch_deadline': now + timedelta(seconds=DIRECT_RESULT_TIMEOUT_SECONDS),
        }
        if source == 'public_kiosk':
            job_vals['user_id'] = False
        job = job_model.create(job_vals)
        event_type = 'reprint' if job_type == 'reprint' else 'print_retry'
        # UI/DATA FIX consistency note: 'reprint' event_type is reused
        # for job_type == 'reprint' exactly like create_reprint() above
        # already does; for a plain 'manual' print (this round's own
        # actual test case - Manual Print, per the explicit scope of
        # this phase), no dedicated "manual print requested" audit
        # event_type currently exists in kds.event's own Selection -
        # rather than invent one outside this round's own scope, or
        # misuse an existing type whose own label doesn't genuinely
        # describe this action, the job record itself
        # (transport/job_type/status/timestamps) is already a
        # complete, queryable audit trail on its own via Printing ->
        # Print Jobs - no separate kds.event log call is made for the
        # plain-manual case, unlike create_reprint() above whose own
        # job_type is always 'reprint'.
        if job_type == 'reprint':
            self.env['kds.event'].log(
                order, event_type='reprint', station=station,
                note=_("Reprint requested (%(reason)s)%(note)s") % {
                    'reason': reason or '', 'note': ': ' + reason_note if reason_note else ''}
            )
        # Returns a plain dict, NOT the job recordset itself -
        # deliberately, unlike create_reprint() above, since this
        # method is called directly over ORM/RPC and a live recordset
        # object is not RPC/JSON-serializable. job_id is the one piece
        # of information either caller (Internal KDS's own
        # onPrintClick, the Public Kiosk's own prepare-print route)
        # needs to report the eventual browser-side print result back
        # against the SAME job.
        return {'job_id': job.id}

    def action_mark_direct_failed(self, error_code=False, error_message='Unknown error'):
        """Direct Network's own failure handler - deliberately NOT a
        reuse of action_mark_failed() above, whose own retry/backup-
        printer escalation logic is entirely Agent-specific (retrying
        "the same printer" or escalating to a station's own configured
        kds.printer backup has no equivalent meaning for a
        browser-executed Direct Network attempt - a failed direct
        attempt is simply failed; the operator can press Print again
        themselves, which creates a fresh job, exactly like any other
        manual action in this system). No automatic retry, no fallback
        printer creation - just an honest, final, timestamped failure
        record. No separate kds.event log call either, for the same
        reason noted in create_direct_print_job() above - no existing
        event_type genuinely describes "a direct print attempt
        failed", and the job record itself (status='failed', error,
        error_code, failed_at, printer_target) is already the
        complete, queryable record of what happened, exactly where
        Printing -> Print Jobs already looks.

        CORRECTION ("Phase 2 - Final Corrections Before Regression
        Test"), item 2: error_code and failed_at (fields.now()) are
        now genuinely persisted - they were previously accepted as
        parameters here but silently discarded, and no explicit
        failure timestamp existed at all (write_date is not a
        substitute - it changes on any write, not specifically this
        one).
        """
        self.write({
            'status': 'failed',
            'error': error_message,
            'error_code': error_code or False,
            'failed_at': fields.Datetime.now(),
        })

    # ---------------------------------------------------------------
    # PHASE 2 CLOSEOUT: the ONE place idempotency/conflict handling
    # for a Direct Network job's own terminal result lives - both
    # callers (Internal KDS's own onPrintClick, the Public Kiosk's own
    # /print/result route) call this instead of action_mark_printed()/
    # action_mark_direct_failed() directly, so the exact same rules
    # apply identically regardless of which screen is reporting.
    # ---------------------------------------------------------------
    def report_direct_print_result(self, successful, error_code=False, error_message=False):
        """Records a Direct Network job's own browser-side print
        result, with idempotency and conflict handling:
          - a REPEATED report of the SAME outcome the job already has
            (e.g. two 'successful' reports in a row, perhaps from a
            retried network call on the reporting side itself) is a
            silent no-op - not an error.
          - a CONFLICTING report (e.g. the job is already 'printed',
            and a 'failed' report now arrives) is explicitly rejected
            - never silently overwrites an already-terminal outcome
              with a different one.
          - only a genuinely 'dispatched' (still-awaiting-result) job
            actually transitions, via the existing
            action_mark_printed()/action_mark_direct_failed() methods
            above - unchanged, reused as-is.
        """
        self.ensure_one()
        if self.transport != 'direct_network':
            raise ValidationError(_("This job is not a Direct Network print job."))

        if self.status == 'printed':
            if successful:
                return  # Idempotent: already printed, reported printed again.
            raise ValidationError(_("This job is already marked Printed - cannot report Failed now."))

        if self.status == 'failed':
            if not successful:
                return  # Idempotent: already failed, reported failed again.
            raise ValidationError(_("This job is already marked Failed - cannot report Printed now."))

        if self.status != 'dispatched':
            raise ValidationError(_("This job is not currently awaiting a Direct Network print result."))

        if successful:
            self.action_mark_printed()
        else:
            self.action_mark_direct_failed(error_code=error_code, error_message=error_message)

    @api.model
    def _cron_timeout_stale_direct_jobs(self):
        """PHASE 2 CLOSEOUT: finds every 'direct_network' job still
        'dispatched' past its own dispatch_deadline - the browser tab
        that was executing its own Direct ePOS attempt crashed, was
        closed, or lost its connection before ever reporting a result
        via report_direct_print_result() above - and marks each one
        Failed with a stable, distinct error_code, so it does not
        appear to still be actively printing forever.

        No automatic retry, no backup printer - identical, honest
        failure handling to any other Direct Network failure. Does
        not touch 'agent'/'iot' jobs at all - the Legacy Agent's own
        lease_expires_at mechanism (a different concept entirely -
        which AGENT PROCESS currently holds a claim to retry a
        PENDING job) is completely separate and unaffected.
        """
        now = fields.Datetime.now()
        stale_jobs = self.search([
            ('transport', '=', 'direct_network'),
            ('status', '=', 'dispatched'),
            ('dispatch_deadline', '!=', False),
            ('dispatch_deadline', '<', now),
        ])
        for job in stale_jobs:
            job.action_mark_direct_failed(
                error_code='RESULT_TIMEOUT',
                error_message=_("No print result was received before the deadline - "
                                "the browser tab may have crashed, closed, or lost its "
                                "connection."))
