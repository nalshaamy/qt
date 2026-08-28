# -*- coding: utf-8 -*-
"""Phase 2 ("Direct Printing <-> kds.print.job Integration") - REAL
HTTP-level end-to-end tests for the two new Public Kiosk routes:
/flexsyskds/public/api/print/prepare and .../print/result.

Uses odoo.tests.HttpCase (a real HTTP server + real, committed
database rows, not TransactionCase's own rolled-back transaction) to
actually exercise the JSON-RPC route handlers themselves - station/
token header validation, the JSON-RPC request/response envelope, and
ownership rejection - not just the underlying model methods those
routes call into (see test_phase2_direct_printing.py's own model-level
suite for that).

kiosk_token is a real, stored field on kds.station
(models/kds_station.py's own create() override auto-generates one via
secrets.token_urlsafe(24) for every new station) - read directly from
each fixture station created below, never invented or guessed.
"""
import json

from odoo.tests import HttpCase, tagged


def _jsonrpc(test_case, route, params):
    """Minimal JSON-RPC 2.0 POST helper against a `type='jsonrpc'`
    Odoo route, matching the documented request/response envelope
    (`{"jsonrpc": "2.0", "method": "call", "params": {...}}` in,
    `{"jsonrpc": "2.0", "result": {...}}` out). Uses HttpCase's own
    documented self.url_open() (not a lower-level session/opener
    attribute, which is not part of HttpCase's own stable, documented
    API) - url_open() already knows the running test server's own
    base URL, so only the route's own path is passed here.
    """
    response = test_case.url_open(
        route,
        data=json.dumps({"jsonrpc": "2.0", "method": "call", "params": params}),
        headers={"Content-Type": "application/json"},
    )
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise AssertionError("JSON-RPC error from %s: %s" % (route, payload["error"]))
    return payload["result"]


@tagged('post_install', '-at_install')
class TestPhase2DirectPrintingHttp(HttpCase):
    """Separate from test_phase2_direct_printing.py's own TransactionCase
    suite deliberately - HttpCase commits real rows via a real HTTP
    server thread rather than rolling back a transaction, so it is
    kept isolated here rather than mixed into that faster, more
    numerous model-level suite."""

    def setUp(self):
        super().setUp()
        self.station = self.env['kds.station'].create({
            'name': 'HTTP Test Direct Station', 'code': 'HTTPTESTDIRECT', 'target_prep_time': 10,
            'flexsys_printing_method': 'direct_network',
            'flexsys_printer_ip': '192.168.1.77',
        })
        self.other_station = self.env['kds.station'].create({
            'name': 'HTTP Test Other Station', 'code': 'HTTPTESTOTHER', 'target_prep_time': 10,
            'flexsys_printing_method': 'direct_network',
            'flexsys_printer_ip': '192.168.1.88',
        })
        self.categ = self.env['product.category'].create({'name': 'HTTP Test Category'})
        self.product = self.env['product.product'].create({
            'name': 'HTTP Test Product', 'categ_id': self.categ.id,
        })
        self.order = self.env['kds.order'].create({
            'source': 'pos', 'order_type': 'dine_in', 'company_id': self.env.company.id,
        })
        line = self.env['kds.order.line'].create({
            'order_id': self.order.id, 'product_id': self.product.id, 'qty': 1,
        })
        line.with_context(kds_workflow_write=True).write({'station_id': self.station.id})

        # For the Legacy Agent rejection test below - a real
        # kds.printer on the SAME station, so create_reprint() can
        # succeed and produce a genuine transport='agent' job to
        # attempt (and correctly fail) reporting a Direct Network
        # result against.
        self.printer_legacy = self.env['kds.printer'].create({
            'name': 'HTTP Test Legacy Printer',
            'station_id': self.station.id,
            'is_default': True,
        })

    def _prepare(self, station, order_id):
        return _jsonrpc(self, '/flexsyskds/public/api/print/prepare', {
            'station_code': station.code, 'token': station.kiosk_token, 'order_id': order_id,
        })

    def _result(self, station, job_id, successful, error_code=False, error_message=False):
        return _jsonrpc(self, '/flexsyskds/public/api/print/result', {
            'station_code': station.code, 'token': station.kiosk_token, 'job_id': job_id,
            'successful': successful, 'error_code': error_code, 'error_message': error_message,
        })

    # -----------------------------------------------------------------
    # G (HTTP). prepare with a valid token/order belonging to the
    # station -> exactly one job created.
    # -----------------------------------------------------------------
    def test_http_prepare_valid_request_creates_one_job(self):
        jobs_before = self.env['kds.print.job'].search_count([])
        result = self._prepare(self.station, self.order.id)

        self.assertTrue(result.get('ok'), result)
        self.assertIn('job_id', result)
        self.assertEqual(self.env['kds.print.job'].search_count([]), jobs_before + 1)

        job = self.env['kds.print.job'].browse(result['job_id'])
        self.assertEqual(job.transport, 'direct_network')
        self.assertEqual(job.source, 'public_kiosk')
        self.assertEqual(job.status, 'dispatched')

    # -----------------------------------------------------------------
    # H (HTTP). prepare with an order that does NOT belong to this
    # station -> rejected, no job created.
    # -----------------------------------------------------------------
    def test_http_prepare_order_not_of_station_is_rejected(self):
        jobs_before = self.env['kds.print.job'].search_count([])
        # self.order's own line is routed to self.station, not
        # self.other_station - other_station's own kiosk session must
        # not be able to prepare a print job for it.
        result = self._prepare(self.other_station, self.order.id)

        self.assertFalse(result.get('ok'), result)
        self.assertEqual(self.env['kds.print.job'].search_count([]), jobs_before)

    def test_http_prepare_invalid_token_is_rejected(self):
        jobs_before = self.env['kds.print.job'].search_count([])
        result = _jsonrpc(self, '/flexsyskds/public/api/print/prepare', {
            'station_code': self.station.code, 'token': 'not-the-real-token',
            'order_id': self.order.id,
        })
        self.assertFalse(result.get('ok'), result)
        self.assertEqual(self.env['kds.print.job'].search_count([]), jobs_before)

    # -----------------------------------------------------------------
    # I (HTTP). result with matching station/token/job -> succeeds.
    # -----------------------------------------------------------------
    def test_http_result_valid_success_marks_printed(self):
        prepared = self._prepare(self.station, self.order.id)
        job_id = prepared['job_id']

        result = self._result(self.station, job_id, True)
        self.assertTrue(result.get('ok'), result)

        job = self.env['kds.print.job'].browse(job_id)
        self.assertEqual(job.status, 'printed')

    def test_http_result_valid_failure_marks_failed(self):
        prepared = self._prepare(self.station, self.order.id)
        job_id = prepared['job_id']

        result = self._result(self.station, job_id, False, error_code='NETWORK_ERROR',
                               error_message='Unable to reach the printer.')
        self.assertTrue(result.get('ok'), result)

        job = self.env['kds.print.job'].browse(job_id)
        self.assertEqual(job.status, 'failed')
        self.assertEqual(job.error_code, 'NETWORK_ERROR')

    # -----------------------------------------------------------------
    # J (HTTP). result cannot update a job belonging to a DIFFERENT
    # station's own kiosk session.
    # -----------------------------------------------------------------
    def test_http_result_rejects_different_station(self):
        prepared = self._prepare(self.station, self.order.id)
        job_id = prepared['job_id']

        # other_station's own kiosk session attempts to report a
        # result for a job that belongs to self.station.
        result = self._result(self.other_station, job_id, True)
        self.assertFalse(result.get('ok'), result)

        job = self.env['kds.print.job'].browse(job_id)
        self.assertEqual(job.status, 'dispatched', "The job must remain untouched by the rejected attempt.")

    # -----------------------------------------------------------------
    # K (HTTP). result cannot update a job that was created by
    # Internal KDS (source='internal_kds'), even at the exact same
    # station over the exact same transport.
    # -----------------------------------------------------------------
    def test_http_result_rejects_internal_kds_job(self):
        internal_job_result = self.env['kds.print.job'].create_direct_print_job(
            self.order.id, self.station.id, source='internal_kds')
        job_id = internal_job_result['job_id']

        result = self._result(self.station, job_id, True)
        self.assertFalse(
            result.get('ok'), result,
            "The Public Kiosk's own /print/result route must reject a job whose source is 'internal_kds'."
        )
        job = self.env['kds.print.job'].browse(job_id)
        self.assertEqual(job.status, 'dispatched')

    # -----------------------------------------------------------------
    # NEW (Closeout item 1): result cannot update a Legacy Agent job
    # (transport='agent') at all - the job must remain completely
    # unmodified. The controller's own check (job.transport !=
    # 'direct_network') already covers this; this is the real,
    # end-to-end HTTP confirmation of that exact contract, completing
    # the ownership coverage alongside J (different station) and K
    # (internal_kds source).
    # -----------------------------------------------------------------
    def test_http_result_rejects_legacy_agent_job(self):
        agent_job = self.env['kds.print.job'].create_reprint(
            self.order, self.station, reason='kitchen_request')
        self.assertEqual(agent_job.transport, 'agent')
        original_status = agent_job.status
        original_write_date = agent_job.write_date

        result = self._result(self.station, agent_job.id, True)
        self.assertFalse(
            result.get('ok'), result,
            "The Public Kiosk's own /print/result route must reject a Legacy Agent (transport='agent') job."
        )

        agent_job.invalidate_recordset()
        self.assertEqual(
            agent_job.status, original_status,
            "A rejected Legacy Agent job's own status must remain completely untouched."
        )
        self.assertEqual(
            agent_job.write_date, original_write_date,
            "A rejected Legacy Agent job must not be written to at all - not even a no-op field touch."
        )

    # -----------------------------------------------------------------
    # L (HTTP). repeated identical success callback is idempotent over
    # real HTTP, not just at the model layer.
    # -----------------------------------------------------------------
    def test_http_result_repeated_success_is_idempotent(self):
        prepared = self._prepare(self.station, self.order.id)
        job_id = prepared['job_id']

        first = self._result(self.station, job_id, True)
        self.assertTrue(first.get('ok'))
        second = self._result(self.station, job_id, True)
        self.assertTrue(second.get('ok'), "A repeated identical success report must be accepted, not rejected.")

        job = self.env['kds.print.job'].browse(job_id)
        self.assertEqual(job.status, 'printed')

    # -----------------------------------------------------------------
    # M (HTTP). a conflicting callback after a terminal state is
    # rejected over real HTTP.
    # -----------------------------------------------------------------
    def test_http_result_conflicting_outcome_is_rejected(self):
        prepared = self._prepare(self.station, self.order.id)
        job_id = prepared['job_id']

        self._result(self.station, job_id, True)
        conflicting = self._result(self.station, job_id, False, error_code='TIMEOUT')
        self.assertFalse(conflicting.get('ok'), conflicting)

        job = self.env['kds.print.job'].browse(job_id)
        self.assertEqual(job.status, 'printed', "The original outcome must survive the rejected conflicting report.")
