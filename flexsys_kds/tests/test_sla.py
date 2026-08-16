# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo.exceptions import ValidationError
from odoo.fields import Datetime
from odoo.tests import tagged

from .common import FlexSysKdsTestCommon


@tagged('post_install', '-at_install')
class TestSla(FlexSysKdsTestCommon):
    """SLA clock starts when the line arrives at the station
    (station_received_time, stamped while still 'new') and stops at
    Ready (ready_time) - not preparation_start_time, which only measured
    active cook time and ignored how long a ticket sat unclaimed in the
    queue."""

    def _order_at_kitchen(self, target_prep_time=10):
        self.station_kitchen.target_prep_time = target_prep_time
        order = self._make_order([(self.product_burger, 1)])
        self._route_line_to_station(order.line_ids, self.station_kitchen)
        return order

    def test_late_triggers_from_arrival_even_if_never_started(self):
        """A line still sitting in 'new' (never even Accepted/Started)
        should still go Late once it's been waiting past the target time -
        this is the core point of moving the clock to station_received_time:
        queue time counts, not just active cook time."""
        order = self._order_at_kitchen(target_prep_time=10)
        line = order.line_ids
        self.assertEqual(line.state, 'new')
        # Backdate arrival as if it's been sitting for 15 minutes already.
        line.station_received_time = Datetime.now() - timedelta(minutes=15)
        self.assertEqual(line.sla_status, 'late',
                          "A line with no preparation_start_time at all must still "
                          "be able to go Late, since the clock now starts at arrival.")

    def test_normal_shortly_after_arrival(self):
        order = self._order_at_kitchen(target_prep_time=10)
        line = order.line_ids
        line.station_received_time = Datetime.now() - timedelta(minutes=1)
        self.assertEqual(line.sla_status, 'normal')

    def test_warning_threshold_from_arrival(self):
        order = self._order_at_kitchen(target_prep_time=10)  # warning at 80% = 8 min
        line = order.line_ids
        line.station_received_time = Datetime.now() - timedelta(minutes=9)
        self.assertEqual(line.sla_status, 'warning')

    def test_clock_stops_at_ready_time(self):
        """Once Ready, elapsed time is fixed at ready_time - station_received_time
        forever after, it must not keep climbing just because the ticket is
        still sitting in the Ready column waiting for packing/pickup."""
        order = self._order_at_kitchen(target_prep_time=10)
        line = order.line_ids
        now = Datetime.now()
        line.write({
            'station_received_time': now - timedelta(minutes=5),
            'state': 'ready',
            'ready_time': now - timedelta(minutes=1),  # finished in ~4 min, well within target
        })
        self.assertEqual(line.sla_status, 'normal',
                          "Finished within target - must read Normal even though the "
                          "line has been sitting Ready for a while since ready_time.")

    def test_ready_but_finished_late_stays_late(self):
        """If it finished (Ready) after exceeding the target, it should
        show Late permanently - not silently reset to Normal just because
        it's no longer actively being timed."""
        order = self._order_at_kitchen(target_prep_time=10)
        line = order.line_ids
        now = Datetime.now()
        line.write({
            'station_received_time': now - timedelta(minutes=20),
            'state': 'ready',
            'ready_time': now - timedelta(minutes=1),  # took ~19 min against a 10 min target
        })
        self.assertEqual(line.sla_status, 'late')

    def test_order_level_sla_matches_worst_line(self):
        """kds.order.sla_status aggregates from its lines - covered here at
        the model level (the live-recompute fix in the controllers, which
        also guards against this being stale, is a separate concern not
        covered by these ORM-level tests)."""
        order = self._make_order([(self.product_burger, 1), (self.product_cappuccino, 1)])
        self._route_line_to_station(order.line_ids, self.station_kitchen)
        self.station_kitchen.target_prep_time = 10
        now = Datetime.now()
        line_a, line_b = order.line_ids[0], order.line_ids[1]
        line_a.station_received_time = now - timedelta(minutes=1)   # normal
        line_b.station_received_time = now - timedelta(minutes=15)  # late
        self.assertEqual(order.sla_status, 'late',
                          "Order-level status should reflect the worst line, not the first one.")

    # -----------------------------------------------------------------
    # Audit finding "SLA Validation" (HIGH): invalid station SLA
    # configuration must be rejected outright rather than silently
    # corrupting the SLA engine's output at read time.
    # -----------------------------------------------------------------
    def test_target_prep_time_must_be_positive(self):
        with self.assertRaises(ValidationError):
            self.station_kitchen.target_prep_time = 0

    def test_target_prep_time_cannot_be_negative(self):
        with self.assertRaises(ValidationError):
            self.station_kitchen.target_prep_time = -5

    def test_warning_threshold_must_be_positive(self):
        with self.assertRaises(ValidationError):
            self.station_kitchen.warning_threshold_pct = 0

    def test_late_threshold_must_exceed_warning_threshold(self):
        with self.assertRaises(ValidationError):
            self.station_kitchen.write({
                'warning_threshold_pct': 90,
                'late_threshold_pct': 80,  # would make "Warning" unreachable
            })

    def test_late_threshold_equal_to_warning_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.station_kitchen.write({
                'warning_threshold_pct': 80,
                'late_threshold_pct': 80,
            })

    def test_valid_sla_config_is_accepted(self):
        self.station_kitchen.write({
            'target_prep_time': 12,
            'warning_threshold_pct': 70,
            'late_threshold_pct': 100,
        })  # should not raise
        self.assertEqual(self.station_kitchen.target_prep_time, 12)

    # -----------------------------------------------------------------
    # Audit finding "SLA Freshness" (HIGH): kds.order.sla_status is
    # store=True (required for the backend list's "Late" filter), so it
    # only recomputes on an explicit dependency write - never purely from
    # time passing. The cron forces a periodic recompute so the stored
    # value stays genuinely fresh for every consumer (not just the two
    # JSON controllers, which already recompute live independently of
    # this cron - see their own v3.2 fix).
    # -----------------------------------------------------------------
    def test_cron_refreshes_stale_stored_sla_status(self):
        order = self._order_at_kitchen(target_prep_time=10)
        line = order.line_ids
        # Backdate WITHOUT going through a method that would itself
        # trigger recompute of the order-level field - simulates "time
        # has simply passed since this was last touched".
        line.station_received_time = Datetime.now() - timedelta(minutes=20)
        # The order-level stored field may still read whatever it was
        # last computed as (likely 'normal', from order/line creation) -
        # not asserted here, since relying on that staleness itself being
        # reproducible would make this test fragile. What's actually
        # under test is the cron's *effect*.
        self.env['kds.order']._cron_refresh_sla_status()
        order.invalidate_recordset(['sla_status'])
        self.assertEqual(order.sla_status, 'late',
                          "After the cron runs, a stored sla_status must reflect the "
                          "line's true current elapsed time, not a stale cached value.")

    def test_cron_ignores_completed_and_cancelled_orders(self):
        # Point: the cron scopes its search to active orders only - a
        # Completed/Cancelled order's stored sla_status should be left
        # exactly as it was (whatever it was when it finished), not
        # recomputed as if it were still an open ticket.
        order = self._order_at_kitchen(target_prep_time=10)
        order.line_ids.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_ready()
        order.line_ids.action_complete()  # DESIGN REVERSAL (v5.4): explicit step now
        self.assertEqual(order.state, 'completed')
        frozen_status = order.sla_status
        self.env['kds.order']._cron_refresh_sla_status()
        order.invalidate_recordset(['sla_status'])
        self.assertEqual(order.sla_status, frozen_status)
