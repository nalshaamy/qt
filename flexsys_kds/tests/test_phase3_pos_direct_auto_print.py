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

    def _order_for(self, station, company=None):
        """AUDIT FIX ("Version 49 - One Test Fixture Correction
        Only"): `company` is optional and defaults to None (which
        _make_order() itself already treats as self.company) - added
        so a station belonging to a NON-default company (e.g.
        self.company_b) can have its own order genuinely created
        under that same company, rather than always defaulting to the
        suite's own primary test company regardless of which company
        the station itself actually belongs to."""
        order = self._make_order([(self.product_burger, 1)], company=company)
        self._route_line_to_station(order.line_ids, station)
        return order

    def _make_pos_only_user(self, login):
        """AUDIT FIX ("Version 45 - Odoo.sh Regression Corrections"),
        item 2: a plain POS-user fixture, using the SAME field-name
        auto-detection FlexSysKdsTestCommon._make_kds_user() already
        established as the confirmed-correct fix for this Odoo 19
        build's own unstable res.users<->res.groups field name
        (group_ids vs groups_id) - the prior version of this fixture
        hardcoded 'groups_id' directly instead, which is exactly what
        produced a real ERROR (not a failed assertion) on live
        Odoo.sh. Not reusing _make_kds_user() itself since that one
        assigns a FlexSys KDS administrative group plus optional
        kds_station_ids - genuinely different from a plain POS cashier
        with no KDS permissions at all, which is the actual scenario
        these tests need."""
        groups_field = next(
            (name for name in ('group_ids', 'groups_id') if name in self.env['res.users']._fields),
            'groups_id',
        )
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': login,
            'login': login,
            'email': '%s@example.com' % login,
            groups_field: [(6, 0, [self.env.ref('point_of_sale.group_pos_user').id])],
        })

    def _grant_company_access(self, user, company):
        """AUDIT FIX ("Version 49 - One Test Fixture Correction
        Only"): a plain _make_pos_only_user() grants no company
        access beyond the default (self.company) - explicitly
        granting a user genuine access to a SECOND company
        (company_ids includes it, company_id switched to it as their
        own current/default company) is required to build a
        genuinely legitimate "Company B owner" fixture. Without this,
        self.env.companies for that user never actually includes
        company_b, and the production company-isolation check added
        in Version 48 (`config.company_id not in self.env.companies`)
        would incorrectly reject even the LEGITIMATE Company B claim
        this test needs to first prove succeeds, before it can then
        prove the cross-company rejection for a genuinely different,
        Company-A-only caller."""
        user.write({
            'company_ids': [(4, company.id)],
            'company_id': company.id,
        })
        return user

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
        claimed = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, self.pos_session.sudo().access_token, 'device-A', limit=1)
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
        first = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, self.pos_session.sudo().access_token, 'device-A', limit=1)
        second = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, self.pos_session.sudo().access_token, 'device-B', limit=1)
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 0, "A job already claimed/dispatched must never be claimed again.")

    def test_g1_station_with_no_pos_config_link_eligible_to_any_session(self):
        self.assertFalse(self.station_printer_only.pos_config_ids)
        order = self._order_for(self.station_printer_only)
        self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        claimed = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, self.pos_session.sudo().access_token, 'device-A', limit=1)
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
        claimed = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, self.pos_session.sudo().access_token, 'device-A', limit=1)
        self.assertEqual(len(claimed), 0, "A station linked to a different POS config must not be claimable here.")

    def test_h1_different_company_station_not_eligible(self):
        order = self._order_for(self.station_kitchen_b)
        self.station_kitchen_b.write({
            'operating_mode': 'printer_only', 'flexsys_printing_method': 'direct_network',
            'flexsys_printer_ip': '10.0.0.5',
        })
        self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_kitchen_b.id)
        claimed = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, self.pos_session.sudo().access_token, 'device-A', limit=1)
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
        claimed = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, self.pos_session.sudo().access_token, 'device-A', limit=1)
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
        claimed = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, self.pos_session.sudo().access_token, 'device-A', limit=5)
        self.assertEqual(len(claimed), 0, "A Legacy Agent job must never be claimed by Direct Auto claim.")

    def test_k1_manual_direct_job_never_claimed(self):
        order = self._order_for(self.station_printer_only)
        manual_result = self.env['kds.print.job'].create_direct_print_job(
            order.id, self.station_printer_only.id, source='internal_kds', bypass_check=True)
        manual_job = self.env['kds.print.job'].browse(manual_result['job_id'])
        self.assertEqual(manual_job.status, 'dispatched', "Manual Direct jobs start dispatched, not pending.")
        claimed = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, self.pos_session.sudo().access_token, 'device-A', limit=5)
        self.assertEqual(len(claimed), 0)

    # -----------------------------------------------------------------
    # I. Wrong executor cannot report result
    # -----------------------------------------------------------------

    def test_i1_wrong_executor_cannot_report_result(self):
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, self.pos_session.sudo().access_token, 'device-A', limit=1)
        job.invalidate_recordset()
        with self.assertRaises(ValidationError):
            job.report_pos_direct_auto_result(self.pos_session.id, self.pos_session.sudo().access_token, 'device-B', True)

    def test_i2_wrong_pos_config_cannot_report_result(self):
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, self.pos_session.sudo().access_token, 'device-A', limit=1)
        job.invalidate_recordset()
        other_config = self._make_test_pos_config('Other Config For I2')
        other_session = self.env['pos.session'].create({'config_id': other_config.id, 'user_id': self.env.uid})
        with self.assertRaises(ValidationError):
            job.report_pos_direct_auto_result(other_session.id, other_session.sudo().access_token, 'device-A', True)

    def test_i3_correct_executor_can_report_result(self):
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, self.pos_session.sudo().access_token, 'device-A', limit=1)
        job.invalidate_recordset()
        job.report_pos_direct_auto_result(self.pos_session.id, self.pos_session.sudo().access_token, 'device-A', True)
        self.assertEqual(job.status, 'printed')

    def test_i4_report_result_delegates_to_idempotency_engine(self):
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, self.pos_session.sudo().access_token, 'device-A', limit=1)
        job.invalidate_recordset()
        job.report_pos_direct_auto_result(self.pos_session.id, self.pos_session.sudo().access_token, 'device-A', True)
        job.report_pos_direct_auto_result(self.pos_session.id, self.pos_session.sudo().access_token, 'device-A', True)
        self.assertEqual(job.status, 'printed')
        with self.assertRaises(ValidationError):
            job.report_pos_direct_auto_result(self.pos_session.id, self.pos_session.sudo().access_token, 'device-A', False, error_code='X')

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
        claimed = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, self.pos_session.sudo().access_token, 'device-A', limit=1)
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
        self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, self.pos_session.sudo().access_token, 'device-A', limit=1)
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
        claimed = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, self.pos_session.sudo().access_token, 'device-A', limit=1)
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
        claimed = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, self.pos_session.sudo().access_token, 'device-A', limit=1)
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
        """AUDIT FIX ("Version 45 - Odoo.sh Regression Corrections"),
        item 4 + FINAL REVIEW: confirmed live - the prior version of
        this test searched the raw function SOURCE TEXT for
        'printer_ids', which also matches inside an explanatory
        comment describing what the code USED to do before this phase
        ("this used to require station.printer_ids...") - a false
        positive that has nothing to do with executable behavior.

        The BEHAVIORAL assertion is now the primary check (per this
        round's own explicit direction that test success must not
        depend only on source-text inspection): creates a real Direct
        Auto job through the actual _flexsys_kds_auto_print() /
        create_direct_auto_print_job() path and confirms its own
        concrete field values (transport, source, printer_id,
        printer_target) directly - not merely the absence of a
        keyword. The source-text check (with Python comments stripped
        first, so a historical-context comment can never trip it) is
        kept as a secondary, complementary guard, not the test's own
        primary basis for passing."""
        # --- Primary: behavioral assertion on the real created job. ---
        printers_before = self.env['kds.printer'].search_count([])
        agent_jobs_before = self.env['kds.print.job'].search_count([('transport', '=', 'agent')])
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.assertTrue(job)
        self.assertEqual(job.transport, 'direct_network')
        self.assertEqual(job.source, 'pos_auto')
        self.assertFalse(job.printer_id, "Direct Auto jobs must never carry a kds.printer.")
        self.assertEqual(job.printer_target, self.station_printer_only.flexsys_printer_ip)
        self.assertEqual(
            self.env['kds.printer'].search_count([]), printers_before,
            "No kds.printer record may be created by the Direct Auto path."
        )
        self.assertEqual(
            self.env['kds.print.job'].search_count([('transport', '=', 'agent')]), agent_jobs_before,
            "No 'agent'-transport job may be created by the Direct Auto path."
        )

        # --- Secondary: source-text guard, comments stripped. ---
        import os
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(module_dir, 'models', 'pos_order.py'), encoding='utf-8') as f:
            content = f.read()
        auto_print_fn = content.split('def _flexsys_kds_auto_print')[1].split('\n\n')[0]
        code_only = '\n'.join(
            line for line in auto_print_fn.split('\n')
            if not line.strip().startswith('#')
        )
        self.assertNotIn(
            'printer_ids', code_only,
            "The EXECUTABLE code of _flexsys_kds_auto_print must not reference "
            "printer_ids - a comment mentioning it for historical context is fine."
        )
        self.assertNotIn("'agent'", code_only)

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
        claimed = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, self.pos_session.sudo().access_token, 'device-A', limit=1)
        self.assertEqual(len(claimed), 0, "A job must not be claimable once its station switched to KDS Only.")

    def test_audit3_auto_print_disabled_after_creation_before_claim(self):
        order = self._order_for(self.station_kds_printer_auto)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_kds_printer_auto.id)
        self.assertTrue(job)
        self.station_kds_printer_auto.write({'auto_print': False})
        claimed = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, self.pos_session.sudo().access_token, 'device-A', limit=1)
        self.assertEqual(len(claimed), 0, "A job must not be claimable once Auto Print was disabled.")

    def test_audit3_printer_ip_removed_after_creation_before_claim(self):
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.assertTrue(job)
        self.station_printer_only.write({'flexsys_printer_ip': False})
        claimed = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, self.pos_session.sudo().access_token, 'device-A', limit=1)
        self.assertEqual(len(claimed), 0, "A job must not be claimable once the Printer IP was removed.")

    # -----------------------------------------------------------------
    # AUDIT FIX ("Version 47 - Odoo 19 POS Session Identity
    # Correction"): the two tests previously here
    # (test_audit4_other_users_session_cannot_claim /
    # ..._cannot_report_result) asserted that a DIFFERENT authenticated
    # user claiming/reporting through another user's own open session
    # must be REJECTED - confirmed against Odoo 19's own real source
    # that this is not the correct contract: Odoo 19 genuinely allows
    # the SAME pos.session to be used by a different authenticated
    # user than whoever originally opened it (session.user_id stays
    # the original opener; a later user is still legitimately using
    # that same session). Session identity is proven with the
    # session's own standard access_token instead - REPLACED below
    # with the full B-M contract: shared-session success, wrong/
    # missing/mismatched token rejection, non-POS-user rejection,
    # closed-session rejection, full payload/printed/failed success
    # paths, and wrong executor/session/token rejection on report.
    # -----------------------------------------------------------------

    def test_v47_a_access_token_field_exists_on_pos_session(self):
        """Sanity check, explicitly required before relying on this
        field anywhere: pos.session must genuinely have an
        access_token field in this Odoo 19 build - confirmed by the
        client against Odoo 19's own real source
        (pos_session.py::_load_pos_data_fields() explicitly loads it),
        verified here directly against the live model schema rather
        than trusted blindly."""
        self.assertIn('access_token', self.env['pos.session']._fields)

    def test_v47_b_shared_session_different_authenticated_user_succeeds(self):
        """Item B: the core Odoo 19 behavior this whole round exists
        to correctly support - Session X opened by User A,
        authenticated User B (also a valid POS user) supplies Session
        X's own id and its correct access_token - claim must SUCCEED.
        This is the exact scenario the OLD session.user_id == env.user
        check would have wrongly rejected."""
        config_x = self._make_test_pos_config('V47 Shared Session Config')
        user_a = self._make_pos_only_user('v47_shared_user_a')
        user_b = self._make_pos_only_user('v47_shared_user_b')
        session_x = self.env['pos.session'].create({'config_id': config_x.id, 'user_id': user_a.id})

        order = self._order_for(self.station_printer_only)
        self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)

        # User B, genuinely acting as themselves (no sudo), supplies
        # Session X's own real id/token even though User A opened it.
        claimed = self.env['kds.print.job'].with_user(user_b).claim_direct_auto_jobs(
            session_x.id, session_x.sudo().access_token, 'device-shared', limit=1)
        self.assertEqual(len(claimed), 1, "A different authenticated POS user sharing the same "
                                           "session with its correct token must succeed.")

    def test_v47_c_wrong_token_rejected(self):
        config = self._make_test_pos_config('V47 Wrong Token Config')
        user = self._make_pos_only_user('v47_wrong_token_user')
        session = self.env['pos.session'].create({'config_id': config.id, 'user_id': user.id})
        order = self._order_for(self.station_printer_only)
        self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)

        claimed = self.env['kds.print.job'].with_user(user).claim_direct_auto_jobs(
            session.id, 'totally-wrong-token', 'device-X', limit=1)
        self.assertEqual(len(claimed), 0, "A wrong session token must reject the claim.")

    def test_v47_d_missing_token_rejected(self):
        config = self._make_test_pos_config('V47 Missing Token Config')
        user = self._make_pos_only_user('v47_missing_token_user')
        session = self.env['pos.session'].create({'config_id': config.id, 'user_id': user.id})
        order = self._order_for(self.station_printer_only)
        self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)

        claimed = self.env['kds.print.job'].with_user(user).claim_direct_auto_jobs(
            session.id, False, 'device-X', limit=1)
        self.assertEqual(len(claimed), 0, "A missing/empty session token must reject the claim.")
        claimed2 = self.env['kds.print.job'].with_user(user).claim_direct_auto_jobs(
            session.id, '', 'device-X', limit=1)
        self.assertEqual(len(claimed2), 0)

    def test_v47_e_token_session_mismatch_rejected(self):
        """Item E: a token that IS a genuine, valid token - but for a
        DIFFERENT session than the one whose id was supplied - must be
        rejected. Proves the comparison is against THIS session's own
        token specifically, not merely "any valid-looking token"."""
        config_a = self._make_test_pos_config('V47 Mismatch Config A')
        config_b = self._make_test_pos_config('V47 Mismatch Config B')
        user_a = self._make_pos_only_user('v47_mismatch_user_a')
        user_b = self._make_pos_only_user('v47_mismatch_user_b')
        session_a = self.env['pos.session'].create({'config_id': config_a.id, 'user_id': user_a.id})
        session_b = self.env['pos.session'].create({'config_id': config_b.id, 'user_id': user_b.id})

        order = self._order_for(self.station_printer_only)
        self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)

        # Session B's own id, but Session A's own (genuinely valid,
        # just for the wrong session) token.
        claimed = self.env['kds.print.job'].with_user(user_b).claim_direct_auto_jobs(
            session_b.id, session_a.sudo().access_token, 'device-X', limit=1)
        self.assertEqual(len(claimed), 0, "Token from Session A must not authorize Session B's own id.")

    def test_v47_f_non_pos_user_with_correct_token_rejected(self):
        """Item F: even a fully correct session id/token pair must be
        rejected if the authenticated caller is not a legitimate POS
        user at all (point_of_sale.group_pos_user) - a valid
        credential in the hands of the wrong kind of account is still
        rejected."""
        config = self._make_test_pos_config('V47 Non-POS User Config')
        pos_user = self._make_pos_only_user('v47_nonpos_session_owner')
        session = self.env['pos.session'].create({'config_id': config.id, 'user_id': pos_user.id})
        order = self._order_for(self.station_printer_only)
        self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)

        non_pos_user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'v47 Non POS User', 'login': 'v47_non_pos_user',
            'email': 'v47_non_pos_user@example.com',
        })
        claimed = self.env['kds.print.job'].with_user(non_pos_user).claim_direct_auto_jobs(
            session.id, session.sudo().access_token, 'device-X', limit=1)
        self.assertEqual(len(claimed), 0, "A non-POS-user account must be rejected even with a correct token.")

    def test_v47_g_closed_session_cannot_claim(self):
        config = self._make_test_pos_config('V47 Closed Session Config')
        user = self._make_pos_only_user('v47_closed_session_user')
        session = self.env['pos.session'].create({'config_id': config.id, 'user_id': user.id})
        session.write({'state': 'closed'})
        order = self._order_for(self.station_printer_only)
        self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)

        claimed = self.env['kds.print.job'].with_user(user).claim_direct_auto_jobs(
            session.id, session.sudo().access_token, 'device-X', limit=1)
        self.assertEqual(len(claimed), 0, "A closed session must not be able to claim.")

    def test_v47_i_correct_session_token_device_success_result_printed(self):
        """Item I: full success path with the new token-based
        contract."""
        config = self._make_test_pos_config('V47 Success Result Config')
        user = self._make_pos_only_user('v47_success_result_user')
        session = self.env['pos.session'].create({'config_id': config.id, 'user_id': user.id})
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.env['kds.print.job'].with_user(user).claim_direct_auto_jobs(
            session.id, session.sudo().access_token, 'device-ok', limit=1)
        job.invalidate_recordset()

        job.with_user(user).report_pos_direct_auto_result(
            session.id, session.sudo().access_token, 'device-ok', True)
        job.invalidate_recordset()
        self.assertEqual(job.status, 'printed')

    def test_v47_j_correct_session_token_device_failure_result_failed(self):
        """Item J: same, with successful=False."""
        config = self._make_test_pos_config('V47 Failure Result Config')
        user = self._make_pos_only_user('v47_failure_result_user')
        session = self.env['pos.session'].create({'config_id': config.id, 'user_id': user.id})
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.env['kds.print.job'].with_user(user).claim_direct_auto_jobs(
            session.id, session.sudo().access_token, 'device-fail', limit=1)
        job.invalidate_recordset()

        job.with_user(user).report_pos_direct_auto_result(
            session.id, session.sudo().access_token, 'device-fail', False,
            error_code='NETWORK_ERROR', error_message='Timed out')
        job.invalidate_recordset()
        self.assertEqual(job.status, 'failed')
        self.assertEqual(job.error_code, 'NETWORK_ERROR')

    def test_v47_k_wrong_executor_rejected_on_report(self):
        config = self._make_test_pos_config('V47 Wrong Executor Config')
        user = self._make_pos_only_user('v47_wrong_executor_user')
        session = self.env['pos.session'].create({'config_id': config.id, 'user_id': user.id})
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.env['kds.print.job'].with_user(user).claim_direct_auto_jobs(
            session.id, session.sudo().access_token, 'device-real', limit=1)
        job.invalidate_recordset()

        with self.assertRaises(ValidationError):
            job.with_user(user).report_pos_direct_auto_result(
                session.id, session.sudo().access_token, 'device-fake', True)

    def test_v47_l_wrong_pos_session_rejected_on_report(self):
        """Item L: a DIFFERENT (but genuinely valid, correctly
        tokened) session than the one that actually claimed the job
        must be rejected on report - direct_executor_pos_session_id
        must match exactly."""
        config_claim = self._make_test_pos_config('V47 Wrong Session Claim Config')
        config_other = self._make_test_pos_config('V47 Wrong Session Other Config')
        user = self._make_pos_only_user('v47_wrong_session_user')
        session_claim = self.env['pos.session'].create({'config_id': config_claim.id, 'user_id': user.id})
        session_other = self.env['pos.session'].create({'config_id': config_other.id, 'user_id': user.id})

        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.env['kds.print.job'].with_user(user).claim_direct_auto_jobs(
            session_claim.id, session_claim.sudo().access_token, 'device-shared-device', limit=1)
        job.invalidate_recordset()

        with self.assertRaises(ValidationError):
            job.with_user(user).report_pos_direct_auto_result(
                session_other.id, session_other.sudo().access_token, 'device-shared-device', True)

    def test_v47_m_wrong_session_token_rejected_on_report(self):
        """Item M: the correct session id, but a wrong token, must be
        rejected on report even if everything else (config, executor)
        would otherwise match."""
        config = self._make_test_pos_config('V47 Wrong Report Token Config')
        user = self._make_pos_only_user('v47_wrong_report_token_user')
        session = self.env['pos.session'].create({'config_id': config.id, 'user_id': user.id})
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.env['kds.print.job'].with_user(user).claim_direct_auto_jobs(
            session.id, session.sudo().access_token, 'device-x', limit=1)
        job.invalidate_recordset()

        with self.assertRaises(ValidationError):
            job.with_user(user).report_pos_direct_auto_result(
                session.id, 'wrong-token-entirely', 'device-x', True)

    def test_v47_h_pos_only_user_shared_session_gets_full_payload_no_acl_error(self):
        """Item H: the shared-session scenario (item B) must also
        yield the complete serialized payload, with no AccessError -
        not merely a non-empty claim list."""
        config = self._make_test_pos_config('V47 Shared Payload Config')
        user_a = self._make_pos_only_user('v47_payload_user_a')
        user_b = self._make_pos_only_user('v47_payload_user_b')
        session = self.env['pos.session'].create({'config_id': config.id, 'user_id': user_a.id})
        order = self._order_for(self.station_printer_only)
        self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)

        claimed = self.env['kds.print.job'].with_user(user_b).claim_direct_auto_jobs(
            session.id, session.sudo().access_token, 'device-payload', limit=1)
        self.assertEqual(len(claimed), 1)
        payload = claimed[0]
        self.assertTrue(payload.get('job_id'))
        self.assertIn('order', payload)
        self.assertIn('lines', payload['order'])

    def test_v47_n_worker_uses_session_access_token(self):
        """Item N: static contract check - the worker must read and
        send this.pos.session.access_token (never invent a FlexSys
        token, never rely on session.user_id). Searches for an actual
        COMPARISON/usage of session.user_id, not merely its name
        appearing inside explanatory prose (a comment documenting that
        it is deliberately NOT used is expected and must not trip this
        guard)."""
        import os
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(module_dir, 'static', 'src', 'js', 'flexsys_pos_direct_print_worker.js')
        with open(path, encoding='utf-8') as f:
            content = f.read()
        self.assertIn('this.pos.session.access_token', content)
        code_only = '\n'.join(
            line for line in content.split('\n')
            if not line.strip().startswith('//')
        )
        self.assertNotIn('session.user_id', code_only)

    def test_v47_o_worker_does_not_persist_access_token_in_localstorage(self):
        """Item O: the pending-result marker persisted to localStorage
        must NEVER include the session access_token - only
        pos_session_id (an identifier, not a credential)."""
        import os
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(module_dir, 'static', 'src', 'js', 'flexsys_pos_direct_print_worker.js')
        with open(path, encoding='utf-8') as f:
            content = f.read()
        result_entry_block = content.split('const resultEntry = {')[1].split('};')[0]
        self.assertNotIn('access_token', result_entry_block)
        self.assertNotIn('session_access_token', content)

    def test_v47_p_reload_same_session_pending_result_retried_with_current_token(self):
        """Item P: static contract check - _flushPendingResults() must
        compare entry.pos_session_id against the CURRENT
        this.pos.session.id, and when they match, use the CURRENT
        in-memory this.pos.session.access_token to retry the report -
        never a stored token, never re-printing physically."""
        import os
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(module_dir, 'static', 'src', 'js', 'flexsys_pos_direct_print_worker.js')
        with open(path, encoding='utf-8') as f:
            content = f.read()
        flush_method = content.split('async _flushPendingResults()')[1].split('\n    async _claimAndPrintOne')[0]
        self.assertIn('entry.pos_session_id !== currentSessionId', flush_method)
        self.assertIn('currentSessionAccessToken', flush_method)
        self.assertIn('this.pos.session.access_token', flush_method)
        self.assertNotIn('flexsysPrintViaDirectEpos', flush_method,
                          "Result retry must never trigger another physical print attempt.")

    def test_v47_q_stale_marker_from_other_session_discarded_not_reported_not_blocking(self):
        """Item Q: static contract check - a marker whose own
        pos_session_id does not match the current session must be
        discarded (never reported with the current session's own
        token, never triggers a reprint) and must NOT set
        allFlushed=false - it must never permanently block the
        current session's own claims."""
        import os
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(module_dir, 'static', 'src', 'js', 'flexsys_pos_direct_print_worker.js')
        with open(path, encoding='utf-8') as f:
            content = f.read()
        flush_method = content.split('async _flushPendingResults()')[1].split('\n    async _claimAndPrintOne')[0]
        stale_branch = flush_method.split('if (entry.pos_session_id !== currentSessionId) {')[1].split('\n            }')[0]
        self.assertIn('clearPendingResult(entry.job_id)', stale_branch)
        self.assertIn('continue', stale_branch)
        self.assertNotIn('allFlushed = false', stale_branch)
        self.assertNotIn('report_pos_direct_auto_result', stale_branch)

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
        baseline (636 post-tests, 662 tests total).

        AUDIT FIX ("Version 45 - Odoo.sh Regression Corrections"),
        item 3: confirmed live - this test used to also assert a
        SECOND, permanently hardcoded number (683) for the current
        package's own static test count, which goes stale every time
        a legitimate test is added anywhere in this suite (exactly
        what happened between this test being written and this same
        round's own new fixture/test additions). That check is now
        computed the same way
        test_v44_release_status_test_count_matches_actual_count below
        does - the actual, current `def test_` count across every
        tests/*.py file, recalculated fresh on every run, never a
        second stale literal to maintain."""
        import glob
        import os
        import re
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(module_dir, 'RELEASE_STATUS.md'), encoding='utf-8') as f:
            content = f.read()
        self.assertIn('636 post-tests', content)
        self.assertIn('662 tests', content)
        self.assertNotIn('588 post-tests', content)
        self.assertNotIn('596 tests', content)

        actual_count = 0
        for path in glob.glob(os.path.join(module_dir, 'tests', '*.py')):
            with open(path, encoding='utf-8') as f:
                file_content = f.read()
            actual_count += len(re.findall(r'^    def test_', file_content, re.MULTILINE))
        self.assertIn('%d static test methods' % actual_count, content)

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

    # -----------------------------------------------------------------
    # AUDIT FIX ("Version 46 - Two Final Phase 3 Runtime Blockers")
    # -----------------------------------------------------------------

    def test_v46_direct_auto_claim_sql_uses_materialized_cte(self):
        """BLOCKER 1: static source check confirming
        claim_direct_auto_jobs() no longer uses the unsafe
        `UPDATE ... WHERE id IN (SELECT ... LIMIT ...)` shape live
        Odoo.sh proved broken for _claim_pending_jobs() - it must use
        the same WITH claimable AS MATERIALIZED (...) UPDATE ... FROM
        claimable fix."""
        import os
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(module_dir, 'models', 'kds_print_job.py'), encoding='utf-8') as f:
            content = f.read()
        claim_method = content.split('def claim_direct_auto_jobs(')[1].split('\n    def ')[0]
        # Strip full-line comments/docstring prose before the text
        # check - this method's own docstring deliberately mentions
        # the OLD unsafe pattern by name, as historical context
        # explaining the fix (wrapped in backticks) - not executable
        # code, and must never trip this guard (same principle already
        # proven for test_zz_no_agent_fallback_in_direct_auto_creation
        # above).
        code_only = '\n'.join(
            line for line in claim_method.split('\n')
            if not line.strip().startswith('#') and '`' not in line
        )
        self.assertIn('WITH claimable AS MATERIALIZED', code_only)
        self.assertIn('FROM claimable', code_only)
        self.assertIn('WHERE job.id = claimable.id', code_only)
        self.assertNotIn(
            'WHERE id IN (', code_only,
            "The old unsafe correlated-subquery shape (UPDATE ... WHERE id IN "
            "(SELECT ...)) must not remain anywhere in this method's executable code."
        )

    def test_v46_direct_auto_claim_limit_2_of_5_returns_exactly_1(self):
        """AUDIT FIX ("Version 50 - One Stale Test Contract Before
        Odoo.sh"): confirmed - this test's own prior assertions
        (len(claimed) == 2, 2 dispatched, 3 pending for a limit=2
        request) directly contradicted the CURRENT, approved server
        contract established in Version 48/49: the Direct Auto POS
        Worker is strictly sequential and the backend always enforces
        safe_limit=1 regardless of the caller-supplied `limit` -
        already proven separately by
        test_v48_1_claim_never_dispatches_more_than_one_job_regardless_of_requested_limit.
        Production safe_limit=1 itself is NOT changed here - only this
        test's own stale expectations are corrected to match it.

        Retained (renamed, not deleted) specifically to keep real
        MATERIALIZED CTE regression coverage for this exact scenario
        live Odoo.sh once proved broken for the Legacy Agent's own
        equivalent query (5 eligible jobs, a multi-job limit request,
        checking the query doesn't ignore its own LIMIT) - now
        asserting the CURRENT correct outcome: even with limit=2
        requested against 5 eligible jobs, exactly 1 payload/dispatch
        result, with the other 4 remaining pending."""
        jobs = self.env['kds.print.job']
        for _i in range(5):
            order = self._order_for(self.station_printer_only)
            jobs |= self.env['kds.print.job'].create_direct_auto_print_job(
                order.id, self.station_printer_only.id)
        self.assertEqual(len(jobs), 5)

        claimed = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, self.pos_session.sudo().access_token, 'device-A', limit=2)
        self.assertEqual(
            len(claimed), 1,
            "Server-enforced safe_limit=1 means a limit=2 request must still return exactly 1 payload."
        )

        jobs.invalidate_recordset()
        dispatched = jobs.filtered(lambda j: j.status == 'dispatched')
        pending = jobs.filtered(lambda j: j.status == 'pending')
        self.assertEqual(len(dispatched), 1, "Exactly 1 job must actually be dispatched.")
        self.assertEqual(len(pending), 4, "Exactly 4 jobs must remain pending.")

    def test_v46_direct_auto_claim_limit_1_of_5_returns_exactly_1(self):
        jobs = self.env['kds.print.job']
        for _i in range(5):
            order = self._order_for(self.station_printer_only)
            jobs |= self.env['kds.print.job'].create_direct_auto_print_job(
                order.id, self.station_printer_only.id)

        claimed = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, self.pos_session.sudo().access_token, 'device-A', limit=1)
        self.assertEqual(len(claimed), 1)

        jobs.invalidate_recordset()
        self.assertEqual(len(jobs.filtered(lambda j: j.status == 'dispatched')), 1)
        self.assertEqual(len(jobs.filtered(lambda j: j.status == 'pending')), 4)

    def test_v46_pos_only_user_can_claim_successfully(self):
        """MANDATORY SUCCESS-PATH TEST 1: a legitimate, plain POS-only
        user (point_of_sale.group_pos_user ONLY - deliberately NOT
        given any FlexSys KDS group, so this test cannot hide the real
        production ACL problem behind an over-privileged test user)
        with their own active session must be able to claim and
        receive the complete serialized payload with NO AccessError -
        the atomic SQL claim succeeding but the payload-building read
        then raising AccessError under the calling user's own bare ACL
        is exactly the runtime blocker this fix resolves."""
        pos_user = self._make_pos_only_user('v46_success_claim_user')
        # AUDIT FIX ("Version 47 - Odoo 19 POS Session Identity
        # Correction"), item 5: confirmed - Odoo 19 rejects more than
        # one non-closed/non-rescue session for the same POS config
        # (self.pos_config already has cls.pos_session open on it from
        # setUpClass). A dedicated config per isolated test avoids
        # that fixture-level ERROR entirely.
        config = self._make_test_pos_config('V46 Success Claim Config')
        session = self.env['pos.session'].create({
            'config_id': config.id, 'user_id': pos_user.id,
        })
        order = self._order_for(self.station_printer_only)
        self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)

        # Genuinely acting as the plain POS user - no sudo, no KDS group.
        claimed = self.env['kds.print.job'].with_user(pos_user).claim_direct_auto_jobs(
            session.id, session.sudo().access_token, 'device-success', limit=1)
        self.assertEqual(len(claimed), 1)
        payload = claimed[0]
        self.assertTrue(payload.get('job_id'))
        self.assertEqual(payload.get('printer_ip'), '192.168.1.70')
        self.assertIn('order', payload)
        self.assertIn('lines', payload['order'])

    def test_v46_pos_only_user_can_report_success_result(self):
        """MANDATORY SUCCESS-PATH TEST 2: the same plain POS-only
        user/device, after a genuine claim, must be able to report a
        successful result with NO AccessError, and the job must
        actually become 'printed'."""
        pos_user = self._make_pos_only_user('v46_success_report_user')
        config = self._make_test_pos_config('V46 Success Report Config')
        session = self.env['pos.session'].create({
            'config_id': config.id, 'user_id': pos_user.id,
        })
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.env['kds.print.job'].with_user(pos_user).claim_direct_auto_jobs(
            session.id, session.sudo().access_token, 'device-success-2', limit=1)
        job.invalidate_recordset()

        job.with_user(pos_user).report_pos_direct_auto_result(session.id, session.sudo().access_token, 'device-success-2', True)
        job.invalidate_recordset()
        self.assertEqual(job.status, 'printed')

    def test_v46_pos_only_user_can_report_failure_result(self):
        """MANDATORY SUCCESS-PATH TEST 3: same flow with
        successful=False - the job must become 'failed' correctly,
        still with no AccessError for the plain POS user."""
        pos_user = self._make_pos_only_user('v46_failure_report_user')
        config = self._make_test_pos_config('V46 Failure Report Config')
        session = self.env['pos.session'].create({
            'config_id': config.id, 'user_id': pos_user.id,
        })
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.env['kds.print.job'].with_user(pos_user).claim_direct_auto_jobs(
            session.id, session.sudo().access_token, 'device-failure', limit=1)
        job.invalidate_recordset()

        job.with_user(pos_user).report_pos_direct_auto_result(
            session.id, session.sudo().access_token, 'device-failure', False,
            error_code='LNA_DENIED', error_message='Denied')
        job.invalidate_recordset()
        self.assertEqual(job.status, 'failed')
        self.assertEqual(job.error_code, 'LNA_DENIED')

    def test_v46_success_path_tests_use_only_pos_group_no_kds_group(self):
        """Explicit requirement: the mandatory success-path tests must
        use ONLY point_of_sale.group_pos_user - never granting the
        test user any FlexSys KDS group, which would hide the real
        production ACL problem behind an artificially-privileged test
        fixture. Static check on _make_pos_only_user() itself."""
        import os
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(module_dir, 'tests', 'test_phase3_pos_direct_auto_print.py'),
                  encoding='utf-8') as f:
            content = f.read()
        helper_body = content.split('def _make_pos_only_user(')[1].split('\n    def ')[0]
        self.assertIn('point_of_sale.group_pos_user', helper_body)
        self.assertNotIn('flexsys_kds.group_kds', helper_body)

    def test_v46_no_broad_kds_acl_granted_to_pos_users(self):
        """Explicit requirement: the fix must NOT grant
        point_of_sale.group_pos_user any general access to
        kds.print.job/kds.order/kds.order.line - the narrow RPC
        methods (with their own internal sudo(), scoped to
        already-authorized ids only) remain the real security
        boundary, not a broadened ACL."""
        import csv
        import os
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        csv_path = os.path.join(module_dir, 'security', 'ir.model.access.csv')
        with open(csv_path, encoding='utf-8', newline='') as f:
            rows = list(csv.DictReader(f))
        kds_models = {'model_kds_print_job', 'model_kds_order', 'model_kds_order_line'}
        offending = [
            row for row in rows
            if row.get('model_id:id') in kds_models
            and 'point_of_sale.group_pos_user' in (row.get('group_id:id') or '')
        ]
        self.assertEqual(
            offending, [],
            "point_of_sale.group_pos_user must not have any direct ACL grant on "
            "kds.print.job/kds.order/kds.order.line."
        )

    # -----------------------------------------------------------------
    # AUDIT FIX ("Version 48 - Final Security/Claim Corrections
    # Before Odoo.sh")
    # -----------------------------------------------------------------

    def test_v48_1_claim_never_dispatches_more_than_one_job_regardless_of_requested_limit(self):
        """Item 1: the POS worker only ever consumes claimed[0] - a
        caller requesting limit=2 or limit=5 must still only ever get
        exactly ONE payload/dispatched job, with the remaining 4
        staying pending. The server, not the caller-supplied limit,
        enforces this."""
        jobs = self.env['kds.print.job']
        for _i in range(5):
            order = self._order_for(self.station_printer_only)
            jobs |= self.env['kds.print.job'].create_direct_auto_print_job(
                order.id, self.station_printer_only.id)
        self.assertEqual(len(jobs), 5)

        for requested_limit in (2, 5):
            with self.subTest(requested_limit=requested_limit):
                claimed = self.env['kds.print.job'].claim_direct_auto_jobs(
                    self.pos_session.id, self.pos_session.sudo().access_token,
                    'device-limit-%d' % requested_limit, limit=requested_limit)
                self.assertEqual(
                    len(claimed), 1,
                    "Requesting limit=%d must still only ever claim exactly 1 job." % requested_limit
                )

        jobs.invalidate_recordset()
        dispatched = jobs.filtered(lambda j: j.status == 'dispatched')
        pending = jobs.filtered(lambda j: j.status == 'pending')
        self.assertEqual(len(dispatched), 2, "Exactly 2 total claims (one per loop iteration) were made.")
        self.assertEqual(len(pending), 3)

    def test_v48_2_rescue_session_cannot_claim(self):
        """Item 2: a rescue/recovery pos.session is not a real browser
        print executor and must never claim a Direct Auto job, even
        with a correct token from a genuine POS user."""
        config = self._make_test_pos_config('V48 Rescue Config')
        user = self._make_pos_only_user('v48_rescue_user')
        session = self.env['pos.session'].create({
            'config_id': config.id, 'user_id': user.id, 'rescue': True,
        })
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)

        claimed = self.env['kds.print.job'].with_user(user).claim_direct_auto_jobs(
            session.id, session.sudo().access_token, 'device-rescue', limit=1)
        self.assertEqual(len(claimed), 0, "A rescue session must never be able to claim.")
        job.invalidate_recordset()
        self.assertEqual(job.status, 'pending')
        self.assertFalse(job.direct_executor_pos_session_id)

    def test_v48_2b_rescue_session_cannot_report_result(self):
        """Item 2: rescue is also rejected on the report path,
        independent of the claim path's own rejection."""
        config = self._make_test_pos_config('V48 Rescue Report Config')
        user = self._make_pos_only_user('v48_rescue_report_user')
        session = self.env['pos.session'].create({'config_id': config.id, 'user_id': user.id})
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.env['kds.print.job'].with_user(user).claim_direct_auto_jobs(
            session.id, session.sudo().access_token, 'device-rescue2', limit=1)
        job.invalidate_recordset()

        # The session becomes a rescue session AFTER the claim (a
        # legitimate later Odoo 19 state transition) - report must
        # reject it regardless of when the transition happened.
        session.sudo().write({'rescue': True})
        with self.assertRaises(ValidationError):
            job.with_user(user).report_pos_direct_auto_result(
                session.id, session.sudo().access_token, 'device-rescue2', True)

    def test_v48_3a_caller_not_allowed_in_session_company_cannot_claim(self):
        """Item 3A: an authenticated caller only allowed in Company A
        must not be able to claim a job through an active session
        belonging to Company B, even with that session's own correct
        token - sudo() on the session/station lookups must never let
        a valid token bypass Odoo's own multi-company boundary.

        AUDIT FIX ("Version 49 - One Test Fixture Correction Only"):
        the Company B owner fixture is now genuinely granted Company
        B access (see _grant_company_access() above), and the order
        itself is genuinely created under Company B
        (company=self.company_b) - the prior version of this fixture
        left user_b_owner with no real Company B access at all and
        built the order in the default company, so this test's own
        setup didn't actually represent the scenario it claimed to."""
        station_b = self.env['kds.station'].create({
            'name': 'V48 Station B', 'code': 'V48STATIONB', 'target_prep_time': 10,
            'operating_mode': 'printer_only', 'company_id': self.company_b.id,
            'flexsys_printing_method': 'direct_network', 'flexsys_printer_ip': '10.0.0.90',
        })
        config_b = self._make_test_pos_config('V48 Company B Config', company_id=self.company_b.id)
        user_b_owner = self._grant_company_access(
            self._make_pos_only_user('v48_company_b_owner'), self.company_b)
        session_b = self.env['pos.session'].create({'config_id': config_b.id, 'user_id': user_b_owner.id})

        # caller_a is only allowed in the default company (self.company)
        # - never explicitly granted company_b.
        caller_a = self._make_pos_only_user('v48_caller_only_company_a')

        order = self._order_for(station_b, company=self.company_b)
        self.env['kds.print.job'].create_direct_auto_print_job(order.id, station_b.id)

        claimed = self.env['kds.print.job'].with_user(caller_a).claim_direct_auto_jobs(
            session_b.id, session_b.sudo().access_token, 'device-cross-company', limit=1)
        self.assertEqual(
            len(claimed), 0,
            "A caller not allowed in Session B's own company must not be able to claim through it."
        )

    def test_v48_3b_caller_not_allowed_in_session_company_cannot_report(self):
        """Item 3B: same cross-company rejection on the report path.

        AUDIT FIX ("Version 49 - One Test Fixture Correction Only"):
        confirmed - the prior version of this test could pass for the
        WRONG reason. user_b_owner had no genuine Company B access, so
        the "legitimate Company B owner" claim on line ~1560 was
        itself silently rejected by the very same Version 48 company
        check this test exists to verify - job.direct_executor_pos_
        session_id stayed False, and the LATER report attempt by
        caller_a then failed for an unrelated reason (the job was
        simply never claimed by anyone at all), not because of the
        cross-company boundary this test claims to prove. Fixed: (1)
        user_b_owner is genuinely granted Company B access and the
        order is genuinely built under Company B: (2) the legitimate
        claim is now explicitly asserted to succeed BEFORE the
        cross-company report attempt is ever made, so this test can
        only pass by actually reaching and exercising the real
        contract."""
        station_b = self.env['kds.station'].create({
            'name': 'V48 Station B Report', 'code': 'V48STATIONBREPORT', 'target_prep_time': 10,
            'operating_mode': 'printer_only', 'company_id': self.company_b.id,
            'flexsys_printing_method': 'direct_network', 'flexsys_printer_ip': '10.0.0.91',
        })
        config_b = self._make_test_pos_config('V48 Company B Report Config', company_id=self.company_b.id)
        user_b_owner = self._grant_company_access(
            self._make_pos_only_user('v48_company_b_report_owner'), self.company_b)
        session_b = self.env['pos.session'].create({'config_id': config_b.id, 'user_id': user_b_owner.id})

        order = self._order_for(station_b, company=self.company_b)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, station_b.id)

        # The legitimate Company B owner claims it first - explicitly
        # asserted to actually succeed before continuing, so this test
        # cannot silently pass without ever reaching the real scenario.
        claimed = self.env['kds.print.job'].with_user(user_b_owner).claim_direct_auto_jobs(
            session_b.id, session_b.sudo().access_token, 'device-cross-report', limit=1)
        self.assertEqual(len(claimed), 1, "The legitimate Company B owner's own claim must actually succeed.")
        job.invalidate_recordset()
        self.assertEqual(job.direct_executor_pos_session_id, session_b)
        self.assertEqual(job.status, 'dispatched')

        caller_a = self._make_pos_only_user('v48_report_caller_only_company_a')
        with self.assertRaises(ValidationError):
            job.with_user(caller_a).report_pos_direct_auto_result(
                session_b.id, session_b.sudo().access_token, 'device-cross-report', True)

    def test_v48_3c_allowed_company_success_path_still_passes(self):
        """Item 3C: the existing, allowed-company success path must
        keep working exactly as before - this new company check must
        not accidentally reject legitimate same-company claims."""
        config = self._make_test_pos_config('V48 Allowed Company Config')
        user = self._make_pos_only_user('v48_allowed_company_user')
        session = self.env['pos.session'].create({'config_id': config.id, 'user_id': user.id})
        order = self._order_for(self.station_printer_only)
        self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)

        claimed = self.env['kds.print.job'].with_user(user).claim_direct_auto_jobs(
            session.id, session.sudo().access_token, 'device-allowed', limit=1)
        self.assertEqual(len(claimed), 1, "A same-company, fully valid claim must still succeed.")

    def test_v48_4_empty_executor_id_rejected_on_claim(self):
        """Item 4: an empty/falsy executor_id must be rejected outright
        by the claim, not merely accepted as "no device identity"."""
        config = self._make_test_pos_config('V48 Empty Executor Config')
        user = self._make_pos_only_user('v48_empty_executor_user')
        session = self.env['pos.session'].create({'config_id': config.id, 'user_id': user.id})
        order = self._order_for(self.station_printer_only)
        self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)

        for empty_value in (False, '', None):
            with self.subTest(empty_value=empty_value):
                claimed = self.env['kds.print.job'].with_user(user).claim_direct_auto_jobs(
                    session.id, session.sudo().access_token, empty_value, limit=1)
                self.assertEqual(len(claimed), 0, "An empty executor_id must reject the claim.")

    def test_v48_4b_empty_executor_id_rejected_on_report(self):
        config = self._make_test_pos_config('V48 Empty Executor Report Config')
        user = self._make_pos_only_user('v48_empty_executor_report_user')
        session = self.env['pos.session'].create({'config_id': config.id, 'user_id': user.id})
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.env['kds.print.job'].with_user(user).claim_direct_auto_jobs(
            session.id, session.sudo().access_token, 'device-real-report', limit=1)
        job.invalidate_recordset()

        with self.assertRaises(ValidationError):
            job.with_user(user).report_pos_direct_auto_result(
                session.id, session.sudo().access_token, False, True)

    def test_v48_direct_auto_claim_sql_uses_hardcoded_safe_limit(self):
        """Static contract check: the actual SQL execution must use a
        hardcoded safe_limit, never the caller-supplied `limit`
        parameter directly."""
        import os
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(module_dir, 'models', 'kds_print_job.py'), encoding='utf-8') as f:
            content = f.read()
        claim_method = content.split('def claim_direct_auto_jobs(')[1].split('\n    def ')[0]
        self.assertIn('safe_limit = 1', claim_method)
        self.assertIn("'limit': safe_limit,", claim_method)
        self.assertNotIn("'limit': limit,", claim_method)
