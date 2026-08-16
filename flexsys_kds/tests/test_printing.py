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
        order = self._order()
        job = self.env['kds.print.job'].create({
            'order_id': order.id,
            'station_id': self.station_kitchen.id,
            'printer_id': self.printer_primary.id,
            'job_type': 'auto',
        })
        job.action_dispatch()
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
