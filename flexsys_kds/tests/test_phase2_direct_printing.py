# -*- coding: utf-8 -*-
"""Phase 2 ("Direct Printing <-> kds.print.job Integration") regression
suite - model-level tests.

These tests exercise kds.print.job's own model-level logic directly
(create_direct_print_job, report_direct_print_result,
action_mark_direct_failed, _cron_timeout_stale_direct_jobs) - the SAME
logic both the Internal KDS ORM call site and the Public Kiosk's own
/print/prepare and /print/result routes call into.

For a REAL end-to-end HTTP round trip through those two routes
themselves (station/token header handling, the JSON-RPC envelope,
ownership rejection over an actual HTTP request) see the separate
HttpCase-based suite in test_phase2_direct_printing_http.py - kept in
its own file since HttpCase commits real, uncommitted-rollback rows
via a real server thread rather than TransactionCase's own
rolled-back transaction (see that file's own module docstring).
"""
from datetime import timedelta

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import FlexSysKdsTestCommon


@tagged('post_install', '-at_install')
class TestPhase2DirectPrinting(FlexSysKdsTestCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # A station fully configured for Direct Network, with NO
        # kds.printer records at all - the exact "Critical" scenario
        # from Phase 2's own acceptance criteria: Direct Network must
        # work even when station.printer_ids is empty.
        cls.station_direct = cls.env['kds.station'].create({
            'name': 'Test Direct Station', 'code': 'TESTDIRECT', 'target_prep_time': 10,
            'flexsys_printing_method': 'direct_network',
            'flexsys_printer_ip': '192.168.1.50',
        })

        # Direct Network selected, but no Printer IP configured yet -
        # the Compatibility Guard scenario.
        cls.station_direct_no_ip = cls.env['kds.station'].create({
            'name': 'Test Direct No-IP Station', 'code': 'TESTDIRECTNOIP', 'target_prep_time': 10,
            'flexsys_printing_method': 'direct_network',
            'flexsys_printer_ip': False,
        })

        # Odoo IoT selected - not implemented yet, must never create
        # any job at all (Direct or Agent).
        cls.station_iot = cls.env['kds.station'].create({
            'name': 'Test IoT Station', 'code': 'TESTIOT', 'target_prep_time': 10,
            'flexsys_printing_method': 'iot',
            'flexsys_printer_ip': '192.168.1.60',  # present but irrelevant for iot
        })

        # station_kitchen (from common.py) already defaults to
        # flexsys_printing_method='direct_network' with no IP set - a
        # second, independent instance of the "no IP" scenario, but
        # ALSO carries a real kds.printer (added below), so it doubles
        # as the Legacy Agent fixture too, matching how a real station
        # migrating between transports would look.
        cls.printer_legacy = cls.env['kds.printer'].create({
            'name': 'Test Legacy Printer',
            'station_id': cls.station_kitchen.id,
            'is_default': True,
        })

    def _order_for(self, station):
        order = self._make_order([(self.product_burger, 1)])
        self._route_line_to_station(order.line_ids, station)
        return order

    # -----------------------------------------------------------------
    # A. Internal KDS Direct Success
    # -----------------------------------------------------------------
    def test_a_internal_kds_direct_success_creates_job_and_marks_printed(self):
        order = self._order_for(self.station_direct)
        jobs_before = self.env['kds.print.job'].search_count([])

        result = self.env['kds.print.job'].create_direct_print_job(
            order.id, self.station_direct.id, job_type='manual',
            reason='kitchen_request', source='internal_kds')
        job = self.env['kds.print.job'].browse(result['job_id'])

        self.assertEqual(self.env['kds.print.job'].search_count([]), jobs_before + 1)
        self.assertEqual(job.transport, 'direct_network')
        self.assertEqual(job.source, 'internal_kds')
        self.assertEqual(job.printer_target, '192.168.1.50')
        self.assertEqual(job.status, 'dispatched')
        self.assertFalse(job.printer_id, "Direct jobs must not require/set a legacy kds.printer.")
        self.assertTrue(job.dispatch_deadline, "A dispatch deadline must be set for timeout detection.")

        job.report_direct_print_result(True)
        self.assertEqual(job.status, 'printed')
        self.assertTrue(job.printed_at)

    # -----------------------------------------------------------------
    # B. Public Kiosk Direct Success
    # -----------------------------------------------------------------
    def test_b_public_kiosk_direct_success_has_no_internal_user(self):
        order = self._order_for(self.station_direct)

        result = self.env['kds.print.job'].create_direct_print_job(
            order.id, self.station_direct.id, job_type='manual',
            reason='kitchen_request', source='public_kiosk')
        job = self.env['kds.print.job'].browse(result['job_id'])

        self.assertEqual(job.source, 'public_kiosk')
        self.assertFalse(
            job.user_id,
            "A public, unauthenticated kiosk request must never be attributed to an "
            "invented/technical internal user."
        )

        job.report_direct_print_result(True)
        self.assertEqual(job.status, 'printed')

    # -----------------------------------------------------------------
    # C. Failure records a structured, non-raw result
    # -----------------------------------------------------------------
    def test_c_failure_records_structured_error(self):
        order = self._order_for(self.station_direct)
        result = self.env['kds.print.job'].create_direct_print_job(
            order.id, self.station_direct.id, source='internal_kds')
        job = self.env['kds.print.job'].browse(result['job_id'])

        job.report_direct_print_result(
            False, error_code='NETWORK_ERROR', error_message='Unable to reach the printer over the local network.')

        self.assertEqual(job.status, 'failed')
        self.assertEqual(job.error_code, 'NETWORK_ERROR')
        self.assertEqual(job.error, 'Unable to reach the printer over the local network.')
        self.assertTrue(job.failed_at)

    # -----------------------------------------------------------------
    # D. Direct Network with no Printer IP -> refuses to create a job
    #    (mirrors create_reprint()'s own NoPrinterConfiguredError
    #    contract exactly - no job, no increased print count).
    # -----------------------------------------------------------------
    def test_d_direct_network_no_ip_creates_no_job(self):
        order = self._order_for(self.station_direct_no_ip)
        jobs_before = self.env['kds.print.job'].search_count([])

        with self.assertRaises(Exception):  # NoPrinterConfiguredError, a UserError subclass
            self.env['kds.print.job'].create_direct_print_job(
                order.id, self.station_direct_no_ip.id, source='internal_kds')

        self.assertEqual(
            self.env['kds.print.job'].search_count([]), jobs_before,
            "No job of any kind should be created when Direct Network has no Printer IP configured."
        )

    # -----------------------------------------------------------------
    # E. error / error_code / failed_at are genuinely separate,
    #    independently-stored fields - not one field wearing three
    #    hats.
    # -----------------------------------------------------------------
    def test_e_error_fields_are_independent(self):
        order = self._order_for(self.station_direct)
        result = self.env['kds.print.job'].create_direct_print_job(
            order.id, self.station_direct.id, source='internal_kds')
        job = self.env['kds.print.job'].browse(result['job_id'])

        self.assertFalse(job.error)
        self.assertFalse(job.error_code)
        self.assertFalse(job.failed_at)

        job.report_direct_print_result(False, error_code='LNA_DENIED', error_message='Local network access permission was denied.')

        self.assertEqual(job.error_code, 'LNA_DENIED')
        self.assertEqual(job.error, 'Local network access permission was denied.')
        self.assertTrue(job.failed_at)
        # The three are stored independently - changing one field's
        # own name in the model would break exactly one of these
        # assertions, not all three at once, proving they are not
        # secretly aliases of a single underlying value.
        self.assertNotEqual(job.error_code, job.error)

    # -----------------------------------------------------------------
    # F. CRITICAL: Direct Network works even when station.printer_ids
    #    is completely empty - the Agent-only assumption this whole
    #    phase exists to remove.
    # -----------------------------------------------------------------
    def test_f_direct_network_works_with_zero_legacy_printers(self):
        self.assertFalse(
            self.station_direct.printer_ids,
            "Test fixture sanity check: station_direct must have zero kds.printer records."
        )
        order = self._order_for(self.station_direct)

        result = self.env['kds.print.job'].create_direct_print_job(
            order.id, self.station_direct.id, source='internal_kds')
        job = self.env['kds.print.job'].browse(result['job_id'])

        self.assertEqual(job.status, 'dispatched')
        self.assertFalse(job.printer_id)

    # -----------------------------------------------------------------
    # G. Legacy Agent path is completely unaffected by any of the
    #    above - create_reprint() still requires a real kds.printer,
    #    exactly as before this phase.
    # -----------------------------------------------------------------
    def test_g_legacy_agent_unaffected(self):
        order = self._order_for(self.station_kitchen)
        job = self.env['kds.print.job'].create_reprint(
            order, self.station_kitchen, reason='kitchen_request')

        self.assertEqual(job.transport, 'agent', "Every pre-Phase-2 job type must default to 'agent'.")
        self.assertEqual(job.printer_id, self.printer_legacy)
        self.assertFalse(job.printer_target, "printer_target is a Direct Network-only field.")
        self.assertFalse(job.source, "source is a Direct Network-only field.")

    def test_g_legacy_agent_still_refuses_with_no_printer(self):
        order = self._order_for(self.station_kitchen)
        no_printer_station = self.env['kds.station'].create({
            'name': 'Test No Printer Station', 'code': 'TESTNOPRINT', 'target_prep_time': 10,
        })
        self._route_line_to_station(order.line_ids, no_printer_station)
        with self.assertRaises(Exception):
            self.env['kds.print.job'].create_reprint(
                order, no_printer_station, reason='kitchen_request')

    # -----------------------------------------------------------------
    # H. Odoo IoT never creates a Direct job (nor an Agent job) by
    #    mistake - the same "no printer configured" guard applies,
    #    since create_direct_print_job() only ever proceeds for
    #    'direct_network' specifically.
    # -----------------------------------------------------------------
    def test_h_iot_creates_no_direct_job(self):
        order = self._order_for(self.station_iot)
        jobs_before = self.env['kds.print.job'].search_count([])

        with self.assertRaises(Exception):
            self.env['kds.print.job'].create_direct_print_job(
                order.id, self.station_iot.id, source='internal_kds')

        self.assertEqual(
            self.env['kds.print.job'].search_count([]), jobs_before,
            "An 'iot' station must never get a Direct Network job created for it."
        )

    # -----------------------------------------------------------------
    # I/J/K. Public Kiosk result ownership - verified here against the
    # exact same conditions kiosk_report_direct_print_result() itself
    # checks (see controllers/kds_kiosk.py), directly at the model
    # layer. The real, end-to-end HTTP versions of these same three
    # scenarios (an actual request through the route itself) are in
    # test_phase2_direct_printing_http.py's own
    # test_http_prepare_order_not_of_station_is_rejected/
    # test_http_result_rejects_different_station/
    # test_http_result_rejects_internal_kds_job.
    # -----------------------------------------------------------------
    def test_i_same_station_same_kiosk_job_is_a_valid_target(self):
        order = self._order_for(self.station_direct)
        result = self.env['kds.print.job'].create_direct_print_job(
            order.id, self.station_direct.id, source='public_kiosk')
        job = self.env['kds.print.job'].browse(result['job_id'])

        # Exactly the condition kiosk_report_direct_print_result()
        # checks before allowing a write.
        is_valid_target = (
            job.exists() and job.station_id == self.station_direct
            and job.transport == 'direct_network' and job.source == 'public_kiosk'
        )
        self.assertTrue(is_valid_target)
        job.report_direct_print_result(True)
        self.assertEqual(job.status, 'printed')

    def test_j_different_station_job_is_rejected(self):
        order = self._order_for(self.station_direct)
        result = self.env['kds.print.job'].create_direct_print_job(
            order.id, self.station_direct.id, source='public_kiosk')
        job = self.env['kds.print.job'].browse(result['job_id'])

        # A kiosk session authenticated for a DIFFERENT station must
        # not be able to target this job.
        other_station = self.station_kitchen
        is_valid_target = (
            job.exists() and job.station_id == other_station
            and job.transport == 'direct_network' and job.source == 'public_kiosk'
        )
        self.assertFalse(is_valid_target, "A job belonging to a different station must be rejected.")

    def test_k_internal_kds_job_is_rejected_by_kiosk_ownership_check(self):
        order = self._order_for(self.station_direct)
        result = self.env['kds.print.job'].create_direct_print_job(
            order.id, self.station_direct.id, source='internal_kds')
        job = self.env['kds.print.job'].browse(result['job_id'])

        # Same station, same transport - but this job was created by
        # Internal KDS, not this kiosk session. Must be rejected.
        is_valid_target = (
            job.exists() and job.station_id == self.station_direct
            and job.transport == 'direct_network' and job.source == 'public_kiosk'
        )
        self.assertFalse(
            is_valid_target,
            "An Internal KDS job must never be updatable via the Public Kiosk's own result route."
        )

    # -----------------------------------------------------------------
    # L. Idempotent repeated same-outcome report
    # -----------------------------------------------------------------
    def test_l_repeated_same_success_is_idempotent(self):
        order = self._order_for(self.station_direct)
        result = self.env['kds.print.job'].create_direct_print_job(
            order.id, self.station_direct.id, source='internal_kds')
        job = self.env['kds.print.job'].browse(result['job_id'])

        job.report_direct_print_result(True)
        first_printed_at = job.printed_at

        # A second, identical "successful" report must be a silent
        # no-op - not an error, and must not overwrite the timestamp.
        job.report_direct_print_result(True)
        self.assertEqual(job.status, 'printed')
        self.assertEqual(job.printed_at, first_printed_at)

    def test_l_repeated_same_failure_is_idempotent(self):
        order = self._order_for(self.station_direct)
        result = self.env['kds.print.job'].create_direct_print_job(
            order.id, self.station_direct.id, source='internal_kds')
        job = self.env['kds.print.job'].browse(result['job_id'])

        job.report_direct_print_result(False, error_code='TIMEOUT', error_message='Printer connection timed out.')
        first_failed_at = job.failed_at

        job.report_direct_print_result(False, error_code='TIMEOUT', error_message='Printer connection timed out.')
        self.assertEqual(job.status, 'failed')
        self.assertEqual(job.failed_at, first_failed_at)

    # -----------------------------------------------------------------
    # M. Conflicting terminal report is rejected
    # -----------------------------------------------------------------
    def test_m_conflicting_result_after_printed_is_rejected(self):
        order = self._order_for(self.station_direct)
        result = self.env['kds.print.job'].create_direct_print_job(
            order.id, self.station_direct.id, source='internal_kds')
        job = self.env['kds.print.job'].browse(result['job_id'])

        job.report_direct_print_result(True)
        with self.assertRaises(ValidationError):
            job.report_direct_print_result(False, error_code='NETWORK_ERROR', error_message='...')
        # The original, correct outcome must survive the rejected
        # conflicting attempt untouched.
        self.assertEqual(job.status, 'printed')

    def test_m_conflicting_result_after_failed_is_rejected(self):
        order = self._order_for(self.station_direct)
        result = self.env['kds.print.job'].create_direct_print_job(
            order.id, self.station_direct.id, source='internal_kds')
        job = self.env['kds.print.job'].browse(result['job_id'])

        job.report_direct_print_result(False, error_code='TIMEOUT', error_message='...')
        with self.assertRaises(ValidationError):
            job.report_direct_print_result(True)
        self.assertEqual(job.status, 'failed')

    def test_m_report_on_non_direct_job_is_rejected(self):
        order = self._order_for(self.station_kitchen)
        job = self.env['kds.print.job'].create_reprint(
            order, self.station_kitchen, reason='kitchen_request')
        with self.assertRaises(ValidationError):
            job.report_direct_print_result(True)

    # -----------------------------------------------------------------
    # Timeout cron: a Direct job whose own browser tab never reported
    # back (crashed/closed) is automatically failed once its
    # dispatch_deadline has passed.
    # -----------------------------------------------------------------
    def test_timeout_cron_fails_stale_dispatched_direct_jobs(self):
        order = self._order_for(self.station_direct)
        result = self.env['kds.print.job'].create_direct_print_job(
            order.id, self.station_direct.id, source='internal_kds')
        job = self.env['kds.print.job'].browse(result['job_id'])

        # Simulate time having passed well beyond the deadline set at
        # creation time.
        job.dispatch_deadline = job.dispatch_deadline - timedelta(hours=1)

        self.env['kds.print.job']._cron_timeout_stale_direct_jobs()

        self.assertEqual(job.status, 'failed')
        self.assertEqual(job.error_code, 'RESULT_TIMEOUT')
        self.assertTrue(job.failed_at)

    def test_timeout_cron_does_not_touch_legacy_agent_jobs(self):
        """The cron's own search is scoped to transport='direct_network'
        only - a Legacy Agent job left 'pending'/'dispatched' for a
        long time (its own lease_expires_at mechanism governs that
        separately) must never be touched by this cron."""
        order = self._order_for(self.station_kitchen)
        job = self.env['kds.print.job'].create_reprint(
            order, self.station_kitchen, reason='kitchen_request')
        job.write({'status': 'dispatched', 'dispatched_at': job.create_date - timedelta(hours=2)})

        self.env['kds.print.job']._cron_timeout_stale_direct_jobs()

        self.assertEqual(job.status, 'dispatched', "A Legacy Agent job must never be touched by this cron.")
        self.assertFalse(job.error_code)

    def test_timeout_cron_does_not_touch_jobs_not_yet_past_deadline(self):
        order = self._order_for(self.station_direct)
        result = self.env['kds.print.job'].create_direct_print_job(
            order.id, self.station_direct.id, source='internal_kds')
        job = self.env['kds.print.job'].browse(result['job_id'])

        # dispatch_deadline is still in the future (just created) -
        # must not be touched.
        self.env['kds.print.job']._cron_timeout_stale_direct_jobs()
        self.assertEqual(job.status, 'dispatched')
