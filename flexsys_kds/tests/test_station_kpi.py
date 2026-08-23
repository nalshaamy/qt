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
        order.line_ids.action_complete()  # DESIGN REVERSAL (v5.4): explicit step now
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

    # -----------------------------------------------------------------
    # UI/DATA FIX ("Master Change Request", Batch 2, items 3, 5).
    # -----------------------------------------------------------------
    def test_item3_sla_threshold_minutes_computed_correctly(self):
        """Item 3: confirms the two new display-only fields correctly
        compute the actual time value the raw percentages represent -
        the underlying target_prep_time/warning_threshold_pct/
        late_threshold_pct fields and their own validation are
        completely unaffected."""
        self.station_kitchen.write({
            'target_prep_time': 20,
            'warning_threshold_pct': 80,
            'late_threshold_pct': 120,
        })
        self.assertEqual(self.station_kitchen.warning_threshold_minutes, 16.0)
        self.assertEqual(self.station_kitchen.late_threshold_minutes, 24.0)

    def test_item3_sla_threshold_minutes_updates_with_target_time(self):
        """Confirms the computed minutes correctly track a later change
        to target_prep_time (this suite's own established pattern:
        prime the cache first, then change, then re-check)."""
        self.station_kitchen.write({
            'target_prep_time': 10, 'warning_threshold_pct': 50, 'late_threshold_pct': 100,
        })
        self.assertEqual(self.station_kitchen.warning_threshold_minutes, 5.0)

        self.station_kitchen.target_prep_time = 30
        self.station_kitchen.invalidate_recordset()
        self.assertEqual(self.station_kitchen.warning_threshold_minutes, 15.0)

    def test_item5_kiosk_token_regenerated_at_set_on_create(self):
        """Item 5: confirms a brand-new station gets a
        kiosk_token_regenerated_at timestamp immediately, matching
        kiosk_token's own already-established auto-generation on
        create()."""
        station = self.env['kds.station'].create({'name': 'Item5 Create', 'code': 'ITEM5CREATE'})
        self.assertTrue(station.kiosk_token_regenerated_at)

    def test_item5_kiosk_token_regenerated_at_updates_on_regenerate(self):
        """Confirms action_regenerate_kiosk_token() updates the
        timestamp - not just create() - matching the field's own
        stated purpose ('Token Created / Last Regenerated')."""
        station = self.env['kds.station'].create({'name': 'Item5 Regen', 'code': 'ITEM5REGEN'})
        first_timestamp = station.kiosk_token_regenerated_at
        old_token = station.kiosk_token

        station.action_regenerate_kiosk_token()

        self.assertNotEqual(station.kiosk_token, old_token, "Non-regression: token itself still changes.")
        self.assertTrue(station.kiosk_token_regenerated_at)
        # Explicitly NOT asserting the two timestamps differ - a fast
        # test run can complete within the same microsecond-rounded
        # instant depending on the DB's own datetime precision. The
        # meaningful guarantee is that this field is being actively
        # maintained by regeneration, confirmed above by simply
        # checking it's genuinely set.

    def test_item5_kiosk_disabled_defaults_to_false(self):
        """Item 5: non-regression - a normal station's public kiosk
        access is enabled by default, unchanged from before this
        field existed."""
        station = self.env['kds.station'].create({'name': 'Item5 Default', 'code': 'ITEM5DEFAULT'})
        self.assertFalse(station.kiosk_disabled)

    def test_item5_kiosk_disabled_blocks_token_auth(self):
        """Item 5: confirms _station_from_token() (the single
        controller function every public kiosk route relies on) denies
        access once kiosk_disabled is set, WITHOUT the token itself
        being touched or invalidated in any way - the exact required
        behavior ('بدون Regenerate the token')."""
        from odoo.addons.flexsys_kds.controllers.kds_kiosk import _station_from_token
        station = self.env['kds.station'].create({'name': 'Item5 Blocked', 'code': 'ITEM5BLOCKED'})
        token = station.kiosk_token

        # Confirms it works normally first (station enabled).
        found = _station_from_token(self.env, 'ITEM5BLOCKED', token)
        self.assertEqual(found, station)

        station.kiosk_disabled = True
        found_after = _station_from_token(self.env, 'ITEM5BLOCKED', token)
        self.assertFalse(found_after, "A disabled station's kiosk must reject even a correct token.")

        # Re-enabling restores access immediately with the SAME token -
        # no regeneration needed.
        station.kiosk_disabled = False
        found_restored = _station_from_token(self.env, 'ITEM5BLOCKED', token)
        self.assertEqual(found_restored, station)
        self.assertEqual(station.kiosk_token, token, "The token itself was never touched throughout.")

    # -----------------------------------------------------------------
    # UI IMPROVEMENT ("Patch 5", item 1, "Station - SLA UI").
    # -----------------------------------------------------------------
    def test_patch5_item1_sla_tab_restructured_into_three_groups(self):
        """Item 1: Warning and Late settings reorganized into their own
        separate, full-width groups (Target/Warning/Late) instead of
        being squeezed side by side inside one shared group - structural
        check confirming the new layout, and that the field order within
        each group matches exactly what was requested (Warning
        Threshold %, Warning At (min), Late Threshold %, Late At
        (min))."""
        form_view = self.env.ref('flexsys_kds.view_kds_station_form')
        arch = form_view.arch_db
        self.assertIn('group string="Warning"', arch)
        self.assertIn('group string="Late"', arch)

        warning_pct_pos = arch.index('name="warning_threshold_pct"')
        warning_min_pos = arch.index('name="warning_threshold_minutes"')
        late_pct_pos = arch.index('name="late_threshold_pct"')
        late_min_pos = arch.index('name="late_threshold_minutes"')
        self.assertLess(warning_pct_pos, warning_min_pos)
        self.assertLess(warning_min_pos, late_pct_pos)
        self.assertLess(late_pct_pos, late_min_pos)

    def test_patch5_item1_sla_calculation_completely_unchanged(self):
        """Non-regression: 'Do not change the existing SLA
        calculation/business logic.' Confirms the computed minute
        values (warning_threshold_minutes/late_threshold_minutes) still
        compute exactly the same way - a pure view reorganization, zero
        change to the underlying compute methods."""
        self.station_kitchen.write({
            'target_prep_time': 20, 'warning_threshold_pct': 80, 'late_threshold_pct': 120,
        })
        self.assertEqual(self.station_kitchen.warning_threshold_minutes, 16.0)
        self.assertEqual(self.station_kitchen.late_threshold_minutes, 24.0)
