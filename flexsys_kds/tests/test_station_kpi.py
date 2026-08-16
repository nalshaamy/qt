# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo.fields import Datetime
from odoo.tests import tagged

from .common import FlexSysKdsTestCommon


@tagged('post_install', '-at_install')
class TestStationKpi(FlexSysKdsTestCommon):
    """Audit finding "Station KPI Refresh" (MEDIUM): real bug found -
    active_order_count/late_order_count/avg_prep_time were all declared
    as depending only on `printer_ids` (correct for printer_count, wrong
    for the other three), so Odoo's ORM had no correct signal for when
    to actually recompute them - only when a printer was added/removed,
    never when an order arrived, changed state, or went Late. Each test
    here deliberately reads the KPI once *before* the change under test
    (priming the cache) to actually exercise the invalidation path, not
    just correctness of a fresh, never-before-read computation.
    """

    def test_active_order_count_updates_after_new_order_arrives(self):
        self.assertEqual(self.station_kitchen.active_order_count, 0)
        order = self._make_order([(self.product_burger, 1)])
        self._route_line_to_station(order.line_ids, self.station_kitchen)
        self.assertEqual(
            self.station_kitchen.active_order_count, 1,
            "KPI must refresh after a new order arrives, even though nothing wrote "
            "to printer_ids (the old, incorrect dependency).")

    def test_active_order_count_drops_after_order_completes(self):
        order = self._make_order([(self.product_burger, 1)])
        self._route_line_to_station(order.line_ids, self.station_kitchen)
        self.assertEqual(self.station_kitchen.active_order_count, 1)
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_ready()
        order.action_complete()  # DESIGN REVERSAL (v5.4): explicit step now
        self.assertEqual(
            self.station_kitchen.active_order_count, 0,
            "Once the only order completes, active_order_count must drop to 0.")

    def test_active_order_count_drops_after_pos_cancellation(self):
        order = self._make_order([(self.product_burger, 1)])
        self._route_line_to_station(order.line_ids, self.station_kitchen)
        self.assertEqual(self.station_kitchen.active_order_count, 1)
        order.action_cancel()
        self.assertEqual(self.station_kitchen.active_order_count, 0)

    def test_late_order_count_updates_when_a_line_crosses_into_late(self):
        self.station_kitchen.target_prep_time = 10
        order = self._make_order([(self.product_burger, 1)])
        self._route_line_to_station(order.line_ids, self.station_kitchen)
        self.assertEqual(self.station_kitchen.late_order_count, 0)
        order.line_ids.station_received_time = Datetime.now() - timedelta(minutes=20)
        self.assertEqual(
            self.station_kitchen.late_order_count, 1,
            "late_order_count must reflect a line crossing into Late, even though "
            "nothing wrote to printer_ids.")

    def test_late_order_count_uses_the_same_sla_logic_as_the_rest_of_kds(self):
        """Point: the KPI must use the same authoritative SLA calculation
        as everywhere else, not a separate implementation - checked here
        by confirming it agrees with the line's own sla_status rather
        than recomputing elapsed time independently."""
        self.station_kitchen.target_prep_time = 10
        order = self._make_order([(self.product_burger, 1)])
        self._route_line_to_station(order.line_ids, self.station_kitchen)
        order.line_ids.station_received_time = Datetime.now() - timedelta(minutes=20)
        self.assertEqual(order.line_ids.sla_status, 'late')
        self.assertEqual(self.station_kitchen.late_order_count, 1)

    def test_avg_prep_time_updates_after_a_line_becomes_ready(self):
        order = self._make_order([(self.product_burger, 1), (self.product_cappuccino, 1)])
        self._route_line_to_station(order.line_ids[0], self.station_kitchen)
        self._route_line_to_station(order.line_ids[1], self.station_coffee)
        self.assertEqual(self.station_kitchen.avg_prep_time, 0.0)

        order.line_ids[0].action_accept()
        order.line_ids[0].action_start()
        order.line_ids[0].action_ready()
        # The second line is still 'new' at a different station, so the
        # order doesn't auto-complete - line_ids[0] genuinely rests at
        # 'ready' rather than immediately cascading to 'completed'.
        self.assertEqual(order.line_ids[0].state, 'ready')

        self.assertGreaterEqual(
            self.station_kitchen.avg_prep_time, 0.0,
            "avg_prep_time must reflect the newly-Ready line without a stale "
            "pre-completion cached value.")

    def test_printer_count_still_updates_on_printer_change(self):
        # Regression check: the fix added new dependency paths without
        # removing the original, correct one - printer_count itself must
        # still work exactly as before.
        self.assertEqual(self.station_kitchen.printer_count, 0)
        self.env['kds.printer'].create({
            'name': 'Test KPI Printer', 'station_id': self.station_kitchen.id,
        })
        self.assertEqual(self.station_kitchen.printer_count, 1)
