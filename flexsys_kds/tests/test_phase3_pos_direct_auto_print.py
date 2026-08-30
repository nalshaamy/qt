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

COMMERCIAL TEST SUITE: overlapping tests covering the same current
behavior have been merged into single authoritative tests. See
docs/TEST_HISTORY.md for a short map of which historical issue each
authoritative test now covers.
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
        """`company` is optional and defaults to None (which
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
        """A plain POS-user fixture, using the SAME field-name
        auto-detection FlexSysKdsTestCommon._make_kds_user() already
        established as the confirmed-correct fix for this Odoo 19
        build's own unstable res.users<->res.groups field name
        (group_ids vs groups_id). Not reusing _make_kds_user() itself
        since that one assigns a FlexSys KDS administrative group plus
        optional kds_station_ids - genuinely different from a plain
        POS cashier with no KDS permissions at all, which is the
        actual scenario these tests need."""
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
        """A plain _make_pos_only_user() grants no company access
        beyond the default (self.company) - explicitly granting a
        user genuine access to a SECOND company (company_ids includes
        it, company_id switched to it as their own current/default
        company) is required to build a genuinely legitimate "Company
        B owner" fixture. Without this, self.env.companies for that
        user never actually includes company_b, and the production
        company-isolation check (`config.company_id not in
        self.env.companies`) would incorrectly reject even the
        LEGITIMATE Company B claim a cross-company test needs to first
        prove succeeds, before it can then prove the cross-company
        rejection for a genuinely different, Company-A-only caller."""
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
    # I. Report result - ownership boundaries + idempotency
    # -----------------------------------------------------------------

    def test_i2_wrong_pos_config_cannot_report_result(self):
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, self.pos_session.sudo().access_token, 'device-A', limit=1)
        job.invalidate_recordset()
        other_config = self._make_test_pos_config('Other Config For I2')
        other_session = self.env['pos.session'].create({'config_id': other_config.id, 'user_id': self.env.uid})
        with self.assertRaises(ValidationError):
            job.report_pos_direct_auto_result(other_session.id, other_session.sudo().access_token, 'device-A', True)

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

    def test_expired_pending_job_cannot_be_claimed_and_cron_marks_no_executor(self):
        """claim_deadline is enforced INSIDE the same atomic claim SQL
        WHERE clause, not only by the cron. Full sequence: an expired
        pending job (1) must never be
        claimable by claim_direct_auto_jobs() itself, deliberately
        checked BEFORE the cron ever runs, remaining untouched
        ('pending', deadline still in the past); (2) once the cron
        does run, it - and only it - actually transitions the job to
        Failed/NO_EXECUTOR. Without the SQL-level check, a job whose
        120-second claim deadline had already expired could still be
        claimed and physically printed in the window before the cron
        got around to failing it - a stale ticket printing hours later
        just because a POS browser happened to reconnect first."""
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
        self.assertTrue(job.failed_at)

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
    # Structural sanity (delivery checklist items)
    # -----------------------------------------------------------------

    def test_zz_no_duplicate_source_field_definition(self):
        import os
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(module_dir, 'models', 'kds_print_job.py'), encoding='utf-8') as f:
            content = f.read()
        self.assertEqual(content.count('source = fields.Selection(['), 1)

    def test_zz_no_agent_fallback_in_direct_auto_creation(self):
        """The BEHAVIORAL assertion is the primary check: creates a
        real Direct Auto job through the actual
        create_direct_auto_print_job() path and confirms its own
        concrete field values (transport, source, printer_id,
        printer_target) directly. The source-text check (with Python
        comments stripped first, so a historical-context comment can
        never trip it) is kept as a secondary, complementary guard."""
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

    def test_direct_auto_claim_rpc_is_model_level(self):
        """Without @api.model, Odoo's own call_kw treats args[0]
        (pos_session_id in the real POS RPC call shape) as record ids
        to browse() and strips it before calling the method - silently
        shifting every subsequent argument. A plain Python ORM test
        calling claim_direct_auto_jobs(session_id, executor_id)
        directly cannot catch this at all (it bypasses call_kw
        entirely) - this is a static source-contract check
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

    def test_direct_auto_result_rpc_is_record_level(self):
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

    def test_switching_station_to_kds_only_blocks_pending_claim(self):
        """A job created while Auto Print was enabled must NOT remain
        claimable once the station's own configuration has since
        changed to no longer allow it - re-validated at CLAIM time,
        not only trusted from job-creation time."""
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.assertTrue(job)
        # Configuration changes AFTER creation, BEFORE claim.
        self.station_printer_only.write({'operating_mode': 'kds_only'})
        claimed = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, self.pos_session.sudo().access_token, 'device-A', limit=1)
        self.assertEqual(len(claimed), 0, "A job must not be claimable once its station switched to KDS Only.")

    def test_disabling_auto_print_blocks_pending_claim(self):
        order = self._order_for(self.station_kds_printer_auto)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_kds_printer_auto.id)
        self.assertTrue(job)
        self.station_kds_printer_auto.write({'auto_print': False})
        claimed = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, self.pos_session.sudo().access_token, 'device-A', limit=1)
        self.assertEqual(len(claimed), 0, "A job must not be claimable once Auto Print was disabled.")

    def test_removing_printer_ip_blocks_pending_claim(self):
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.assertTrue(job)
        self.station_printer_only.write({'flexsys_printer_ip': False})
        claimed = self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, self.pos_session.sudo().access_token, 'device-A', limit=1)
        self.assertEqual(len(claimed), 0, "A job must not be claimable once the Printer IP was removed.")

    # -----------------------------------------------------------------
    # POS Direct Auto Print - session identity contract (Odoo 19: the
    # SAME pos.session can genuinely be used by a different
    # authenticated user than whoever originally opened it - session
    # identity is proven with the session's own standard access_token,
    # never session.user_id). See docs/TEST_HISTORY.md.
    # -----------------------------------------------------------------

    def test_pos_only_user_claims_direct_auto_job_and_receives_payload(self):
        """Authoritative POS-only Direct Auto claim success contract.

        A plain POS-only user - point_of_sale.group_pos_user ONLY,
        deliberately holding NO FlexSys KDS group at all, so this test
        cannot hide a real production ACL problem behind an
        over-privileged fixture - with a genuinely valid session/
        token/station/config/company claims exactly one Direct Auto
        job, receives the complete serialized payload with no
        AccessError, and the exact session/config/executor are
        recorded as the job's own claiming identity."""
        pos_user = self._make_pos_only_user('pos_only_claim_user')
        self.assertTrue(pos_user.has_group('point_of_sale.group_pos_user'))
        kds_groups = (
            self.group_operator | self.group_supervisor
            | self.group_branch_manager | self.group_administrator
        )
        self.assertFalse(
            pos_user.all_group_ids & kds_groups,
            "A POS-only user must not belong to any FlexSys KDS group."
        )

        config = self._make_test_pos_config('POS Only Claim Config')
        session = self.env['pos.session'].create({'config_id': config.id, 'user_id': pos_user.id})
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)

        # Genuinely acting as the plain POS user - no sudo, no KDS group.
        claimed = self.env['kds.print.job'].with_user(pos_user).claim_direct_auto_jobs(
            session.id, session.sudo().access_token, 'device-claim-payload', limit=1)
        self.assertEqual(len(claimed), 1, "Exactly one job must be claimed.")
        payload = claimed[0]
        self.assertEqual(payload['job_id'], job.id)
        self.assertTrue(payload.get('job_id'))
        self.assertEqual(payload.get('printer_ip'), '192.168.1.70')
        self.assertIn('order', payload)
        self.assertIn('lines', payload['order'])

        job.invalidate_recordset()
        self.assertEqual(job.status, 'dispatched')
        self.assertEqual(job.direct_executor_id, 'device-claim-payload')
        self.assertEqual(job.direct_executor_pos_config_id, config)
        self.assertEqual(job.direct_executor_pos_session_id, session)
        self.assertTrue(job.direct_claimed_at)
        self.assertTrue(job.dispatch_deadline)
        self.assertFalse(job.claim_deadline, "claim_deadline must be cleared once claimed.")

    def test_pos_only_user_reports_success_and_job_becomes_printed(self):
        """Authoritative success-report contract: starts from a
        genuine claim, then reports with the correct session/token/
        device - job must become 'printed'."""
        pos_user = self._make_pos_only_user('pos_only_success_report_user')
        config = self._make_test_pos_config('POS Only Success Report Config')
        session = self.env['pos.session'].create({'config_id': config.id, 'user_id': pos_user.id})
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        claimed = self.env['kds.print.job'].with_user(pos_user).claim_direct_auto_jobs(
            session.id, session.sudo().access_token, 'device-success', limit=1)
        self.assertEqual(len(claimed), 1, "The preliminary claim must actually succeed.")
        job.invalidate_recordset()

        job.with_user(pos_user).report_pos_direct_auto_result(
            session.id, session.sudo().access_token, 'device-success', True)
        job.invalidate_recordset()
        self.assertEqual(job.status, 'printed')

    def test_pos_only_user_reports_failure_and_job_becomes_failed(self):
        """Authoritative failure-report contract: a failed physical
        print result must transition the job to 'failed' with the
        error details recorded."""
        pos_user = self._make_pos_only_user('pos_only_failure_report_user')
        config = self._make_test_pos_config('POS Only Failure Report Config')
        session = self.env['pos.session'].create({'config_id': config.id, 'user_id': pos_user.id})
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        claimed = self.env['kds.print.job'].with_user(pos_user).claim_direct_auto_jobs(
            session.id, session.sudo().access_token, 'device-failure', limit=1)
        self.assertEqual(len(claimed), 1)
        job.invalidate_recordset()

        job.with_user(pos_user).report_pos_direct_auto_result(
            session.id, session.sudo().access_token, 'device-failure', False,
            error_code='LNA_DENIED', error_message='Denied')
        job.invalidate_recordset()
        self.assertEqual(job.status, 'failed')
        self.assertTrue(job.failed_at)
        self.assertEqual(job.error_code, 'LNA_DENIED')
        self.assertEqual(job.error, 'Denied')

    def test_wrong_executor_cannot_report_direct_auto_result(self):
        """A device different from the one that actually claimed the
        job must be rejected on report - direct_executor_id must
        match exactly."""
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.env['kds.print.job'].claim_direct_auto_jobs(self.pos_session.id, self.pos_session.sudo().access_token, 'device-real', limit=1)
        job.invalidate_recordset()
        with self.assertRaises(ValidationError):
            job.report_pos_direct_auto_result(self.pos_session.id, self.pos_session.sudo().access_token, 'device-fake', True)

    def test_direct_auto_claim_is_server_limited_to_one_job(self):
        """The POS worker only ever consumes claimed[0], so the server
        - not the caller-supplied `limit` - must always enforce
        exactly one claim per call, regardless of what limit is
        requested (this is also the live regression scenario for the
        atomic MATERIALIZED CTE claim SQL: confirming the query never
        ignores its own effective LIMIT).

        Uses one fixed five-job set across sequential claim requests
        to avoid cross-case database contamination: limit=1, then
        limit=2, then limit=5 in sequence against that SAME set,
        tracking cumulative dispatched/pending counts and collecting
        every returned job_id to confirm they all belong to the
        original 5 and no id is ever returned twice - proving
        safe_limit=1, the MATERIALIZED CTE's own correct behavior, and
        that an already-dispatched job is never re-claimed, all in one
        coherent scenario."""
        jobs = self.env['kds.print.job']
        for _i in range(5):
            order = self._order_for(self.station_printer_only)
            jobs |= self.env['kds.print.job'].create_direct_auto_print_job(
                order.id, self.station_printer_only.id)
        self.assertEqual(len(jobs), 5)

        seen_job_ids = set()
        expected_dispatched_after = {1: 1, 2: 2, 5: 3}
        expected_pending_after = {1: 4, 2: 3, 5: 2}

        for requested_limit in (1, 2, 5):
            claimed = self.env['kds.print.job'].claim_direct_auto_jobs(
                self.pos_session.id, self.pos_session.sudo().access_token,
                'device-limit-%d' % requested_limit, limit=requested_limit)
            self.assertEqual(
                len(claimed), 1,
                "Requesting limit=%d must still only ever claim exactly 1 job." % requested_limit
            )
            claimed_job_id = claimed[0]['job_id']
            self.assertIn(claimed_job_id, jobs.ids, "The claimed job must be one of the original 5.")
            self.assertNotIn(claimed_job_id, seen_job_ids, "An already-dispatched job must never be re-claimed.")
            seen_job_ids.add(claimed_job_id)

            jobs.invalidate_recordset()
            dispatched = jobs.filtered(lambda j: j.status == 'dispatched')
            pending = jobs.filtered(lambda j: j.status == 'pending')
            self.assertEqual(
                len(dispatched), expected_dispatched_after[requested_limit],
                "Cumulative dispatched count is wrong after limit=%d." % requested_limit
            )
            self.assertEqual(
                len(pending), expected_pending_after[requested_limit],
                "Cumulative pending count is wrong after limit=%d." % requested_limit
            )

        self.assertEqual(len(seen_job_ids), 3, "Exactly 3 distinct jobs must have been claimed in total.")

    def test_printer_only_auto_print_is_readonly_in_station_form(self):
        """Printer Only must show auto_print visible but readonly
        (locked at the backend-enforced True) - KDS Only stays hidden,
        KDS+Printer stays freely editable, both unchanged."""
        import os
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(module_dir, 'views', 'kds_station_views.xml'), encoding='utf-8') as f:
            content = f.read()
        self.assertIn('invisible="operating_mode == \'kds_only\'"', content)
        self.assertIn('readonly="operating_mode == \'printer_only\'"', content)

    def test_shared_pos_session_can_be_used_by_another_valid_pos_user(self):
        """The core Odoo 19 behavior FlexSys must correctly support -
        Session X opened by User A, authenticated User B (also a valid
        POS user) supplies Session X's own id and its correct
        access_token - claim must SUCCEED. session.user_id == env.user
        would have wrongly rejected this legitimate scenario."""
        config_x = self._make_test_pos_config('Shared Session Config')
        user_a = self._make_pos_only_user('shared_session_user_a')
        user_b = self._make_pos_only_user('shared_session_user_b')
        session_x = self.env['pos.session'].create({'config_id': config_x.id, 'user_id': user_a.id})

        order = self._order_for(self.station_printer_only)
        self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)

        # User B, genuinely acting as themselves (no sudo), supplies
        # Session X's own real id/token even though User A opened it.
        claimed = self.env['kds.print.job'].with_user(user_b).claim_direct_auto_jobs(
            session_x.id, session_x.sudo().access_token, 'device-shared', limit=1)
        self.assertEqual(len(claimed), 1, "A different authenticated POS user sharing the same "
                                           "session with its correct token must succeed.")

    def test_wrong_pos_session_token_is_rejected(self):
        config = self._make_test_pos_config('Wrong Token Config')
        user = self._make_pos_only_user('wrong_token_user')
        session = self.env['pos.session'].create({'config_id': config.id, 'user_id': user.id})
        order = self._order_for(self.station_printer_only)
        self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)

        claimed = self.env['kds.print.job'].with_user(user).claim_direct_auto_jobs(
            session.id, 'totally-wrong-token', 'device-X', limit=1)
        self.assertEqual(len(claimed), 0, "A wrong session token must reject the claim.")

    def test_missing_pos_session_token_is_rejected(self):
        config = self._make_test_pos_config('Missing Token Config')
        user = self._make_pos_only_user('missing_token_user')
        session = self.env['pos.session'].create({'config_id': config.id, 'user_id': user.id})
        order = self._order_for(self.station_printer_only)
        self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)

        claimed = self.env['kds.print.job'].with_user(user).claim_direct_auto_jobs(
            session.id, False, 'device-X', limit=1)
        self.assertEqual(len(claimed), 0, "A missing/empty session token must reject the claim.")
        claimed2 = self.env['kds.print.job'].with_user(user).claim_direct_auto_jobs(
            session.id, '', 'device-X', limit=1)
        self.assertEqual(len(claimed2), 0)

    def test_pos_session_token_mismatch_is_rejected(self):
        """A token that IS a genuine, valid token - but for a
        DIFFERENT session than the one whose id was supplied - must be
        rejected. Proves the comparison is against THIS session's own
        token specifically, not merely "any valid-looking token"."""
        config_a = self._make_test_pos_config('Mismatch Config A')
        config_b = self._make_test_pos_config('Mismatch Config B')
        user_a = self._make_pos_only_user('mismatch_user_a')
        user_b = self._make_pos_only_user('mismatch_user_b')
        session_a = self.env['pos.session'].create({'config_id': config_a.id, 'user_id': user_a.id})
        session_b = self.env['pos.session'].create({'config_id': config_b.id, 'user_id': user_b.id})

        order = self._order_for(self.station_printer_only)
        self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)

        # Session B's own id, but Session A's own (genuinely valid,
        # just for the wrong session) token.
        claimed = self.env['kds.print.job'].with_user(user_b).claim_direct_auto_jobs(
            session_b.id, session_a.sudo().access_token, 'device-X', limit=1)
        self.assertEqual(len(claimed), 0, "Token from Session A must not authorize Session B's own id.")

    def test_non_pos_user_cannot_claim_even_with_correct_token(self):
        """Even a fully correct session id/token pair must be rejected
        if the authenticated caller is not a legitimate POS user at
        all (point_of_sale.group_pos_user) - a valid credential in the
        hands of the wrong kind of account is still rejected."""
        config = self._make_test_pos_config('Non-POS User Config')
        pos_user = self._make_pos_only_user('nonpos_session_owner')
        session = self.env['pos.session'].create({'config_id': config.id, 'user_id': pos_user.id})
        order = self._order_for(self.station_printer_only)
        self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)

        non_pos_user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Non POS User', 'login': 'non_pos_user_v49',
            'email': 'non_pos_user_v49@example.com',
        })
        claimed = self.env['kds.print.job'].with_user(non_pos_user).claim_direct_auto_jobs(
            session.id, session.sudo().access_token, 'device-X', limit=1)
        self.assertEqual(len(claimed), 0, "A non-POS-user account must be rejected even with a correct token.")

    def test_closed_pos_session_cannot_claim_direct_auto_job(self):
        config = self._make_test_pos_config('Closed Session Config')
        user = self._make_pos_only_user('closed_session_user')
        session = self.env['pos.session'].create({'config_id': config.id, 'user_id': user.id})
        session.write({'state': 'closed'})
        order = self._order_for(self.station_printer_only)
        self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)

        claimed = self.env['kds.print.job'].with_user(user).claim_direct_auto_jobs(
            session.id, session.sudo().access_token, 'device-X', limit=1)
        self.assertEqual(len(claimed), 0, "A closed session must not be able to claim.")

    def test_wrong_pos_session_cannot_report_direct_auto_result(self):
        """A DIFFERENT (but genuinely valid, correctly tokened) session
        than the one that actually claimed the job must be rejected on
        report - direct_executor_pos_session_id must match exactly."""
        config_claim = self._make_test_pos_config('Wrong Session Claim Config')
        config_other = self._make_test_pos_config('Wrong Session Other Config')
        user = self._make_pos_only_user('wrong_session_user')
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

    def test_wrong_pos_session_token_cannot_report_direct_auto_result(self):
        """The correct session id, but a wrong token, must be rejected
        on report even if everything else (config, executor) would
        otherwise match."""
        config = self._make_test_pos_config('Wrong Report Token Config')
        user = self._make_pos_only_user('wrong_report_token_user')
        session = self.env['pos.session'].create({'config_id': config.id, 'user_id': user.id})
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.env['kds.print.job'].with_user(user).claim_direct_auto_jobs(
            session.id, session.sudo().access_token, 'device-x', limit=1)
        job.invalidate_recordset()

        with self.assertRaises(ValidationError):
            job.with_user(user).report_pos_direct_auto_result(
                session.id, 'wrong-token-entirely', 'device-x', True)

    def test_pos_worker_assets_and_setup_contract(self):
        """Authoritative POS worker asset-loading and setup-patch
        contract.

        (1) Asset load order: the shared ticket renderer and Epson
        adapter must load BEFORE the Direct Auto Print worker itself,
        and no Public Kiosk-only file may be loaded into POS assets.
        (2) Both the offline-send-warning patch and the worker's own
        setup() patch must genuinely be `async` and `await
        super.setup(...args)` - if either isn't, a later patch in the
        same PosStore chain resolves against a synchronous wrapper
        instead of the real Odoo setup(), defeating the worker's own
        readiness guarantee (this.config/this.device/this.session not
        actually ready yet when the worker starts). (3) The
        `_flexsysDirectPrintWorker` guard (preventing a duplicate
        worker on a repeated setup() call) must live INSIDE the
        setup() patch itself, with the worker's own construction and
        .start() call both inside that guard."""
        import ast
        import os
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # --- (1) Asset ordering. ---
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

        # --- (2) Async setup + await super, both ends of the chain. ---
        offline_warning_path = os.path.join(
            module_dir, 'static', 'src', 'js', 'flexsys_kds_offline_send_warning.js')
        with open(offline_warning_path, encoding='utf-8') as f:
            offline_warning_content = f.read()
        self.assertIn('async setup(...args)', offline_warning_content)
        self.assertIn('await super.setup(...args)', offline_warning_content)

        worker_path = os.path.join(module_dir, 'static', 'src', 'js', 'flexsys_pos_direct_print_worker.js')
        with open(worker_path, encoding='utf-8') as f:
            worker_content = f.read()
        self.assertIn('async setup(...args)', worker_content)
        self.assertIn('await super.setup(...args)', worker_content)

        # --- (3) Duplicate-worker guard at the setup() level. ---
        setup_method = worker_content.split('async setup(...args)')[1]
        self.assertIn('if (!this._flexsysDirectPrintWorker) {', setup_method)
        guard_body = setup_method.split('if (!this._flexsysDirectPrintWorker) {')[1].split('\n            }')[0]
        self.assertIn('new FlexSysPosDirectPrintWorker(this)', guard_body)
        self.assertIn('.start()', guard_body)

    def test_pos_worker_result_first_blocks_new_claim_until_acknowledged(self):
        """Authoritative result-first worker contract.

        (1) _flushPendingResults() must return a boolean actually
        checked by _runCycle() before proceeding to a new claim - an
        unacknowledged pending result from an EARLIER cycle must block
        a new claim at the START of a cycle. (2) _claimAndPrintOne()
        must not itself call this._runCycle() (a historical no-op,
        since the outer _runCycle() already had cycleInFlight=true) -
        _runCycle() must instead run a genuine sequential
        `while (await this._claimAndPrintOne())` loop. (3) A report
        RPC that fails DURING the current loop's own iteration (after
        a genuine physical print) must also stop further claims in the
        SAME cycle: `return true;` only on the success side of the
        report try/catch (after clearPendingResult), `return false;`
        on the catch side, with no shared/unconditional `return true;`
        floating after the try/catch block."""
        import os
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(module_dir, 'static', 'src', 'js', 'flexsys_pos_direct_print_worker.js')
        with open(path, encoding='utf-8') as f:
            content = f.read()

        # --- (1) allFlushed boolean genuinely checked by _runCycle(). ---
        flush_method = content.split('async _flushPendingResults()')[1].split('\n    async _claimAndPrintOne')[0]
        self.assertIn('let allFlushed = true', flush_method)
        self.assertIn('allFlushed = false', flush_method)
        self.assertIn('return allFlushed', flush_method)

        run_cycle = content.split('async _runCycle()')[1].split('\n    async _flushPendingResults')[0]
        self.assertIn('const allFlushed = await this._flushPendingResults()', run_cycle)
        self.assertIn('if (!allFlushed) {', run_cycle)

        # --- (2) No recursive _runCycle() call; genuine sequential loop. ---
        claim_and_print_method = content.split('async _claimAndPrintOne()')[1].split('\n    /**')[0].split(
            '\n    async setup')[0]
        self.assertNotIn(
            'this._runCycle()', claim_and_print_method,
            "_claimAndPrintOne() must no longer call this._runCycle() itself - "
            "that call was a no-op due to cycleInFlight still being true in the caller."
        )
        self.assertIn('return true;', claim_and_print_method)
        self.assertIn('return false;', claim_and_print_method)
        self.assertIn('while (await this._claimAndPrintOne())', run_cycle)

        # --- (3) return true/false split correctly across the report try/catch. ---
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

        after_catch = claim_and_print_method.split(catch_side, 1)[1]
        tail_before_method_close = after_catch.split('}\n    }')[0]
        self.assertNotIn('return true;', tail_before_method_close)

    def test_pos_worker_uses_session_token_without_persisting_it(self):
        """Authoritative session-token usage contract: the worker
        must read and send this.pos.session.access_token (never
        invent a FlexSys token, never rely on session.user_id
        as executable logic), and the pending-result marker persisted
        to localStorage must NEVER include the token itself - only
        pos_session_id (an identifier, not a credential)."""
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
        self.assertNotIn(
            'session.user_id', code_only,
            "session.user_id must not appear as executable logic - a comment "
            "documenting that it is deliberately not used is fine."
        )

        result_entry_block = content.split('const resultEntry = {')[1].split('};')[0]
        self.assertNotIn('access_token', result_entry_block)
        self.assertNotIn('session_access_token', content)

    def test_pos_worker_pending_result_retry_and_stale_session_behavior(self):
        """Authoritative pending-result retry contract:
        _flushPendingResults() must compare entry.pos_session_id
        against the CURRENT this.pos.session.id: when they match, the
        CURRENT in-memory this.pos.session.access_token is used to
        retry the report (never a stored token, never re-printing
        physically); when they don't match (a stale marker from an
        older session), the marker is discarded locally - never
        reported with the current session's own token, never triggers
        a reprint, and must NOT set allFlushed=false, so it can never
        permanently block the current session's own claims."""
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

        stale_branch = flush_method.split('if (entry.pos_session_id !== currentSessionId) {')[1].split('\n            }')[0]
        self.assertIn('clearPendingResult(entry.job_id)', stale_branch)
        self.assertIn('continue', stale_branch)
        self.assertNotIn('allFlushed = false', stale_branch)
        self.assertNotIn('report_pos_direct_auto_result', stale_branch)

    def test_rescue_session_cannot_claim_direct_auto_job(self):
        """A rescue/recovery pos.session is not a real browser print
        executor and must never claim a Direct Auto job, even with a
        correct token from a genuine POS user."""
        config = self._make_test_pos_config('Rescue Config')
        user = self._make_pos_only_user('rescue_user')
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

    def test_rescue_session_cannot_report_direct_auto_result(self):
        """Rescue is also rejected on the report path, independent of
        the claim path's own rejection."""
        config = self._make_test_pos_config('Rescue Report Config')
        user = self._make_pos_only_user('rescue_report_user')
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

    def test_cross_company_pos_user_cannot_claim_direct_auto_job(self):
        """An authenticated caller only allowed in Company A must not
        be able to claim a job through an active session belonging to
        Company B, even with that session's own correct token -
        sudo() on the session/station lookups must never let a valid
        token bypass Odoo's own multi-company boundary."""
        station_b = self.env['kds.station'].create({
            'name': 'Cross Company Station B', 'code': 'CROSSCOMPANYB', 'target_prep_time': 10,
            'operating_mode': 'printer_only', 'company_id': self.company_b.id,
            'flexsys_printing_method': 'direct_network', 'flexsys_printer_ip': '10.0.0.90',
        })
        config_b = self._make_test_pos_config('Cross Company B Config', company_id=self.company_b.id)
        user_b_owner = self._grant_company_access(
            self._make_pos_only_user('cross_company_b_owner'), self.company_b)
        session_b = self.env['pos.session'].create({'config_id': config_b.id, 'user_id': user_b_owner.id})

        # caller_a is only allowed in the default company (self.company)
        # - never explicitly granted company_b.
        caller_a = self._make_pos_only_user('cross_company_caller_only_a')

        order = self._order_for(station_b, company=self.company_b)
        self.env['kds.print.job'].create_direct_auto_print_job(order.id, station_b.id)

        claimed = self.env['kds.print.job'].with_user(caller_a).claim_direct_auto_jobs(
            session_b.id, session_b.sudo().access_token, 'device-cross-company', limit=1)
        self.assertEqual(
            len(claimed), 0,
            "A caller not allowed in Session B's own company must not be able to claim through it."
        )

    def test_cross_company_pos_user_cannot_report_direct_auto_result(self):
        """Same cross-company rejection on the report path. The
        legitimate Company B claim is explicitly asserted to succeed
        BEFORE the cross-company report attempt is ever made, so this
        test can only pass by actually reaching and exercising the
        real contract."""
        station_b = self.env['kds.station'].create({
            'name': 'Cross Company Station B Report', 'code': 'CROSSCOMPANYBREPORT', 'target_prep_time': 10,
            'operating_mode': 'printer_only', 'company_id': self.company_b.id,
            'flexsys_printing_method': 'direct_network', 'flexsys_printer_ip': '10.0.0.91',
        })
        config_b = self._make_test_pos_config('Cross Company B Report Config', company_id=self.company_b.id)
        user_b_owner = self._grant_company_access(
            self._make_pos_only_user('cross_company_b_report_owner'), self.company_b)
        session_b = self.env['pos.session'].create({'config_id': config_b.id, 'user_id': user_b_owner.id})

        order = self._order_for(station_b, company=self.company_b)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, station_b.id)

        claimed = self.env['kds.print.job'].with_user(user_b_owner).claim_direct_auto_jobs(
            session_b.id, session_b.sudo().access_token, 'device-cross-report', limit=1)
        self.assertEqual(len(claimed), 1, "The legitimate Company B owner's own claim must actually succeed.")
        job.invalidate_recordset()
        self.assertEqual(job.direct_executor_pos_session_id, session_b)
        self.assertEqual(job.status, 'dispatched')

        caller_a = self._make_pos_only_user('cross_company_report_caller_only_a')
        with self.assertRaises(ValidationError):
            job.with_user(caller_a).report_pos_direct_auto_result(
                session_b.id, session_b.sudo().access_token, 'device-cross-report', True)

    def test_empty_executor_id_rejected_on_claim(self):
        """An empty/falsy executor_id must be rejected outright by the
        claim, not merely accepted as "no device identity"."""
        config = self._make_test_pos_config('Empty Executor Config')
        user = self._make_pos_only_user('empty_executor_user')
        session = self.env['pos.session'].create({'config_id': config.id, 'user_id': user.id})
        order = self._order_for(self.station_printer_only)
        self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)

        for empty_value in (False, '', None):
            with self.subTest(empty_value=empty_value):
                claimed = self.env['kds.print.job'].with_user(user).claim_direct_auto_jobs(
                    session.id, session.sudo().access_token, empty_value, limit=1)
                self.assertEqual(len(claimed), 0, "An empty executor_id must reject the claim.")

    def test_empty_executor_id_rejected_on_report(self):
        config = self._make_test_pos_config('Empty Executor Report Config')
        user = self._make_pos_only_user('empty_executor_report_user')
        session = self.env['pos.session'].create({'config_id': config.id, 'user_id': user.id})
        order = self._order_for(self.station_printer_only)
        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, self.station_printer_only.id)
        self.env['kds.print.job'].with_user(user).claim_direct_auto_jobs(
            session.id, session.sudo().access_token, 'device-real-report', limit=1)
        job.invalidate_recordset()

        with self.assertRaises(ValidationError):
            job.with_user(user).report_pos_direct_auto_result(
                session.id, session.sudo().access_token, False, True)

    def test_pos_users_are_not_granted_broad_kds_model_access(self):
        """point_of_sale.group_pos_user must not have any general
        access to kds.print.job/kds.order/kds.order.line - the narrow
        RPC methods (with their own internal sudo(), scoped to
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

    def test_make_test_pos_config_respects_company_override(self):
        """The shared _make_test_pos_config() helper must genuinely
        create the record UNDER the overridden company (via
        with_company()), not merely set company_id on the resulting
        record while still resolving Odoo's own company-dependent
        DEFAULTS (journal_id, invoice_journal_id, picking_type_id,
        warehouse, etc.) from whichever company env.company already
        was. This regression test creates a genuine Company B
        pos.config through the helper and confirms every company-
        dependent field Odoo actually populated is genuinely Company
        B's own - not merely that config_b.company_id itself says so."""
        config_b = self._make_test_pos_config('Helper Company Check', company_id=self.company_b.id)
        self.assertEqual(config_b.company_id, self.company_b)
        for field_name in ('journal_id', 'invoice_journal_id', 'picking_type_id'):
            related_record = getattr(config_b, field_name, False)
            if related_record:
                self.assertEqual(
                    related_record.company_id, self.company_b,
                    "%s must belong to Company B, not leak a default from another company." % field_name
                )
