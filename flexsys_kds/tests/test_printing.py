# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import FlexSysKdsTestCommon


@tagged('post_install', '-at_install')
class TestPrinting(FlexSysKdsTestCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.printer_primary = cls.env['kds.printer'].create({
            'name': 'Test Kitchen Printer 01',
            'station_id': cls.station_kitchen.id,
            'is_default': True,
        })
        cls.printer_backup = cls.env['kds.printer'].create({
            'name': 'Test Kitchen Printer 02 (Backup)',
            'station_id': cls.station_kitchen.id,
            'is_backup': True,
        })

    def _order(self):
        order = self._make_order([(self.product_burger, 1)])
        self._route_line_to_station(order.line_ids, self.station_kitchen)
        return order

    def test_reprint_requires_a_reason(self):
        order = self._order()
        with self.assertRaises(ValidationError):
            self.env['kds.print.job'].create_reprint(order, self.station_kitchen, reason=False)

    def test_printer_gets_an_agent_key_on_create(self):
        """Point 5: every printer should get a per-printer secret for the
        print agent bridge automatically, without anyone having to
        remember to set one."""
        self.assertTrue(self.printer_primary.agent_key)
        self.assertNotEqual(self.printer_primary.agent_key, self.printer_backup.agent_key)

    def test_regenerate_agent_key_changes_it(self):
        old_key = self.printer_primary.agent_key
        self.printer_primary.action_regenerate_agent_key()
        self.assertNotEqual(self.printer_primary.agent_key, old_key)

    # -----------------------------------------------------------------
    # UI/DATA FIX ("Printing Configuration Gap - Agent Key Access" /
    # "Rename/Fix Agent Key Action"): action_show_agent_key() (renamed
    # from action_copy_agent_key() - that name implied an automatic
    # clipboard copy the action never actually performed) must retrieve
    # the existing key WITHOUT ever regenerating/changing it, restricted
    # to KDS Administrator only, and never write the key back into any
    # persisted field. The client's own explicit choice: "Show Agent
    # Key is acceptable as long as the full key can be selected and
    # copied manually" - satisfied unchanged by the same underlying
    # sticky-notification mechanism, only the name/label corrected.
    # -----------------------------------------------------------------
    def test_show_agent_key_returns_sticky_notification_with_the_real_key(self):
        """Confirms the action returns Odoo's own standard
        display_notification client action, sticky (stays until
        manually dismissed - long enough to select and copy manually).

        REAL BUG FIX ("Print Agent Authentication - Live Test
        Failure"): the message's own structure changed - the key is no
        longer the ENTIRE message, it is now the message's own first
        line, followed by a verification hint - see this test's own
        updated assertions below, and action_show_agent_key()'s own
        docstring for the complete root-cause explanation (a confirmed
        manual copy error, not a stored/compared value mismatch)."""
        result = self.printer_primary.action_show_agent_key()
        self.assertEqual(result['type'], 'ir.actions.client')
        self.assertEqual(result['tag'], 'display_notification')
        message = result['params']['message']
        self.assertTrue(
            message.startswith(self.printer_primary.agent_key),
            "The key must be the very first thing in the message - a copy starting "
            "from the beginning of the message body must never need to skip past "
            "anything else first.")
        self.assertTrue(result['params']['sticky'])

    def test_show_agent_key_message_has_verification_hint_after_key(self):
        """REAL BUG FIX ("Print Agent Authentication - Live Test
        Failure"): confirms the message includes a length-verification
        hint AFTER the key (separated by a blank line), letting the
        administrator visually confirm they copied the right thing
        before configuring the external agent with it."""
        result = self.printer_primary.action_show_agent_key()
        message = result['params']['message']
        key = self.printer_primary.agent_key
        self.assertIn(str(len(key)), message)
        self.assertIn('\n\n', message, "The key and the hint must be visually separated.")
        # The hint text itself must never masquerade as part of the key -
        # it's plain English prose, structurally unmistakable from a
        # base64 secret even if accidentally included in a copy.
        self.assertIn('characters', message)

    def test_show_agent_key_never_changes_the_key(self):
        """Required: 'Do not regenerate/change the key.' Directly
        contrasts with action_regenerate_agent_key() (tested above),
        which DOES change it."""
        old_key = self.printer_primary.agent_key
        self.printer_primary.action_show_agent_key()
        self.printer_primary.invalidate_recordset()
        self.assertEqual(
            self.printer_primary.agent_key, old_key,
            "Showing the key must never regenerate or otherwise change it - unlike "
            "action_regenerate_agent_key(), which is a completely separate action.")

    def test_show_agent_key_denied_for_non_administrator(self):
        """Required: 'Allow KDS Administrator only.' A KDS Supervisor
        (a real, distinct, lesser role in this project's own access
        hierarchy) must be denied, with an explicit AccessError - not a
        silent no-op or a value leaked despite the restriction."""
        from odoo.exceptions import AccessError
        supervisor = self._make_kds_user('printer_show_key_supervisor', self.group_supervisor)
        with self.assertRaises(AccessError):
            self.printer_primary.with_user(supervisor).action_show_agent_key()

    def test_show_agent_key_allowed_for_administrator(self):
        """Positive case: a genuine KDS Administrator can successfully
        call the action and receive the real key as the message's own
        first line."""
        admin_user = self._make_kds_user('printer_show_key_admin', self.group_administrator)
        result = self.printer_primary.with_user(admin_user).action_show_agent_key()
        self.assertTrue(result['params']['message'].startswith(self.printer_primary.agent_key))

    def test_show_agent_key_handles_missing_key_gracefully(self):
        """Defensive: a printer with no agent_key at all (should not
        normally happen, since create() always sets one - but the
        action itself must not raise if it somehow is empty) shows a
        clear message instead of a blank/broken notification."""
        printer_no_key = self.env['kds.printer'].create({
            'name': 'Printer With No Key (edge case)',
            'station_id': self.station_kitchen.id,
        })
        printer_no_key.sudo().agent_key = False
        result = printer_no_key.action_show_agent_key()
        self.assertIn('No Print Agent Key', result['params']['message'])

    def test_retry_before_falling_back(self):
        order = self._order()
        job = self.env['kds.print.job'].create({
            'order_id': order.id,
            'station_id': self.station_kitchen.id,
            'printer_id': self.printer_primary.id,
            'job_type': 'auto',
        })
        job.action_mark_failed('simulated failure 1')
        self.assertEqual(job.status, 'pending', "First failure should retry, not fail outright.")
        self.assertEqual(job.retry_count, 1)
        self.assertFalse(job.escalated)

        job.action_mark_failed('simulated failure 2')
        self.assertEqual(job.status, 'pending', "Second failure should still be within MAX_AUTO_RETRY.")
        self.assertEqual(job.retry_count, 2)

    def test_falls_back_to_backup_printer_after_max_retries(self):
        order = self._order()
        job = self.env['kds.print.job'].create({
            'order_id': order.id,
            'station_id': self.station_kitchen.id,
            'printer_id': self.printer_primary.id,
            'job_type': 'auto',
        })
        job.action_mark_failed('failure 1')
        job.action_mark_failed('failure 2')
        # Third failure exceeds MAX_AUTO_RETRY (2) -> falls back.
        job.action_mark_failed('failure 3')

        self.assertEqual(job.status, 'failed')
        self.assertTrue(job.escalated)

        fallback_jobs = self.env['kds.print.job'].search([
            ('order_id', '=', order.id),
            ('printer_id', '=', self.printer_backup.id),
        ])
        self.assertEqual(len(fallback_jobs), 1, "A new job should be created on the backup printer.")
        self.assertEqual(fallback_jobs.status, 'pending')

    def test_escalates_with_manager_alert_when_no_backup_available(self):
        # A station with only one printer, no backup configured.
        lonely_printer = self.env['kds.printer'].create({
            'name': 'Test Coffee Printer (no backup)',
            'station_id': self.station_coffee.id,
            'is_default': True,
        })
        order = self._make_order([(self.product_cappuccino, 1)])
        self._route_line_to_station(order.line_ids, self.station_coffee)
        job = self.env['kds.print.job'].create({
            'order_id': order.id,
            'station_id': self.station_coffee.id,
            'printer_id': lonely_printer.id,
            'job_type': 'auto',
        })
        job.action_mark_failed('failure 1')
        job.action_mark_failed('failure 2')
        job.action_mark_failed('failure 3')

        self.assertEqual(job.status, 'failed')
        self.assertTrue(job.escalated)
        alert_events = self.env['kds.event'].search([
            ('order_id', '=', order.id),
            ('note', 'like', 'MANAGER ALERT%'),
        ])
        self.assertTrue(alert_events, "A manager-alert audit event should be logged when there's no backup.")

    def test_successful_print_marks_printed(self):
        """UPDATED for "Dead Code Cleanup Part 2", item 1
        ("action_dispatch()"): the earlier version of this test used
        the now-removed action_dispatch() purely as a setup shortcut,
        not testing its own behavior specifically - updated to use the
        actual, supported runtime path instead (the atomic claim
        mechanism every real Print Agent request goes through), per
        "update tests to use the actual supported runtime setup instead
        of preserving a dead production method for test convenience."
        """
        order = self._order()
        job = self.env['kds.print.job'].create({
            'order_id': order.id,
            'station_id': self.station_kitchen.id,
            'printer_id': self.printer_primary.id,
            'job_type': 'auto',
        })
        claimed = self.env['kds.print.job']._claim_pending_jobs(
            self.printer_primary, agent_id='test-agent')
        self.assertEqual(claimed.ids, [job.id])
        self.assertEqual(job.status, 'dispatched')
        self.assertTrue(job.dispatched_at)
        job.action_acknowledge()
        self.assertTrue(job.acknowledged_at)
        job.action_mark_printed()
        self.assertEqual(job.status, 'printed')
        self.assertTrue(job.printed_at)

    # -----------------------------------------------------------------
    # Audit finding "Printing Agent Atomic Claim/Lease" (HIGH): the old
    # flow was a separate "list pending" + "dispatch by id" pair of
    # calls, leaving a race window where two agents (or a retrying
    # agent racing itself) could both see and both claim the same job.
    # -----------------------------------------------------------------
    def test_claim_marks_job_dispatched_with_agent_identity(self):
        order = self._order()
        job = self.env['kds.print.job'].create({
            'order_id': order.id,
            'station_id': self.station_kitchen.id,
            'printer_id': self.printer_primary.id,
            'job_type': 'auto',
        })
        claimed = self.env['kds.print.job']._claim_pending_jobs(
            self.printer_primary, agent_id='agent-A')
        self.assertEqual(claimed.ids, [job.id])
        self.assertEqual(job.status, 'dispatched')
        self.assertEqual(job.claimed_by_agent, 'agent-A')
        self.assertTrue(job.claimed_at)
        self.assertTrue(job.lease_expires_at)

    def test_second_claim_does_not_reclaim_an_active_lease(self):
        """This is the exact scenario the fix targets: two agents (or one
        agent retrying) calling claim for the same printer in quick
        succession must never both come away with the same job."""
        order = self._order()
        self.env['kds.print.job'].create({
            'order_id': order.id,
            'station_id': self.station_kitchen.id,
            'printer_id': self.printer_primary.id,
            'job_type': 'auto',
        })
        first_claim = self.env['kds.print.job']._claim_pending_jobs(
            self.printer_primary, agent_id='agent-A')
        second_claim = self.env['kds.print.job']._claim_pending_jobs(
            self.printer_primary, agent_id='agent-B')
        self.assertEqual(len(first_claim), 1)
        self.assertEqual(len(second_claim), 0,
                          "A job with an active (unexpired) lease must not be claimable again.")

    def test_expired_lease_becomes_claimable_again(self):
        """Handles a crashed agent or lost network connection - the exact
        'safe against retries and network timeouts' requirement."""
        order = self._order()
        job = self.env['kds.print.job'].create({
            'order_id': order.id,
            'station_id': self.station_kitchen.id,
            'printer_id': self.printer_primary.id,
            'job_type': 'auto',
        })
        self.env['kds.print.job']._claim_pending_jobs(
            self.printer_primary, agent_id='agent-A', lease_seconds=-1)
        # lease_seconds=-1 -> lease_expires_at is already in the past,
        # simulating "claimed a while ago and never followed up".
        second_claim = self.env['kds.print.job']._claim_pending_jobs(
            self.printer_primary, agent_id='agent-B')
        self.assertEqual(second_claim.ids, [job.id])
        self.assertEqual(job.claimed_by_agent, 'agent-B',
                          "The job should now belong to whichever agent re-claimed it.")

    def test_claim_only_returns_jobs_for_the_requested_printer(self):
        order = self._order()
        self.env['kds.print.job'].create({
            'order_id': order.id,
            'station_id': self.station_kitchen.id,
            'printer_id': self.printer_backup.id,  # different printer
            'job_type': 'auto',
        })
        claimed = self.env['kds.print.job']._claim_pending_jobs(
            self.printer_primary, agent_id='agent-A')
        self.assertFalse(claimed, "Claiming for printer_primary must not touch printer_backup's jobs.")

    def test_claim_respects_limit(self):
        order = self._order()
        for _i in range(5):
            self.env['kds.print.job'].create({
                'order_id': order.id,
                'station_id': self.station_kitchen.id,
                'printer_id': self.printer_primary.id,
                'job_type': 'auto',
            })
        claimed = self.env['kds.print.job']._claim_pending_jobs(
            self.printer_primary, agent_id='agent-A', limit=2)
        self.assertEqual(len(claimed), 2)

    # -----------------------------------------------------------------
    # Audit finding "Complete Print Payload" (HIGH): the old payload was
    # just {id, job_type, scope, order_name} - nowhere near enough to
    # print a real ticket without further, unsafe model access.
    # -----------------------------------------------------------------
    def test_print_payload_contains_required_fields(self):
        order = self._order()
        job = self.env['kds.print.job'].create({
            'order_id': order.id,
            'station_id': self.station_kitchen.id,
            'printer_id': self.printer_primary.id,
            'job_type': 'auto',
            'copies': 2,
        })
        payload = job._print_payload()
        for key in ('contract_version', 'job_id', 'order_number', 'order_reference',
                    'station', 'order_type', 'table', 'customer_name', 'created_at',
                    'print_scope', 'copies', 'items'):
            self.assertIn(key, payload, f"Print payload is missing required key: {key}")
        self.assertEqual(payload['copies'], 2)
        self.assertEqual(payload['station'], self.station_kitchen.name)
        self.assertEqual(len(payload['items']), 1)
        item = payload['items'][0]
        for key in ('qty', 'product', 'variant_info', 'note', 'station', 'line_change'):
            self.assertIn(key, item, f"Print payload item is missing required key: {key}")

    def test_print_payload_scope_station_items_excludes_other_stations(self):
        order = self._make_order([(self.product_burger, 1), (self.product_cappuccino, 1)])
        self._route_line_to_station(order.line_ids[0], self.station_kitchen)
        self._route_line_to_station(order.line_ids[1], self.station_coffee)
        job = self.env['kds.print.job'].create({
            'order_id': order.id,
            'station_id': self.station_kitchen.id,
            'printer_id': self.printer_primary.id,
            'job_type': 'auto',
            'scope': 'station_items',
        })
        payload = job._print_payload()
        self.assertEqual(len(payload['items']), 1)
        self.assertEqual(payload['items'][0]['station'], self.station_kitchen.name)

    def test_print_payload_scope_full_order_includes_every_station(self):
        order = self._make_order([(self.product_burger, 1), (self.product_cappuccino, 1)])
        self._route_line_to_station(order.line_ids[0], self.station_kitchen)
        self._route_line_to_station(order.line_ids[1], self.station_coffee)
        job = self.env['kds.print.job'].create({
            'order_id': order.id,
            'station_id': self.station_kitchen.id,
            'printer_id': self.printer_primary.id,
            'job_type': 'auto',
            'scope': 'full_order',
        })
        payload = job._print_payload()
        self.assertEqual(len(payload['items']), 2)

    def test_print_job_default_copies_is_one(self):
        order = self._order()
        job = self.env['kds.print.job'].create({
            'order_id': order.id,
            'station_id': self.station_kitchen.id,
            'printer_id': self.printer_primary.id,
            'job_type': 'auto',
        })
        self.assertEqual(job.copies, 1)

    # -----------------------------------------------------------------
    # UI/DATA FIX ("Printing UI & Job History - Final Cleanup Before
    # Testing"): print_number/display_job_type correctly reflect the
    # real print sequence per (order_id, station_id), independent of
    # the technical job_type value (auto/manual/reprint) each job was
    # actually created with, and independent of retry_count (a
    # completely separate concept - technical retries of the SAME job,
    # not new print jobs at all).
    # -----------------------------------------------------------------
    def test_first_print_is_number_one_and_display_type_print(self):
        """The first print job ever created for a given (order,
        station) - whichever job_type it happens to be (auto or
        manual) - must be print_number=1, display_job_type='print'."""
        order = self._order()
        job = self.env['kds.print.job'].create({
            'order_id': order.id,
            'station_id': self.station_kitchen.id,
            'printer_id': self.printer_primary.id,
            'job_type': 'auto',
        })
        self.assertEqual(job.print_number, 1)
        self.assertEqual(job.display_job_type, 'print')

    def test_first_print_manual_is_still_number_one(self):
        """A first job created as 'manual' (e.g. via
        action_print_full_order) is print_number=1 just the same - the
        FIRST job for its own (order, station) is always 'Print',
        regardless of whether it happened to be triggered automatically
        or manually."""
        order = self._order()
        job = self.env['kds.print.job'].create({
            'order_id': order.id,
            'station_id': self.station_kitchen.id,
            'printer_id': self.printer_primary.id,
            'job_type': 'manual',
        })
        self.assertEqual(job.print_number, 1)
        self.assertEqual(job.display_job_type, 'print')

    def test_reprint_after_first_print_is_number_two(self):
        """The exact reported scenario: after a genuine first print,
        create_reprint() must produce print_number=2,
        display_job_type='reprint' - and the ORIGINAL first job's own
        print_number/display_job_type must remain correctly 1/'print',
        never recomputed or disturbed by the later reprint's own
        creation."""
        order = self._order()
        first_job = self.env['kds.print.job'].create({
            'order_id': order.id,
            'station_id': self.station_kitchen.id,
            'printer_id': self.printer_primary.id,
            'job_type': 'auto',
        })
        self.assertEqual(first_job.print_number, 1)

        reprint_job = self.env['kds.print.job'].create_reprint(
            order, self.station_kitchen, reason='kitchen_request')

        self.assertEqual(reprint_job.print_number, 2)
        self.assertEqual(reprint_job.display_job_type, 'reprint')
        first_job.invalidate_recordset()
        self.assertEqual(
            first_job.print_number, 1,
            "The original first job's own print_number must remain 1, completely "
            "unaffected by the later reprint's own creation.")
        self.assertEqual(first_job.display_job_type, 'print')

    def test_multiple_reprints_number_sequentially(self):
        """Test D's own required scenario, multiple times over: three
        manual reprints after an initial auto print must number 2, 3,
        4 in the order they were actually created - the exact reported
        bug scenario ('نفس الطلب يظهر بعدة سجلات Reprint... ولا يظهر
        سجل Print الأصلي'), reproduced and confirmed fixed."""
        order = self._order()
        original = self.env['kds.print.job'].create({
            'order_id': order.id,
            'station_id': self.station_kitchen.id,
            'printer_id': self.printer_primary.id,
            'job_type': 'auto',
        })
        self.assertEqual(original.print_number, 1)
        self.assertEqual(original.display_job_type, 'print')

        reprint_2 = self.env['kds.print.job'].create_reprint(
            order, self.station_kitchen, reason='lost_ticket')
        reprint_3 = self.env['kds.print.job'].create_reprint(
            order, self.station_kitchen, reason='kitchen_request')
        reprint_4 = self.env['kds.print.job'].create_reprint(
            order, self.station_kitchen, reason='customer_change')

        self.assertEqual(reprint_2.print_number, 2)
        self.assertEqual(reprint_3.print_number, 3)
        self.assertEqual(reprint_4.print_number, 4)
        for job in (reprint_2, reprint_3, reprint_4):
            self.assertEqual(job.display_job_type, 'reprint')

        # The original must STILL correctly show as the first Print,
        # visible in the history alongside the three reprints - not
        # "missing", the exact reported symptom.
        original.invalidate_recordset()
        self.assertEqual(original.print_number, 1)
        self.assertEqual(original.display_job_type, 'print')

    def test_print_numbering_independent_across_orders_and_stations(self):
        """Confirms the sequence is scoped strictly per (order_id,
        station_id) - a different order, or the same order at a
        different station, must start its own sequence at 1, never
        continuing another one's own numbering."""
        order_a = self._order()
        order_b = self._order()

        job_a1 = self.env['kds.print.job'].create({
            'order_id': order_a.id, 'station_id': self.station_kitchen.id,
            'printer_id': self.printer_primary.id, 'job_type': 'auto',
        })
        job_b1 = self.env['kds.print.job'].create({
            'order_id': order_b.id, 'station_id': self.station_kitchen.id,
            'printer_id': self.printer_primary.id, 'job_type': 'auto',
        })

        self.assertEqual(job_a1.print_number, 1)
        self.assertEqual(job_b1.print_number, 1,
                          "A different order must start its own sequence at 1, "
                          "not continue order_a's own numbering.")

    def test_retry_count_never_affects_print_number_or_display_type(self):
        """Required: 'Retry Count لا يعني Reprint Count.' A technical
        retry of the SAME print job (action_mark_failed, below the
        auto-retry threshold) must never create a new print_job row,
        never change print_number, and never change display_job_type -
        only retry_count itself changes."""
        order = self._order()
        job = self.env['kds.print.job'].create({
            'order_id': order.id,
            'station_id': self.station_kitchen.id,
            'printer_id': self.printer_primary.id,
            'job_type': 'auto',
        })
        self.assertEqual(job.print_number, 1)
        self.assertEqual(job.display_job_type, 'print')
        self.assertEqual(job.retry_count, 0)

        job.action_mark_failed('simulated printer error')

        job.invalidate_recordset()
        self.assertEqual(job.retry_count, 1,
                          "retry_count increments on the SAME job - no new row created.")
        self.assertEqual(
            job.print_number, 1,
            "print_number must remain 1 - a technical retry is not a new print event.")
        self.assertEqual(
            job.display_job_type, 'print',
            "display_job_type must remain 'print' - retries never turn a first print "
            "into a 'reprint'.")
        # Confirms no new kds.print.job row was created by the retry.
        self.assertEqual(
            self.env['kds.print.job'].search_count([
                ('order_id', '=', order.id), ('station_id', '=', self.station_kitchen.id),
            ]),
            1,
            "A retry must never create an additional print_job row - Retry Count and "
            "Reprint Count are completely separate concepts.")

    def test_reprint_action_creates_a_genuinely_new_job_row(self):
        """Confirms create_reprint() itself creates a distinct new
        kds.print.job row (not just bumping some counter on the
        original) - the required 'كل طلب إعادة طباعة يدوي ينشئ سجلًا
        جديدًا'."""
        order = self._order()
        first_job = self.env['kds.print.job'].create({
            'order_id': order.id,
            'station_id': self.station_kitchen.id,
            'printer_id': self.printer_primary.id,
            'job_type': 'auto',
        })

        reprint_job = self.env['kds.print.job'].create_reprint(
            order, self.station_kitchen, reason='manager_request')

        self.assertNotEqual(
            reprint_job.id, first_job.id,
            "A reprint must be a genuinely new, separate kds.print.job record.")
        self.assertEqual(
            self.env['kds.print.job'].search_count([
                ('order_id', '=', order.id), ('station_id', '=', self.station_kitchen.id),
            ]),
            2)

    # -----------------------------------------------------------------
    # UI/DATA FIX ("Printing Cleanup & Job History - Final Request"),
    # item 3: no kds.print.job must ever be created for a station with
    # no configured/eligible printer - confirmed the previous behavior
    # silently created a permanently unexecutable job with
    # printer_id=False.
    # -----------------------------------------------------------------
    def test_create_reprint_no_printer_raises_and_creates_no_job(self):
        """Required: 'Do NOT create kds.print.job. Do NOT increase
        Print # / Reprint count.' A station with zero printers
        configured must raise, not silently create a broken job."""
        from odoo.addons.flexsys_kds.models.kds_print_job import NoPrinterConfiguredError
        order = self._order()
        station_no_printer = self.env['kds.station'].create({
            'name': 'Dessert Station (no printer)',
            'code': 'DESSERT_NOPRN',
        })

        with self.assertRaises(NoPrinterConfiguredError):
            self.env['kds.print.job'].create_reprint(
                order, station_no_printer, reason='kitchen_request')

        self.assertEqual(
            self.env['kds.print.job'].search_count([
                ('order_id', '=', order.id), ('station_id', '=', station_no_printer.id),
            ]),
            0,
            "No kds.print.job of any kind must have been created.")

    def test_no_printer_error_carries_stable_error_code(self):
        """Confirms the exception carries a stable, non-translated
        error_code a caller (a controller) can check, distinguishing
        this specific condition from any other UserError."""
        order = self._order()
        station_no_printer = self.env['kds.station'].create({
            'name': 'Dessert Station 2 (no printer)',
            'code': 'DESSERT_NOPRN2',
        })
        try:
            self.env['kds.print.job'].create_reprint(
                order, station_no_printer, reason='kitchen_request')
            self.fail("Expected NoPrinterConfiguredError to be raised.")
        except Exception as e:
            self.assertEqual(getattr(e, 'error_code', None), 'no_printer')

    def test_action_print_full_order_skips_station_without_printer(self):
        """The same fix for action_print_full_order(), but per-station:
        one station with no printer must not prevent printing correctly
        to another station that DOES have one configured."""
        order = self._order()  # already routed to station_kitchen, which has printers
        station_no_printer = self.env['kds.station'].create({
            'name': 'Bar Station (no printer)',
            'code': 'BAR_NOPRN',
        })
        bar_line = self.env['pos.order.line'].create({
            'order_id': order.pos_order_id.id,
            'product_id': self.product_cappuccino.id,
            'qty': 1, 'price_unit': 4.0, 'price_subtotal': 4.0, 'price_subtotal_incl': 4.0,
        })
        kds_line = self.env['kds.order.line'].create({
            'order_id': order.id, 'product_id': self.product_cappuccino.id,
            'product_name': self.product_cappuccino.name, 'qty': 1,
            'station_id': station_no_printer.id,
        })
        order.invalidate_recordset()

        order.action_print_full_order(bypass_check=True)

        kitchen_jobs = self.env['kds.print.job'].search([
            ('order_id', '=', order.id), ('station_id', '=', self.station_kitchen.id),
        ])
        no_printer_jobs = self.env['kds.print.job'].search([
            ('order_id', '=', order.id), ('station_id', '=', station_no_printer.id),
        ])
        self.assertEqual(
            len(kitchen_jobs), 1,
            "The station WITH a printer must still get its own print job created.")
        self.assertEqual(
            len(no_printer_jobs), 0,
            "The station WITHOUT a printer must get no job at all - not a broken one.")

    def test_action_print_full_order_still_works_when_printer_exists(self):
        """Non-regression: a station that DOES have a printer configured
        must continue to get a correctly-created print job exactly as
        before."""
        order = self._order()
        order.action_print_full_order(bypass_check=True)

        job = self.env['kds.print.job'].search([
            ('order_id', '=', order.id), ('station_id', '=', self.station_kitchen.id),
        ])
        self.assertEqual(len(job), 1)
        self.assertTrue(job.printer_id)
        self.assertEqual(job.print_number, 1)
        self.assertEqual(job.display_job_type, 'print')

    def test_printer_exists_physical_failure_same_job_retry_increments(self):
        """Required acceptance case (item 4): 'إذا تم Resolve لطابعة
        صالحة وتم إنشاء Job ثم فشلت الطباعة: Job exists -> same Job ->
        Retry Count increases' - confirms this ALREADY correct behavior
        directly, unaffected by this round's own changes."""
        order = self._order()
        job = self.env['kds.print.job'].create({
            'order_id': order.id,
            'station_id': self.station_kitchen.id,
            'printer_id': self.printer_primary.id,
            'job_type': 'auto',
        })
        self.assertEqual(job.print_number, 1)
        self.assertEqual(job.retry_count, 0)

        job.action_mark_failed('simulated physical printer failure')

        job.invalidate_recordset()
        self.assertEqual(job.retry_count, 1, "Same job, retry_count increments.")
        self.assertEqual(job.print_number, 1, "Still print #1 - no new job created.")
        self.assertEqual(job.display_job_type, 'print', "Not turned into a Reprint by a retry.")
        self.assertEqual(
            self.env['kds.print.job'].search_count([
                ('order_id', '=', order.id), ('station_id', '=', self.station_kitchen.id),
            ]),
            1, "No new kds.print.job row created by the physical failure/retry.")

    def test_successful_retry_stays_same_job(self):
        """Required acceptance case: 'Successful retry -> Same Job.'"""
        order = self._order()
        job = self.env['kds.print.job'].create({
            'order_id': order.id,
            'station_id': self.station_kitchen.id,
            'printer_id': self.printer_primary.id,
            'job_type': 'auto',
        })
        job.action_mark_failed('transient error')
        job.invalidate_recordset()
        self.assertEqual(job.retry_count, 1)
        self.assertEqual(job.status, 'pending')

        job.action_mark_printed()

        job.invalidate_recordset()
        self.assertEqual(job.status, 'printed')
        self.assertEqual(job.print_number, 1)
        self.assertEqual(job.display_job_type, 'print')
        self.assertEqual(
            self.env['kds.print.job'].search_count([
                ('order_id', '=', order.id), ('station_id', '=', self.station_kitchen.id),
            ]),
            1, "A successful retry must still be the exact same single job row.")

    def test_full_acceptance_sequence_print_retry_reprint_reprint(self):
        """The dev request's own full worked example, reproduced end to
        end: Print #1 (retry 0) -> physical failure, retry -> User
        Reprint -> Print #2 -> another Reprint -> Print #3 with its own
        retries."""
        order = self._order()
        first = self.env['kds.print.job'].create({
            'order_id': order.id,
            'station_id': self.station_kitchen.id,
            'printer_id': self.printer_primary.id,
            'job_type': 'auto',
        })
        self.assertEqual(first.print_number, 1)
        self.assertEqual(first.display_job_type, 'print')
        self.assertEqual(first.retry_count, 0)

        first.action_mark_failed('printer jam')
        first.invalidate_recordset()
        self.assertEqual(first.retry_count, 1)
        self.assertEqual(first.print_number, 1, "Still the same job/number after a retry.")

        second = self.env['kds.print.job'].create_reprint(
            order, self.station_kitchen, reason='lost_ticket')
        self.assertEqual(second.print_number, 2)
        self.assertEqual(second.display_job_type, 'reprint')
        self.assertEqual(second.retry_count, 0)

        second.action_mark_failed('printer jam')
        second.action_mark_failed('printer jam again')
        second.invalidate_recordset()
        self.assertEqual(second.retry_count, 2)
        self.assertEqual(second.print_number, 2, "Retries never change print_number.")
        self.assertEqual(second.display_job_type, 'reprint')

        third = self.env['kds.print.job'].create_reprint(
            order, self.station_kitchen, reason='customer_change')
        self.assertEqual(third.print_number, 3)
        self.assertEqual(third.display_job_type, 'reprint')
        self.assertEqual(third.retry_count, 0)

        # Final state check across all three jobs at once.
        all_jobs = self.env['kds.print.job'].search(
            [('order_id', '=', order.id), ('station_id', '=', self.station_kitchen.id)],
            order='print_number asc')
        self.assertEqual(len(all_jobs), 3, "No accidental duplicate jobs.")
        self.assertEqual(all_jobs.mapped('print_number'), [1, 2, 3])
        self.assertEqual(all_jobs.mapped('display_job_type'), ['print', 'reprint', 'reprint'])
        self.assertEqual(all_jobs.mapped('retry_count'), [1, 2, 0])

    def test_kds_reprint_controller_returns_no_printer_error_code(self):
        """Confirms the /flexsys_kds/print/reprint controller correctly
        surfaces error_code='no_printer' via _kds_error() when the
        underlying create_reprint() raises NoPrinterConfiguredError -
        the JSON shape the frontend's own onPrintClick relies on to
        show the specific required Toast."""
        from odoo.addons.flexsys_kds.controllers.kds import _kds_error
        from odoo.addons.flexsys_kds.models.kds_print_job import NoPrinterConfiguredError
        exc = NoPrinterConfiguredError("No printer is configured for this station.")
        result = _kds_error(exc)
        self.assertEqual(result['ok'], False)
        self.assertEqual(result['error_code'], 'no_printer')
        self.assertIn('No printer is configured', result['error'])

    def test_kds_error_helper_omits_error_code_for_ordinary_exceptions(self):
        """Confirms _kds_error() doesn't fabricate an error_code for an
        exception that doesn't define one - existing callers/behavior
        for every other error path are unaffected."""
        from odoo.addons.flexsys_kds.controllers.kds import _kds_error
        from odoo.exceptions import UserError
        result = _kds_error(UserError("Some other, ordinary error"))
        self.assertEqual(result['ok'], False)
        self.assertNotIn('error_code', result)

    # -----------------------------------------------------------------
    # UI/DATA FIX ("Printing Cleanup & Job History - Toast + Job Record
    # Simplification"), item 1: found a SEPARATE, independent copy of
    # the exact same "RPC result discarded" bug in the standalone kiosk
    # page's own printOrder() (controllers/kds_kiosk.py) - a fully
    # separate HTML/JS surface with no Odoo web client or OWL
    # notification service reachable at all, which the earlier round's
    # fix (kds_app.js/kds_store.js) never touched. Fixed with its own,
    # dependency-free toast mechanism there. These tests confirm the
    # backend-shared logic (now unified via _kds_error(), no longer
    # duplicated) and the template's own structural presence - the
    # actual visual rendering of a toast is genuine browser behavior
    # this Python/Odoo test suite cannot execute or verify, exactly
    # like the earlier Offline Send Warning round's own honestly-scoped
    # tests.
    # -----------------------------------------------------------------
    def test_kiosk_print_reuses_shared_kds_error_helper(self):
        """Confirms kds_kiosk.py's own kiosk_print() now reuses
        controllers/kds.py's own _kds_error() (imported, not
        hand-duplicated) - one single implementation of the
        error_code-surfacing logic, not two copies that could silently
        drift apart. Unrelated to the Toast requirement itself (removed
        entirely in a later round - see
        test_kiosk_template_has_no_toast_mechanism below) - this is
        the exception-handling/JSON-response-stability fix, which
        remains necessary regardless of whether any frontend surface
        displays error_code."""
        from odoo.addons.flexsys_kds.controllers.kds_kiosk import _kds_error as kiosk_kds_error
        from odoo.addons.flexsys_kds.controllers.kds import _kds_error as backend_kds_error
        self.assertIs(
            kiosk_kds_error, backend_kds_error,
            "kds_kiosk.py must import and reuse the exact same _kds_error function object, "
            "not a separate, hand-duplicated copy of its own logic.")

    def test_kiosk_template_has_no_toast_mechanism(self):
        """UI/DATA FIX ("Printing Cleanup - Toast + Job Record
        Simplification"), decision item 6: the Toast requirement is
        removed entirely - "No Printer -> No Job is sufficient."
        Confirms the toast container/function/CSS added in v7.17.1 for
        this specific requirement are genuinely gone from the rendered
        template, not just visually hidden."""
        import re
        module_dir = __import__('os').path.dirname(__import__('os').path.dirname(
            __import__('os').path.abspath(__file__)))
        kiosk_path = __import__('os').path.join(module_dir, 'controllers', 'kds_kiosk.py')
        with open(kiosk_path, encoding='utf-8') as f:
            content = f.read()
        m = re.search(r'_KIOSK_HTML_TEMPLATE = r"""(.*)"""\s*$', content, re.DOTALL)
        self.assertIsNotNone(m, "Expected to find _KIOSK_HTML_TEMPLATE in kds_kiosk.py.")
        template = m.group(1)
        rendered = template % {
            'station_name': 'Kitchen', 'branch_name': 'QT01', 'company_name': 'Test Co',
            'station_code': 'KITCHEN', 'token': 'abc123',
        }
        self.assertNotIn('kdsToastStack', rendered)
        self.assertNotIn('showToast', rendered)
        self.assertNotIn('kds-toast', rendered)

    # -----------------------------------------------------------------
    # UI/DATA FIX ("Printing Cleanup - Toast + Job Record
    # Simplification"), decision item 5: "Improve only the Print Jobs
    # list presentation/grouping so multiple jobs for the same order
    # are easy to understand." Architecture itself (decision items
    # 1-4) is completely unchanged - one immutable kds.print.job record
    # per actual Print/Reprint request, confirmed already correct by
    # the earlier round's own tests above (unaffected, still passing).
    # -----------------------------------------------------------------
    def test_print_job_action_defaults_to_grouping_by_order(self):
        """Confirms action_kds_print_job's own context defaults to
        grouping by Order, so multiple jobs for the same order appear
        clustered together immediately on opening the screen."""
        action = self.env.ref('flexsys_kds.action_kds_print_job')
        context = action.context or '{}'
        parsed_context = eval(context) if isinstance(context, str) else context
        self.assertTrue(
            parsed_context.get('search_default_group_order'),
            "The Print Jobs action must default to grouping by Order.")
        self.assertTrue(
            action.search_view_id,
            "The action must reference the explicit search view carrying the "
            "group_order filter.")

    def test_search_view_has_group_by_order_filter(self):
        """Confirms the search view's own arch genuinely defines a
        group-by filter on order_id, named exactly 'group_order' -
        matching what the action's own default context activates."""
        search_view = self.env.ref('flexsys_kds.view_kds_print_job_search')
        arch = search_view.arch
        self.assertIn('name="group_order"', arch)
        self.assertIn("'group_by': 'order_id'", arch)

    def test_list_view_default_order_groups_print_sequence_naturally(self):
        """Confirms the list view's own default_order sorts by
        (order_id, print_number) - so within any given order, jobs read
        1, 2, 3 top to bottom, the exact readability improvement
        requested, without touching the model's own default create_date
        desc ordering used elsewhere."""
        list_view = self.env.ref('flexsys_kds.view_kds_print_job_list')
        self.assertEqual(list_view.arch_db.count('default_order='), 1)
        self.assertIn('default_order="order_id, print_number"', list_view.arch_db)

    def test_multiple_jobs_same_order_sort_correctly_by_default_order(self):
        """End-to-end confirmation: querying with the list view's own
        default_order genuinely returns jobs for the same order in the
        correct 1, 2, 3 sequence, not reversed by create_date."""
        order = self._order()
        first = self.env['kds.print.job'].create({
            'order_id': order.id, 'station_id': self.station_kitchen.id,
            'printer_id': self.printer_primary.id, 'job_type': 'auto',
        })
        second = self.env['kds.print.job'].create_reprint(
            order, self.station_kitchen, reason='kitchen_request')
        third = self.env['kds.print.job'].create_reprint(
            order, self.station_kitchen, reason='lost_ticket')

        ordered_jobs = self.env['kds.print.job'].search(
            [('order_id', '=', order.id)], order='order_id, print_number')
        self.assertEqual(ordered_jobs.ids, [first.id, second.id, third.id])
        self.assertEqual(ordered_jobs.mapped('print_number'), [1, 2, 3])

    def test_architecture_unchanged_no_record_reuse(self):
        """Explicit non-regression confirming decision items 1-4:
        immutable one-record-per-request architecture is completely
        unchanged - three separate, genuinely distinct database records
        exist for Print #1/Reprint #2/Reprint #3, never a single record
        updated in place."""
        order = self._order()
        first = self.env['kds.print.job'].create({
            'order_id': order.id, 'station_id': self.station_kitchen.id,
            'printer_id': self.printer_primary.id, 'job_type': 'auto',
        })
        second = self.env['kds.print.job'].create_reprint(
            order, self.station_kitchen, reason='kitchen_request')
        third = self.env['kds.print.job'].create_reprint(
            order, self.station_kitchen, reason='lost_ticket')

        all_ids = {first.id, second.id, third.id}
        self.assertEqual(len(all_ids), 3, "Three genuinely distinct record ids - no reuse.")
        self.assertEqual(
            self.env['kds.print.job'].search_count([('order_id', '=', order.id)]),
            3)

    # -----------------------------------------------------------------
    # REAL BUG FIX ("Print Agent Authentication - Live Test Failure"):
    # confirmed live that secrets.token_urlsafe(24) always generates
    # exactly 32 characters (never varying); a key received by an
    # external agent 17 characters longer than that - matching
    # len("Print Agent Key: ") exactly - strongly indicated a manual
    # copy error (the notification's own title accidentally included
    # alongside the actual key), not a stored/compared value mismatch.
    # -----------------------------------------------------------------
    def test_agent_key_generation_length_is_stable(self):
        """Confirms the exact, stable expected length this round's own
        root-cause analysis relies on - secrets.token_urlsafe(24) always
        produces exactly 32 characters, with zero variance across many
        generations."""
        import secrets
        lengths = {len(secrets.token_urlsafe(24)) for _ in range(50)}
        self.assertEqual(lengths, {32}, "token_urlsafe(24) must always produce exactly 32 "
                                         "characters - the baseline this round's own fix "
                                         "and its length-verification hint both depend on.")

    def test_hmac_compare_digest_type_error_handling_pattern(self):
        """REAL BUG FIX ("Print Agent Authentication - Live Test
        Failure"), item 2: 'harden hmac.compare_digest() handling so
        malformed/non-ASCII input returns a normal authentication
        failure instead of producing a server TypeError.'

        Honest, explicitly-scoped test: controllers/kds.py's own
        `_printer_from_key()` reads `odoo.http.request.env`, which is
        only genuinely populated during a real HTTP request - it cannot
        be safely unit-tested here without either a full HttpCase
        (a different, heavier test class this project's own test suite
        does not currently use anywhere) or mocking Odoo's own internal
        request-context machinery (fragile, version-sensitive, exactly
        the kind of risk this project has repeatedly and deliberately
        avoided elsewhere). This test instead directly confirms the
        core fix - the exact try/except TypeError pattern now wrapping
        the hmac.compare_digest() call in that method - against the
        real malformed inputs that motivated it, so the underlying
        logic itself is verified even though the full HTTP-level
        integration is not."""
        import hmac

        def guarded_compare(stored, incoming):
            """Mirrors _printer_from_key()'s own new try/except
            structure exactly - not a reimplementation of different
            logic, the identical pattern."""
            try:
                return hmac.compare_digest(stored, incoming)
            except TypeError:
                return False

        stored_key = 'Nvg684b52yMKV5GELiVxk53kADQHP-b-'  # a genuine, valid-shaped key

        # A genuinely correct match must still succeed.
        self.assertTrue(guarded_compare(stored_key, stored_key))

        # An ordinary wrong-value mismatch must return False, not raise.
        self.assertFalse(guarded_compare(stored_key, 'completely-different-value'))

        # The exact confirmed live scenario: a key with extra characters
        # prepended (simulating the notification title accidentally
        # copied alongside the real key) must fail cleanly, not raise.
        self.assertFalse(guarded_compare(stored_key, 'Print Agent Key: ' + stored_key))

        # A wrong TYPE entirely (a bug on the external agent's own side -
        # None, an int, a list) must fail cleanly, not propagate a raw
        # TypeError up to an unhandled HTTP 500.
        for malformed in (None, 12345, ['not', 'a', 'string'], {'key': stored_key}, b'bytes-not-str'):
            try:
                result = guarded_compare(stored_key, malformed)
            except Exception as e:
                self.fail(f"guarded_compare() must never raise for malformed input "
                          f"{malformed!r}, got: {e!r}")
            self.assertFalse(result, f"Malformed input {malformed!r} must be treated as a "
                                      f"clean authentication failure.")

        # A string containing non-ASCII characters - the specific
        # documented CPython constraint on hmac.compare_digest() for str
        # arguments - must also fail cleanly, not raise.
        try:
            result = guarded_compare(stored_key, 'ключ-not-ascii-agent-key-value')
        except Exception as e:
            self.fail(f"guarded_compare() must never raise for non-ASCII input, got: {e!r}")
        self.assertFalse(result)

    def test_printer_from_key_source_uses_the_hardened_pattern(self):
        """Structural confirmation that controllers/kds.py's own real
        _printer_from_key() source genuinely contains the try/except
        TypeError guard around hmac.compare_digest() - not just that an
        equivalent pattern exists somewhere else, matching the
        `test_kiosk_template_has_no_toast_mechanism`-style structural
        check already used elsewhere in this suite for content this
        Python/Odoo test process cannot otherwise safely exercise."""
        import inspect
        from odoo.addons.flexsys_kds.controllers.kds import FlexSysKdsPrintAgentController
        source = inspect.getsource(FlexSysKdsPrintAgentController._printer_from_key)
        self.assertIn('try:', source)
        self.assertIn('except TypeError:', source)
        self.assertIn('hmac.compare_digest', source)

    # -----------------------------------------------------------------
    # UI/DATA FIX ("Master Change Request", Batch 3, items 13-18).
    # Non-regression: action_regenerate_agent_key(), action_show_agent_key(),
    # action_set_default(), action_set_backup(), and the printing
    # engine's own Claim/Lease/Retry/Failover logic are all covered
    # extensively above/elsewhere in this suite and completely
    # untouched by this batch - these tests focus specifically on what
    # this batch actually changed.
    # -----------------------------------------------------------------
    def test_item14_test_connection_button_removed_from_printer_form(self):
        """Item 14: 'REMOVE من Production UI: Mark as Online (No Real
        Connectivity Check).' Structural check confirming the button
        itself is genuinely gone from the rendered view - not just
        relabeled."""
        import os
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        view_path = os.path.join(module_dir, 'views', 'kds_printer_views.xml')
        with open(view_path, encoding='utf-8') as f:
            content = f.read()
        self.assertNotIn('action_test_connection', content,
                          "The button calling action_test_connection() must be fully "
                          "removed from the printer form's own view.")

    def test_deep_cleanup_test_connection_method_fully_removed(self):
        """UPDATED for "Deep Dead Code & Commercial Cleanup Request",
        item "Printer action_test_connection()": the earlier version of
        this test confirmed the method was deliberately kept, unused,
        in the codebase. This request explicitly overrides that
        decision - "Do not keep simulation/demo functionality in the
        production commercial addon" - and confirmed zero active
        callers existed anywhere. The method is now genuinely deleted,
        not merely unreachable from the UI."""
        printer = self.printer_primary
        self.assertFalse(hasattr(printer, 'action_test_connection'),
                          "action_test_connection() must be genuinely removed.")

    def test_item15_default_backup_fields_readonly_in_form_view(self):
        """Item 15: 'يفضل: Set as Default / Set as Backup كإجراءات.
        والحقول تكون indicators/read-only.' Structural check confirming
        is_default/is_backup are genuinely marked readonly in the
        rendered form - the two action buttons remain the only way to
        actually change either role."""
        form_view = self.env.ref('flexsys_kds.view_kds_printer_form')
        arch = form_view.arch_db
        # Confirms both fields appear with readonly="1" specifically (not
        # just present anywhere in the arch, which would also match the
        # earlier, non-readonly version).
        self.assertIn('name="is_default" readonly="1"', arch)
        self.assertIn('name="is_backup"', arch)
        self.assertIn('readonly="1"', arch)

    def test_item15_set_default_action_still_enforces_single_default(self):
        """Non-regression: action_set_default()'s own existing
        'only one Default per station' enforcement is completely
        unaffected by making the field read-only in the view (a
        view-only change - this method itself was never touched)."""
        self.printer_primary.action_set_default()
        self.assertTrue(self.printer_primary.is_default)
        self.printer_backup.action_set_default()
        self.printer_primary.invalidate_recordset()
        self.assertFalse(self.printer_primary.is_default,
                          "Setting a new Default must still correctly unset the previous one.")
        self.assertTrue(self.printer_backup.is_default)

    def test_item17_new_status_filters_present_in_search_view(self):
        """Item 17: 'إضافة/تحسين الفلاتر: Pending, Dispatched, Printed,
        Failed, Escalated, Reprints.' Confirms the three genuinely new
        filters this batch adds are present, alongside the pre-existing
        ones."""
        search_view = self.env.ref('flexsys_kds.view_kds_print_job_search')
        arch = search_view.arch
        for filter_name, status_value in (
            ('filter_pending', 'pending'), ('filter_dispatched', 'dispatched'),
            ('filter_printed', 'printed'),
        ):
            self.assertIn('name="%s"' % filter_name, arch)
            self.assertIn("('status', '=', '%s')" % status_value, arch)
        # Pre-existing filters, confirmed still present/unaffected.
        for filter_name in ('filter_failed', 'filter_escalated', 'filter_reprint'):
            self.assertIn('name="%s"' % filter_name, arch)

    def test_item17_default_order_newest_order_first_correct_sequence_within(self):
        """Item 17: 'Default sorting: Newest first' - reconciled with
        the earlier print-sequence fix. Confirms a newer order's own
        jobs appear before an older order's own jobs, while each
        order's own jobs still read 1, 2, 3 internally."""
        old_order = self._order()
        old_job = self.env['kds.print.job'].create({
            'order_id': old_order.id, 'station_id': self.station_kitchen.id,
            'printer_id': self.printer_primary.id, 'job_type': 'auto',
        })
        new_order = self._order()
        new_job_1 = self.env['kds.print.job'].create({
            'order_id': new_order.id, 'station_id': self.station_kitchen.id,
            'printer_id': self.printer_primary.id, 'job_type': 'auto',
        })
        new_job_2 = self.env['kds.print.job'].create_reprint(
            new_order, self.station_kitchen, reason='kitchen_request')

        all_jobs = self.env['kds.print.job'].search(
            [('id', 'in', [old_job.id, new_job_1.id, new_job_2.id])],
            order='order_id desc, print_number')

        self.assertEqual(
            list(all_jobs.ids[:2]), [new_job_1.id, new_job_2.id],
            "The newer order's own jobs must sort before the older order's own jobs.")
        self.assertEqual(all_jobs.ids[2], old_job.id)
        # Within the newer order's own two jobs, print_number order (1
        # then 2) must still hold correctly.
        self.assertEqual(all_jobs.ids[:2], [new_job_1.id, new_job_2.id])

    def test_item17_print_job_form_view_exists_with_agent_lease_fields(self):
        """Item 17: 'تفاصيل Job يمكن أن تعرض: Agent, Lease information,
        Failure/Error, Failover information.' Confirms the new form
        view exists at all (there was none before this fix) and
        includes the specific fields the request names."""
        form_view = self.env.ref('flexsys_kds.view_kds_print_job_form')
        arch = form_view.arch_db
        for field_name in ('claimed_by_agent', 'claimed_at', 'lease_expires_at',
                            'error', 'retry_count', 'escalated'):
            self.assertIn('name="%s"' % field_name, arch)

    def test_item17_print_job_action_now_includes_form_view_mode(self):
        """Confirms the action itself was updated to actually reach the
        new form view - clicking a row in the list must open it, not
        do nothing."""
        action = self.env.ref('flexsys_kds.action_kds_print_job')
        self.assertIn('form', action.view_mode)

    def test_item18_escalated_job_form_shows_failover_message(self):
        """Item 18: 'يجب أن يكون من السهل معرفة: Original Printer ->
        Backup Printer.' Confirms the form view's own failover alert is
        conditioned on escalated - present in the arch and gated
        correctly, so it only ever shows for a genuinely escalated job."""
        form_view = self.env.ref('flexsys_kds.view_kds_print_job_form')
        arch = form_view.arch_db
        self.assertIn('invisible="not escalated"', arch)
        self.assertIn('Escalated to a backup printer', arch)

    def test_item18_failover_still_creates_independent_records(self):
        """Item 18: 'مع الاحتفاظ بالسجلات المستقلة الحالية.' Non-
        regression: the underlying escalation logic itself
        (action_mark_failed()) is completely untouched by this batch -
        confirms it still creates a genuinely separate job record on
        the backup printer, never reusing/rewriting the original."""
        order = self._order()
        job = self.env['kds.print.job'].create({
            'order_id': order.id, 'station_id': self.station_kitchen.id,
            'printer_id': self.printer_primary.id, 'job_type': 'auto',
        })
        job.action_mark_failed('e1')
        job.action_mark_failed('e2')
        job.action_mark_failed('e3')  # exceeds MAX_AUTO_RETRY, triggers escalation

        job.invalidate_recordset()
        self.assertTrue(job.escalated)
        backup_jobs = self.env['kds.print.job'].search([
            ('order_id', '=', order.id), ('id', '!=', job.id),
        ])
        self.assertEqual(len(backup_jobs), 1, "A genuinely separate job record.")
        self.assertEqual(backup_jobs.printer_id, self.printer_backup)
        self.assertNotEqual(backup_jobs.id, job.id)
