# -*- coding: utf-8 -*-
"""Phase 3 ("POS Direct Auto Print Worker") regression suite.

HONEST SCOPE NOTE: TransactionCase runs inside a single, uncommitted
database transaction, so this environment cannot exercise real
concurrent connections against `FOR UPDATE SKIP LOCKED` (that
guarantee is only meaningful across genuinely separate, concurrent
database sessions). claim_direct_auto_jobs()'s own atomicity is
therefore verified here at the LOGICAL level - correct eligibility
filtering, correct exclusion of ineligible jobs, correct field
transitions - the same level every other test in this suite already
operates at. The claim SQL itself reuses the exact same proven
FOR UPDATE SKIP LOCKED pattern _claim_pending_jobs() (the Legacy
Agent's own claim method, already relied upon in production) uses -
no new concurrency primitive is introduced by this phase.
"""
from datetime import timedelta

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import FlexSysKdsTestCommon


@tagged('post_install', '-at_install')
class TestPhase3PosDirectAutoPrint(FlexSysKdsTestCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.station_printer_only = cls.env['kds.station'].create({
            'name': 'Test Printer Only', 'code': 'TESTPRINTERONLY', 'target_prep_time': 10,
            'operating_mode': 'printer_only',
            'flexsys_printing_method': 'direct_network',
            'flexsys_printer_ip': '192.168.1.70',
        })
        cls.station_kds_printer_auto = cls.env['kds.station'].create({
            'name': 'Test KDS+Printer Auto', 'code': 'TESTKDSPRINTERAUTO', 'target_prep_time': 10,
            'operating_mode': 'kds_printer',
            'auto_print': True,
            'flexsys_printing_method': 'direct_network',
            'flexsys_printer_ip': '192.168.1.71',
        })
        cls.pos_config = cls._make_test_pos_config('Phase 3 Test POS')
        cls.pos_session = cls.env['pos.session'].create({
            'config_id': cls.pos_config.id, 'user_id': cls.env.uid,
        })
        if hasattr(cls.pos_session, 'action_pos_session_open'):
            try:
                cls.pos_session.action_pos_session_open()
            except Exception:
                pass

    def _order_for(self, station):
        order = self._make_order([(self.product_burger, 1)])
        self._route_line_to_station(order.line_ids, station)
        return order

    # -----------------------------------------------------------------
    # A. Operating Mode / Auto Print enforcement
    # -----------------------------------------------------------------

    def test_a1_create_printer_only_forces_auto_print_true(self):
        station = self.env['kds.station'].create({
            'name': 'A1', 'code': 'TESTA1', 'target_prep_time': 10,
            'operating_mode': 'printer_only', 'auto_print': False,
        })
        self.assertTrue(station.auto_print, "printer_only must force auto_print=True even if False was requested.")

    def test_a2_write_false_on_printer_only_does_not_stick(self):
        self.station_printer_only.write({'auto_print': False})
        self.assertTrue(self.station_printer_only.auto_print)

    def test_a3_create_kds_only_forces_auto_print_false(self):
        station = self.env['kds.station'].create({
            'name': 'A3', 'code': 'TESTA3', 'target_prep_time': 10,
            'operating_mode': 'kds_only', 'auto_print': True,
        })
        self.assertFalse(station.auto_print, "kds_only must force auto_print=False even if True was requested.")

    def test_a4_switch_kds_printer_to_printer_only_forces_true(self):
        station = self.env['kds.station'].create({
            'name': 'A4', 'code': 'TESTA4', 'target_prep_time': 10,
            'operating_mode': 'kds_printer', 'auto_print': False,
        })
        station.write({'operating_mode': 'printer_only'})
        self.assertTrue(station.auto_print)

    def test_a5_switch_printer_only_to_kds_only_forces_false(self):
        station = self.env['kds.station'].create({
            'name': 'A5', 'code': 'TESTA5', 'target_prep_time': 10,
            'operating_mode': 'printer_only',
        })
        self.assertTrue(station.auto_print)
        station.write({'operating_mode': 'kds_only'})
        self.assertFalse(station.auto_print)

    def test_a6_kds_printer_freely_toggleable(self):
        station = self.env['kds.station'].create({
            'name': 'A6', 'code': 'TESTA6', 'target_prep_time': 10,
            'operating_mode': 'kds_printer', 'auto_print': False,
        })
        station.write({'auto_print': True})
        self.assertTrue(station.auto_print)
        station.write({'auto_print': False})
        self.assertFalse(station.auto_print)

    def test_a7_mixed_recordset_multi_write_applies_correct_value_per_record(self):
        """Explicit requirement: a single write() call on a recordset
        containing stations with DIFFERENT effective operating modes
        must apply the CORRECT forced value to each - never one
        shared value copied across all of them (the exact class of
        bug discovered and fixed during this phase's own
        implementation)."""
        s_printer_only = self.env['kds.station'].create({
            'name': 'A7-po', 'code': 'TESTA7PO', 'target_prep_time': 10,
            'operating_mode': 'printer_only',
        })
        s_kds_only = self.env['kds.station'].create({
            'name': 'A7-ko', 'code': 'TESTA7KO', 'target_prep_time': 10,
            'operating_mode': 'kds_only',
        })
        s_kds_printer = self.env['kds.station'].create({
            'name': 'A7-kp', 'code': 'TESTA7KP', 'target_prep_time': 10,
            'operating_mode': 'kds_printer', 'auto_print': False,
        })
        combined = s_printer_only + s_kds_only + s_kds_printer
        combined.write({'auto_print': True})

        self.assertTrue(s_printer_only.auto_print, "printer_only must remain True.")
        self.assertFalse(
            s_kds_only.auto_print,
            "kds_only must be forced back to False, NOT left at the shared True value "
            "the buggy version would have incorrectly applied to every record in the batch."
        )
        self.assertTrue(s_kds_printer.auto_print, "kds_printer's own requested True must be respected.")

    # -----------------------------------------------------------------
    # B/C. Direct Auto Job Creation + Missing IP
    # -----------------------------------------------------------------

    def test_b1_printer_only_creates_pending_direct_auto_job(self):
        order = self._order_for(self.station_printer_only)
        jobs_before = self.env['kds.print.job'].search_count([])
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.assertTrue(job)
        self.assertEqual(self.env['kds.print.job'].search_count([]), jobs_before + 1)
        self.assertEqual(job.transport, 'direct_network')
        self.assertEqual(job.job_type, 'auto')
        self.assertEqual(job.source, 'pos_auto')
        self.assertEqual(job.status, 'pending')
        self.assertFalse(job.printer_id)
        self.assertEqual(job.printer_target, '192.168.1.70')
        self.assertTrue(job.claim_deadline)

    def test_b2_kds_printer_auto_on_creates_job(self):
        order = self._order_for(self.station_kds_printer_auto)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_kds_printer_auto.id)
        self.assertTrue(job)
        self.assertEqual(job.status, 'pending')

    def test_b3_kds_printer_auto_off_creates_no_job(self):
        station = self.env['kds.station'].create({
            'name': 'B3', 'code': 'TESTB3', 'target_prep_time': 10,
            'operating_mode': 'kds_printer', 'auto_print': False,
            'flexsys_printing_method': 'direct_network', 'flexsys_printer_ip': '192.168.1.80',
        })
        order = self._order_for(station)
        jobs_before = self.env['kds.print.job'].search_count([])
        result = self.env['kds.print.job'].create_direct_auto_print_job(order.id, station.id)
        self.assertFalse(result)
        self.assertEqual(self.env['kds.print.job'].search_count([]), jobs_before)

    def test_b4_kds_only_creates_no_job(self):
        station = self.env['kds.station'].create({
            'name': 'B4', 'code': 'TESTB4', 'target_prep_time': 10,
            'operating_mode': 'kds_only',
        })
        order = self._order_for(station)
        result = self.env['kds.print.job'].create_direct_auto_print_job(order.id, station.id)
        self.assertFalse(result)

    def test_c1_missing_ip_creates_no_job_and_logs_configuration_error(self):
        station = self.env['kds.station'].create({
            'name': 'C1', 'code': 'TESTC1', 'target_prep_time': 10,
            'operating_mode': 'printer_only',
            'flexsys_printing_method': 'direct_network', 'flexsys_printer_ip': False,
        })
        order = self._order_for(station)
        jobs_before = self.env['kds.print.job'].search_count([])
        events_before = self.env['kds.event'].search_count([])
        result = self.env['kds.print.job'].create_direct_auto_print_job(order.id, station.id)
        self.assertFalse(result)
        self.assertEqual(self.env['kds.print.job'].search_count([]), jobs_before)
        self.assertGreater(self.env['kds.event'].search_count([]), events_before)

    def test_c2_no_kds_printer_record_required(self):
        """Critical: the entire point of this phase - Direct Auto works
        with ZERO kds.printer records for the station."""
        self.assertFalse(self.station_printer_only.printer_ids)
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.assertTrue(job)

    # -----------------------------------------------------------------
    # D. Idempotency
    # -----------------------------------------------------------------

    def test_d1_duplicate_auto_job_creation_prevented(self):
        order = self._order_for(self.station_printer_only)
        job1 = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.assertTrue(job1)
        jobs_before = self.env['kds.print.job'].search_count([])
        job2 = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.assertFalse(job2, "A second Auto job for the same order+station must not be created.")
        self.assertEqual(self.env['kds.print.job'].search_count([]), jobs_before)

    def test_d2_idempotency_does_not_block_manual_reprint(self):
        order = self._order_for(self.station_printer_only)
        self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        manual_result = self.env['kds.print.job'].create_direct_print_job(
            order.id, self.station_printer_only.id, source='internal_kds', bypass_check=True)
        self.assertTrue(manual_result.get('job_id'))

    def test_d3_idempotency_scoped_per_station(self):
        order = self._make_order([(self.product_burger, 1), (self.product_cappuccino, 1)])
        self._route_line_to_station(order.line_ids.filtered(lambda l: l.product_id == self.product_burger),
                                     self.station_printer_only)
        self._route_line_to_station(order.line_ids.filtered(lambda l: l.product_id == self.product_cappuccino),
                                     self.station_kds_printer_auto)
        job1 = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        job2 = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_kds_printer_auto.id)
        self.assertTrue(job1)
        self.assertTrue(job2)
        self.assertNotEqual(job1.id, job2.id)

    # -----------------------------------------------------------------
    # E/F/G/H. Atomic Claim, Multi-POS, Config eligibility, Company isolation
    # -----------------------------------------------------------------

    def test_e1_claim_returns_pending_job_as_dispatched(self):
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        claimed = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, 'device-A', limit=1)
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0]['job_id'], job.id)
        job.invalidate_recordset()
        self.assertEqual(job.status, 'dispatched')
        self.assertEqual(job.direct_executor_id, 'device-A')
        self.assertEqual(job.direct_executor_pos_config_id, self.pos_config)
        self.assertTrue(job.direct_claimed_at)
        self.assertTrue(job.dispatch_deadline)
        self.assertFalse(job.claim_deadline, "claim_deadline must be cleared once claimed.")

    def test_f1_second_claim_does_not_return_same_job(self):
        order = self._order_for(self.station_printer_only)
        self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        first = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, 'device-A', limit=1)
        second = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, 'device-B', limit=1)
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 0, "A job already claimed/dispatched must never be claimed again.")

    def test_g1_station_with_no_pos_config_link_eligible_to_any_session(self):
        self.assertFalse(self.station_printer_only.pos_config_ids)
        order = self._order_for(self.station_printer_only)
        self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        claimed = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, 'device-A', limit=1)
        self.assertEqual(len(claimed), 1)

    def test_g2_station_linked_to_other_config_not_eligible(self):
        other_config = self._make_test_pos_config('Other Config')
        linked_station = self.env['kds.station'].create({
            'name': 'G2', 'code': 'TESTG2', 'target_prep_time': 10,
            'operating_mode': 'printer_only',
            'flexsys_printing_method': 'direct_network', 'flexsys_printer_ip': '192.168.1.90',
            'pos_config_ids': [(6, 0, [other_config.id])],
        })
        order = self._order_for(linked_station)
        self.env['kds.print.job'].create_direct_auto_print_job(order.id, linked_station.id)
        claimed = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, 'device-A', limit=1)
        self.assertEqual(len(claimed), 0, "A station linked to a different POS config must not be claimable here.")

    def test_h1_different_company_station_not_eligible(self):
        order = self._order_for(self.station_kitchen_b)
        self.station_kitchen_b.write({
            'operating_mode': 'printer_only', 'flexsys_printing_method': 'direct_network',
            'flexsys_printer_ip': '10.0.0.5',
        })
        self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_kitchen_b.id)
        claimed = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, 'device-A', limit=1)
        self.assertEqual(len(claimed), 0, "A different-company station's job must not be claimable.")

    def test_inactive_station_not_claimed(self):
        station = self.env['kds.station'].create({
            'name': 'Inactive', 'code': 'TESTINACTIVE', 'target_prep_time': 10,
            'operating_mode': 'printer_only',
            'flexsys_printing_method': 'direct_network', 'flexsys_printer_ip': '192.168.1.91',
        })
        order = self._order_for(station)
        self.env['kds.print.job'].create_direct_auto_print_job(order.id, station.id)
        station.active = False
        claimed = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, 'device-A', limit=1)
        self.assertEqual(len(claimed), 0)

    # -----------------------------------------------------------------
    # J/K. Agent job isolation, Manual Direct isolation
    # -----------------------------------------------------------------

    def test_j1_agent_job_never_claimed_by_direct_auto_claim(self):
        printer = self.env['kds.printer'].create({
            'name': 'Legacy', 'station_id': self.station_kitchen.id, 'is_default': True,
        })
        order = self._order_for(self.station_kitchen)
        self.env['kds.print.job'].create({
            'order_id': order.id, 'station_id': self.station_kitchen.id,
            'printer_id': printer.id, 'job_type': 'auto', 'status': 'pending',
        })
        claimed = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, 'device-A', limit=5)
        self.assertEqual(len(claimed), 0, "A Legacy Agent job must never be claimed by Direct Auto claim.")

    def test_k1_manual_direct_job_never_claimed(self):
        order = self._order_for(self.station_printer_only)
        manual_result = self.env['kds.print.job'].create_direct_print_job(
            order.id, self.station_printer_only.id, source='internal_kds', bypass_check=True)
        manual_job = self.env['kds.print.job'].browse(manual_result['job_id'])
        self.assertEqual(manual_job.status, 'dispatched', "Manual Direct jobs start dispatched, not pending.")
        claimed = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, 'device-A', limit=5)
        self.assertEqual(len(claimed), 0)

    # -----------------------------------------------------------------
    # I. Wrong executor cannot report result
    # -----------------------------------------------------------------

    def test_i1_wrong_executor_cannot_report_result(self):
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, 'device-A', limit=1)
        job.invalidate_recordset()
        with self.assertRaises(ValidationError):
            job.report_pos_direct_auto_result(self.pos_session.id, 'device-B', True)

    def test_i2_wrong_pos_config_cannot_report_result(self):
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, 'device-A', limit=1)
        job.invalidate_recordset()
        other_config = self._make_test_pos_config('Other Config For I2')
        other_session = self.env['pos.session'].create({'config_id': other_config.id, 'user_id': self.env.uid})
        with self.assertRaises(ValidationError):
            job.report_pos_direct_auto_result(other_session.id, 'device-A', True)

    def test_i3_correct_executor_can_report_result(self):
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, 'device-A', limit=1)
        job.invalidate_recordset()
        job.report_pos_direct_auto_result(self.pos_session.id, 'device-A', True)
        self.assertEqual(job.status, 'printed')

    def test_i4_report_result_delegates_to_idempotency_engine(self):
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, 'device-A', limit=1)
        job.invalidate_recordset()
        job.report_pos_direct_auto_result(self.pos_session.id, 'device-A', True)
        job.report_pos_direct_auto_result(self.pos_session.id, 'device-A', True)
        self.assertEqual(job.status, 'printed')
        with self.assertRaises(ValidationError):
            job.report_pos_direct_auto_result(self.pos_session.id, 'device-A', False, error_code='X')

    # -----------------------------------------------------------------
    # L/M/N. Timeouts + Legacy Agent cron isolation
    # -----------------------------------------------------------------

    def test_l1_pending_past_claim_deadline_fails_with_no_executor(self):
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        job.claim_deadline = job.claim_deadline - timedelta(hours=1)
        self.env['kds.print.job']._cron_timeout_stale_direct_jobs()
        job.invalidate_recordset()
        self.assertEqual(job.status, 'failed')
        self.assertEqual(job.error_code, 'NO_EXECUTOR')
        self.assertTrue(job.failed_at)

    def test_audit_blocker1_expired_claim_deadline_not_claimable_before_cron(self):
        """BLOCKER 1 ("Version 43 - Final Phase 3 Corrections"):
        confirmed by direct read - the atomic claim SQL did not check
        claim_deadline at all, so a job whose deadline had already
        expired could still be claimed and physically printed in the
        window before the timeout cron got around to failing it. This
        proves the deadline is now enforced INSIDE the same atomic
        claim, not only by the cron: with the cron deliberately NOT
        run, an expired-deadline job must return zero claims and stay
        untouched (still 'pending', deadline still in the past) -
        only the separate cron run afterward may actually fail it."""
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        job.claim_deadline = job.claim_deadline - timedelta(hours=1)

        # Deliberately do NOT run the cron here - claim must reject
        # this job on its own, at claim time.
        claimed = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, 'device-A', limit=1)
        self.assertEqual(len(claimed), 0, "An expired-deadline job must never be claimable.")
        job.invalidate_recordset()
        self.assertEqual(job.status, 'pending', "The job must remain untouched by the claim attempt itself.")

        # Now the cron processes it, as the only mechanism that
        # actually transitions it to Failed.
        self.env['kds.print.job']._cron_timeout_stale_direct_jobs()
        job.invalidate_recordset()
        self.assertEqual(job.status, 'failed')
        self.assertEqual(job.error_code, 'NO_EXECUTOR')

    def test_l2_pending_not_yet_past_deadline_untouched(self):
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.env['kds.print.job']._cron_timeout_stale_direct_jobs()
        job.invalidate_recordset()
        self.assertEqual(job.status, 'pending')

    def test_m1_dispatched_past_dispatch_deadline_fails_with_result_timeout(self):
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, 'device-A', limit=1)
        job.invalidate_recordset()
        job.dispatch_deadline = job.dispatch_deadline - timedelta(hours=1)
        self.env['kds.print.job']._cron_timeout_stale_direct_jobs()
        job.invalidate_recordset()
        self.assertEqual(job.status, 'failed')
        self.assertEqual(job.error_code, 'RESULT_TIMEOUT')

    def test_n1_legacy_agent_job_untouched_by_direct_cron(self):
        printer = self.env['kds.printer'].create({
            'name': 'N1', 'station_id': self.station_kitchen.id, 'is_default': True,
        })
        order = self._order_for(self.station_kitchen)
        agent_job = self.env['kds.print.job'].create({
            'order_id': order.id, 'station_id': self.station_kitchen.id,
            'printer_id': printer.id, 'job_type': 'auto', 'status': 'pending',
        })
        self.env['kds.print.job']._cron_timeout_stale_direct_jobs()
        agent_job.invalidate_recordset()
        self.assertEqual(agent_job.status, 'pending', "Legacy Agent jobs must be untouched by this cron.")
        self.assertFalse(agent_job.error_code)

    # -----------------------------------------------------------------
    # O. Payload content/scoping
    # -----------------------------------------------------------------

    def test_o1_payload_contains_required_fields(self):
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        claimed = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, 'device-A', limit=1)
        payload = claimed[0]
        self.assertEqual(payload['job_id'], job.id)
        self.assertEqual(payload['printer_ip'], '192.168.1.70')
        self.assertIn('use_local_network_access', payload)
        self.assertIn('station_name', payload)
        self.assertIn('branch_name', payload)
        self.assertEqual(payload['ticket_status'], 'NEW')
        order_payload = payload['order']
        for key in ('id', 'name', 'pos_reference', 'order_type_label', 'table_label',
                    'created_time', 'employee_name', 'lines'):
            self.assertIn(key, order_payload)

    def test_o2_payload_only_station_scoped_noncancelled_lines(self):
        order = self._make_order([(self.product_burger, 1), (self.product_cappuccino, 1)])
        burger_line = order.line_ids.filtered(lambda l: l.product_id == self.product_burger)
        coffee_line = order.line_ids.filtered(lambda l: l.product_id == self.product_cappuccino)
        self._route_line_to_station(burger_line, self.station_printer_only)
        self._route_line_to_station(coffee_line, self.station_kds_printer_auto)
        self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        claimed = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, 'device-A', limit=1)
        lines = claimed[0]['order']['lines']
        self.assertEqual(len(lines), 1, "Only this station's own line must be in the payload.")
        self.assertEqual(lines[0]['product_name'], self.product_burger.name)

    # -----------------------------------------------------------------
    # P. Asset ordering (static contract check)
    # -----------------------------------------------------------------

    def test_p1_pos_assets_ordering(self):
        import ast
        import os
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(module_dir, '__manifest__.py'), encoding='utf-8') as f:
            data = ast.literal_eval(f.read())
        pos_assets = data['assets']['point_of_sale._assets_pos']
        renderer_idx = next(i for i, a in enumerate(pos_assets) if 'flexsys_ticket_renderer' in a)
        adapter_idx = next(i for i, a in enumerate(pos_assets) if 'flexsys_epos_direct_adapter' in a)
        worker_idx = next(i for i, a in enumerate(pos_assets) if 'flexsys_pos_direct_print_worker' in a)
        self.assertLess(renderer_idx, worker_idx)
        self.assertLess(adapter_idx, worker_idx)
        self.assertFalse(
            any('static/src/public/' in a or 'flexsys_epos_direct_public' in a for a in pos_assets),
            "Public Kiosk-only files must not be loaded into POS assets."
        )

    # -----------------------------------------------------------------
    # Structural sanity (delivery checklist items)
    # -----------------------------------------------------------------

    def test_zz_no_duplicate_source_field_definition(self):
        import os
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(module_dir, 'models', 'kds_print_job.py'), encoding='utf-8') as f:
            content = f.read()
        self.assertEqual(content.count('source = fields.Selection(['), 1)

    def test_zz_no_agent_fallback_in_direct_auto_creation(self):
        import os
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(module_dir, 'models', 'pos_order.py'), encoding='utf-8') as f:
            content = f.read()
        auto_print_fn = content.split('def _flexsys_kds_auto_print')[1].split('\n\n')[0]
        self.assertNotIn('printer_ids', auto_print_fn)
        self.assertNotIn("'agent'", auto_print_fn)

    # -----------------------------------------------------------------
    # AUDIT FIX ("Phase 3 - Audit Corrections Before Odoo.sh")
    # -----------------------------------------------------------------

    def test_audit1_claim_direct_auto_jobs_is_api_model(self):
        """BLOCKER 1: without @api.model, Odoo's own call_kw treats
        args[0] (pos_session_id in the real POS RPC call shape) as
        record ids to browse() and strips it before calling the
        method - silently shifting every subsequent argument. A plain
        Python ORM test calling claim_direct_auto_jobs(session_id,
        executor_id) directly cannot catch this at all (it bypasses
        call_kw entirely) - this is a static source-contract check
        specifically so that gap can't hide the bug again."""
        import os
        import re
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(module_dir, 'models', 'kds_print_job.py'), encoding='utf-8') as f:
            content = f.read()
        match = re.search(r'(@api\.model\s*\n)?\s*def claim_direct_auto_jobs\(', content)
        self.assertIsNotNone(match, "claim_direct_auto_jobs() not found at all.")
        self.assertIsNotNone(
            match.group(1),
            "claim_direct_auto_jobs must be decorated with @api.model - without it, "
            "the RPC's own first argument (pos_session_id) is misinterpreted as "
            "record ids by Odoo's call_kw."
        )

    def test_audit1_report_pos_direct_auto_result_is_not_api_model(self):
        """The opposite check, for the opposite reason: this method IS
        meant to rely on Odoo's own automatic browse(args[0]) behavior
        - the POS worker's own call passes job_id as the first RPC
        argument specifically so it becomes `self` (ensure_one()'d
        inside). Decorating this one with @api.model would break that
        - it must stay a plain instance method."""
        import os
        import re
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(module_dir, 'models', 'kds_print_job.py'), encoding='utf-8') as f:
            content = f.read()
        match = re.search(r'(@api\.model\s*\n)?\s*def report_pos_direct_auto_result\(', content)
        self.assertIsNotNone(match)
        self.assertIsNone(
            match.group(1),
            "report_pos_direct_auto_result must NOT be @api.model - it relies on "
            "Odoo's own automatic self=browse(job_id) from the RPC's first argument."
        )

    def test_audit2_offline_send_warning_setup_patch_is_async_and_awaits_super(self):
        """BLOCKER 2: this patch sits earlier in PosStore's own patch
        chain than the Phase 3 worker's own setup() patch. If this one
        isn't itself `async` and doesn't genuinely `await
        super.setup(...args)`, a LATER patch's own `await
        super.setup(...args)` resolves against this synchronous
        wrapper instead of the real Odoo setup() further down the
        chain - defeating the worker's own readiness guarantee
        (this.config/this.device/this.session not actually ready yet
        when the worker starts)."""
        import os
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(module_dir, 'static', 'src', 'js', 'flexsys_kds_offline_send_warning.js')
        with open(path, encoding='utf-8') as f:
            content = f.read()
        self.assertIn(
            'async setup(...args)', content,
            "The setup() patch in flexsys_kds_offline_send_warning.js must be async."
        )
        self.assertIn(
            'await super.setup(...args)', content,
            "The setup() patch must genuinely await super.setup(), not just call it, "
            "so later patches in the same chain get a real completion signal."
        )

    def test_audit2_pos_direct_print_worker_still_awaits_super_setup(self):
        """Non-regression: confirms the Phase 3 worker's own patch
        still awaits super.setup() too (both ends of the chain must
        hold for the guarantee to actually work end to end)."""
        import os
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(module_dir, 'static', 'src', 'js', 'flexsys_pos_direct_print_worker.js')
        with open(path, encoding='utf-8') as f:
            content = f.read()
        self.assertIn('async setup(...args)', content)
        self.assertIn('await super.setup(...args)', content)

    def test_audit3_config_change_after_creation_before_claim_disables_claim(self):
        """BLOCKER/gap 3: a job created while Auto Print was enabled
        must NOT remain claimable once the station's own configuration
        has since changed to no longer allow it - re-validated at
        CLAIM time, not only trusted from job-creation time."""
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.assertTrue(job)
        # Configuration changes AFTER creation, BEFORE claim.
        self.station_printer_only.write({'operating_mode': 'kds_only'})
        claimed = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, 'device-A', limit=1)
        self.assertEqual(len(claimed), 0, "A job must not be claimable once its station switched to KDS Only.")

    def test_audit3_auto_print_disabled_after_creation_before_claim(self):
        order = self._order_for(self.station_kds_printer_auto)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_kds_printer_auto.id)
        self.assertTrue(job)
        self.station_kds_printer_auto.write({'auto_print': False})
        claimed = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, 'device-A', limit=1)
        self.assertEqual(len(claimed), 0, "A job must not be claimable once Auto Print was disabled.")

    def test_audit3_printer_ip_removed_after_creation_before_claim(self):
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.assertTrue(job)
        self.station_printer_only.write({'flexsys_printer_ip': False})
        claimed = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, 'device-A', limit=1)
        self.assertEqual(len(claimed), 0, "A job must not be claimable once the Printer IP was removed.")

    def test_audit4_other_users_session_cannot_claim(self):
        """Item 4: an authenticated user cannot claim through a POS
        session that belongs to a DIFFERENT user, even though that
        session genuinely exists and is open."""
        other_user = self.env['res.users'].create({
            'name': 'Other Cashier', 'login': 'other_cashier_audit4',
            'groups_id': [(6, 0, [self.env.ref('point_of_sale.group_pos_user').id])],
        })
        other_session = self.env['pos.session'].create({
            'config_id': self.pos_config.id, 'user_id': other_user.id,
        })
        order = self._order_for(self.station_printer_only)
        self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        claimed = self.env['kds.print.job'].claim_direct_auto_jobs(other_session.id, 'device-X', limit=1)
        self.assertEqual(
            len(claimed), 0,
            "The current user must not be able to claim through another user's own POS session."
        )

    def test_audit4_other_users_session_cannot_report_result(self):
        other_user = self.env['res.users'].create({
            'name': 'Other Cashier 2', 'login': 'other_cashier_audit4b',
            'groups_id': [(6, 0, [self.env.ref('point_of_sale.group_pos_user').id])],
        })
        other_session = self.env['pos.session'].create({
            'config_id': self.pos_config.id, 'user_id': other_user.id,
        })
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, 'device-A', limit=1)
        job.invalidate_recordset()
        with self.assertRaises(ValidationError):
            job.report_pos_direct_auto_result(other_session.id, 'device-A', True)

    def test_audit5_auto_print_readonly_for_printer_only(self):
        """Item 5: Printer Only must show auto_print visible but
        readonly (locked at the backend-enforced True) - KDS Only
        stays hidden, KDS+Printer stays freely editable, both
        unchanged."""
        import os
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(module_dir, 'views', 'kds_station_views.xml'), encoding='utf-8') as f:
            content = f.read()
        self.assertIn('invisible="operating_mode == \'kds_only\'"', content)
        self.assertIn('readonly="operating_mode == \'printer_only\'"', content)

    # -----------------------------------------------------------------
    # AUDIT FIX ("Version 43 - Final Phase 3 Corrections Before Odoo.sh")
    # -----------------------------------------------------------------

    def test_v43_claim_sql_enforces_claim_deadline(self):
        """BLOCKER 1: confirmed - the atomic claim SQL did not check
        claim_deadline at all. Static source check confirming the
        deadline condition is now genuinely inside the same WHERE
        clause as the other eligibility conditions (functional
        coverage for the same requirement lives in
        test_audit_blocker1_expired_claim_deadline_not_claimable_before_cron
        above, which exercises it against a real record)."""
        import os
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(module_dir, 'models', 'kds_print_job.py'), encoding='utf-8') as f:
            content = f.read()
        claim_method = content.split('def claim_direct_auto_jobs(')[1].split('\n    def ')[0]
        self.assertIn('claim_deadline IS NOT NULL', claim_method)
        self.assertIn("claim_deadline > (NOW() AT TIME ZONE 'UTC')", claim_method)

    def test_v43_worker_flush_pending_results_returns_boolean_and_blocks_claim(self):
        """Item 2: static contract check - _flushPendingResults() must
        return a value (used by _runCycle() to decide whether to
        proceed to a new claim), and _runCycle() must genuinely check
        it and return early rather than always proceeding to
        _claimAndPrintOne() regardless."""
        import os
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(module_dir, 'static', 'src', 'js', 'flexsys_pos_direct_print_worker.js')
        with open(path, encoding='utf-8') as f:
            content = f.read()
        flush_method = content.split('async _flushPendingResults()')[1].split('\n    async ')[0]
        self.assertIn('let allFlushed = true', flush_method)
        self.assertIn('allFlushed = false', flush_method)
        self.assertIn('return allFlushed', flush_method)

        run_cycle = content.split('async _runCycle()')[1].split('\n    async _flushPendingResults')[0]
        self.assertIn('const allFlushed = await this._flushPendingResults()', run_cycle)
        self.assertIn('if (!allFlushed) {', run_cycle)

    def test_v43_worker_start_guard_moved_to_posstore_level(self):
        """Item 3: confirmed - start()'s own `if (this.running) return;`
        guard did nothing against a repeated setup() call, since a
        brand-new worker object (fresh running=false) was
        unconditionally created every time. The guard must now live in
        the setup() patch itself, checking `this._flexsysDirectPrintWorker`
        BEFORE constructing a new worker."""
        import os
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(module_dir, 'static', 'src', 'js', 'flexsys_pos_direct_print_worker.js')
        with open(path, encoding='utf-8') as f:
            content = f.read()
        setup_method = content.split('async setup(...args)')[1]
        self.assertIn('if (!this._flexsysDirectPrintWorker) {', setup_method)
        # The construction and start() call must be INSIDE that guard,
        # not before/outside it.
        guard_body = setup_method.split('if (!this._flexsysDirectPrintWorker) {')[1].split('\n            }')[0]
        self.assertIn('new FlexSysPosDirectPrintWorker(this)', guard_body)
        self.assertIn('.start()', guard_body)

    def test_v43_worker_no_recursive_runcycle_call_from_claim_and_print(self):
        """Item 4: confirmed - the old `this._runCycle();` call at the
        end of _claimAndPrintOne() was a no-op in practice (the outer
        _runCycle() still had cycleInFlight=true, so the inner call
        exited immediately on its own guard). It must be gone -
        replaced by a genuine sequential loop in _runCycle() itself
        that awaits _claimAndPrintOne() repeatedly until it returns a
        falsy value, never introducing concurrent claims/prints."""
        import os
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(module_dir, 'static', 'src', 'js', 'flexsys_pos_direct_print_worker.js')
        with open(path, encoding='utf-8') as f:
            content = f.read()
        claim_and_print_method = content.split('async _claimAndPrintOne()')[1].split('\n    /**')[0].split(
            '\n    async setup')[0]
        self.assertNotIn(
            'this._runCycle()', claim_and_print_method,
            "_claimAndPrintOne() must no longer call this._runCycle() itself - "
            "that call was a no-op due to cycleInFlight still being true in the caller."
        )
        self.assertIn('return true;', claim_and_print_method)
        self.assertIn('return false;', claim_and_print_method)

        run_cycle = content.split('async _runCycle()')[1].split('\n    async _flushPendingResults')[0]
        self.assertIn('while (await this._claimAndPrintOne())', run_cycle)

    def test_v43_release_status_test_counts_accurate(self):
        """Item 5: confirmed - RELEASE_STATUS.md still referenced the
        stale 596/588 numbers from long before Phase 3. The document
        must state the actual last-confirmed pre-Phase-3 Odoo.sh
        baseline (636 post-tests, 662 tests total) and the current,
        not-yet-run package's own real static test count (683), and
        must not claim the current package has passed Odoo.sh."""
        import os
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(module_dir, 'RELEASE_STATUS.md'), encoding='utf-8') as f:
            content = f.read()
        self.assertIn('636 post-tests', content)
        self.assertIn('662 tests', content)
        self.assertIn('683', content)
        self.assertNotIn('588 post-tests', content)
        self.assertNotIn('596 tests', content)

    def test_v43_legacy_agent_removal_wording_conditional_not_general(self):
        """Item 5: the wording must state a CONDITIONAL, planned
        removal phase (only after Odoo.sh + real Epson hardware
        validation) - not a general "not scheduled for removal"
        statement that implies no removal plan exists at all."""
        import os
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for rel_path in ('README.md', os.path.join('docs', 'ARCHITECTURE.md')):
            with open(os.path.join(module_dir, rel_path), encoding='utf-8') as f:
                content = f.read()
            self.assertNotIn('not scheduled for removal', content, rel_path)
            self.assertIn('separate removal phase is planned', content, rel_path)

    def test_v44_result_report_failure_during_loop_stops_further_claims(self):
        """BLOCKER ("Version 44 - One Remaining Worker Runtime
        Blocker"): confirmed - _claimAndPrintOne() used to
        unconditionally `return true;` after its own report try/catch,
        regardless of whether the report RPC actually succeeded. That
        meant: Job A physically printed -> its own result persisted to
        localStorage -> the report RPC fails -> marker correctly stays
        -> but the method still returned true -> the while loop in
        _runCycle() immediately claimed and physically printed Job B in
        the SAME cycle, with Job A's own result still unacknowledged.

        This is a DIFFERENT scenario from
        test_v43_worker_flush_pending_results_returns_boolean_and_blocks_claim
        above, which only verifies an ALREADY-stale marker (from some
        earlier cycle) blocks a claim at the very START of a cycle -
        this test targets the report RPC failing DURING the current
        loop's own iteration instead. Static structural check: `return
        true;` and `return false;` must both live INSIDE the report
        try/catch itself (true only on the success path after
        clearPendingResult, false on the catch path with no
        clearPendingResult call before it) - not as one shared
        `return true;` statement after the try/catch block."""
        import os
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(module_dir, 'static', 'src', 'js', 'flexsys_pos_direct_print_worker.js')
        with open(path, encoding='utf-8') as f:
            content = f.read()

        claim_and_print_method = content.split('async _claimAndPrintOne()')[1].split(
            '\n    /**')[0].split('\n    async setup')[0]

        # The report_pos_direct_auto_result call site's own try block.
        report_try_block = claim_and_print_method.split(
            'await this.pos.data.call("kds.print.job", "report_pos_direct_auto_result"'
        )[1]
        try_side = report_try_block.split('} catch (error) {')[0]
        catch_side = report_try_block.split('} catch (error) {')[1]

        self.assertIn(
            'clearPendingResult(resultEntry.job_id);', try_side,
            "The marker must be cleared on the SUCCESS side of the report try/catch."
        )
        self.assertIn(
            'return true;', try_side,
            "return true must be inside the try block, immediately after a successful "
            "report and clearPendingResult - never unconditional after the try/catch."
        )
        self.assertNotIn(
            'clearPendingResult', catch_side,
            "The marker must NOT be cleared when the report RPC itself failed."
        )
        self.assertIn(
            'return false;', catch_side,
            "A failed report RPC must return false, stopping the sequential claim "
            "loop immediately - a Job A whose result is unacknowledged must block "
            "Job B from being claimed in the same cycle."
        )

        # Confirm there is no longer a single shared `return true;`
        # statement sitting after the closing brace of the try/catch
        # (the exact structure of the original bug).
        after_catch = claim_and_print_method.split(catch_side, 1)[1]
        # Only whitespace/closing braces should remain between the end
        # of the catch block and the end of the method - no bare
        # `return true;` floating outside both branches.
        tail_before_method_close = after_catch.split('}\n    }')[0]
        self.assertNotIn('return true;', tail_before_method_close)

    def test_v44_release_status_test_count_matches_actual_count(self):
        """TEST COUNT DOCUMENTATION: the number written into
        RELEASE_STATUS.md must match the ACTUAL count of `def test_`
        methods across every tests/*.py file, computed here
        programmatically rather than trusted as a hand-maintained
        number - the same mismatch this round's own report explicitly
        flagged (RELEASE_STATUS.md said 683 while the real count had
        already moved to 690/691). This test recomputes the real count
        every time it runs, so a future round that adds tests without
        updating this document will be caught here rather than
        silently drifting again."""
        import glob
        import os
        import re
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        actual_count = 0
        for path in glob.glob(os.path.join(module_dir, 'tests', '*.py')):
            with open(path, encoding='utf-8') as f:
                content = f.read()
            actual_count += len(re.findall(r'^    def test_', content, re.MULTILINE))

        with open(os.path.join(module_dir, 'RELEASE_STATUS.md'), encoding='utf-8') as f:
            release_status = f.read()

        self.assertIn(
            '%d static test methods' % actual_count, release_status,
            "RELEASE_STATUS.md's own documented test count (%d) does not match "
            "the actual, programmatically-verified count." % actual_count
        )
