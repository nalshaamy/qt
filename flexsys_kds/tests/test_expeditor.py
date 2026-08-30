# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import FlexSysKdsTestCommon


@tagged('post_install', '-at_install')
class TestExpeditor(FlexSysKdsTestCommon):
    """Audit finding "Expeditor/Packing Workflow" - the final Phase 1
    item. `station_expeditor` is created here, scoped to this test
    class's own fixtures only (each test class gets its own fresh
    `cls.company` via TransactionCase's per-class isolation) -
    deliberately NOT added to the shared common.py fixtures, since
    `kds.order.expeditor_enabled` is computed per-company: adding an
    is_expeditor station to the shared company would silently change
    ~130 existing tests in every *other* file to route through this new
    flow instead of the direct-to-Completed behavior they were written
    against.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls._make_kds_user('exp_admin', cls.group_administrator)
        cls.station_expeditor = cls.env['kds.station'].create({
            'name': 'Test Expeditor', 'code': 'TESTEXPEDITOR',
            'target_prep_time': 5, 'is_expeditor': True,
        })
        # REAL BUG FIX, confirmed live on Odoo.sh (test suite stopped
        # after 5 errors in this file): these two helpers used to create
        # each order's lines with no station_id (via the shared
        # _make_order()), then immediately `write({'station_id': ...})`
        # on the already-created line - but station_id has been in
        # KDS_LINE_PROTECTED_FIELDS for a long time (kds_order_line.py),
        # so a raw write() without kds_workflow_write=True context
        # correctly raises AccessError. This worked at some earlier
        # point (before that protection existed or was tightened) and
        # was never updated afterward - production-code protection
        # itself was never the bug, the test fixture was.
        # Fixed via the actual supported mechanism instead of a bypass:
        # product.kds_station_id (route_product()'s own first fallback
        # level, a real production feature - "the product's own default
        # station") is set once here, so create()'s own auto-routing
        # (which runs unconditionally whenever station_id isn't already
        # in the create vals - see kds_order_line.py's create()
        # override) assigns the correct station naturally, with zero
        # need for any write() afterward, protected or otherwise.
        # cls.product_burger/product_cappuccino are fresh, class-scoped
        # copies (created in FlexSysKdsTestCommon.setUpClass(), called
        # just above via super()) - safe to configure here without
        # leaking into any other test file's own separate product
        # instances.
        cls.product_burger.kds_station_id = cls.station_kitchen
        cls.product_cappuccino.kds_station_id = cls.station_coffee

    def _order_two_stations(self):
        """Kitchen (Burger) + Coffee (Cappuccino), matching the audit's
        own worked example. Routes automatically via each product's own
        kds_station_id default (set in setUpClass above) - no direct
        station_id write needed."""
        return self._make_order(
            [(self.product_burger, 1), (self.product_cappuccino, 1)]).with_user(self.admin)

    def _order(self):
        return self._make_order([(self.product_burger, 1)]).with_user(self.admin)

    # 1. Expeditor enabled -------------------------------------------------
    def test_expeditor_enabled_when_company_has_expeditor_station(self):
        order = self._order()
        self.assertTrue(order.expeditor_enabled)

    # 2. Expeditor disabled -------------------------------------------------
    def test_expeditor_disabled_falls_back_to_direct_ready_then_complete(self):
        """The system must continue supporting restaurants that don't use
        Expeditor/Packing - checked by deactivating the only expeditor
        station and confirming the order just reaches Ready normally,
        with no Packing task, then completes with a plain manual
        Complete click (no intermediate Packing step, but Complete is
        still a deliberate step - see the v5.4 design reversal)."""
        self.station_expeditor.active = False
        order = self._order()
        self.assertFalse(order.expeditor_enabled)
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_ready()
        # DESIGN REVERSAL (v5.4): Ready no longer auto-completes at all,
        # with or without Expeditor - Complete is always a deliberate,
        # separate step now. Still, without Expeditor there's no
        # intermediate Packing task - a plain "Complete" click is all
        # that's needed, exactly the simpler flow that existed before
        # Expeditor was built.
        self.assertEqual(order.state, 'ready',
                          "With no active expeditor station, the order should still just "
                          "reach Ready - no Packing task activates.")
        self.assertFalse(order.expeditor_task_ids)
        order.line_ids.action_complete()
        self.assertEqual(order.state, 'completed')

    # 3. Single production station -------------------------------------------------
    def test_single_station_all_ready_activates_expeditor(self):
        order = self._order()
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_ready()
        self.assertEqual(
            order.state, 'ready',
            "Production Ready must not equal Final Order Ready when Expeditor is enabled - "
            "the order must NOT auto-complete.")
        self.assertEqual(len(order.expeditor_task_ids), 1)
        task = order.expeditor_task_ids
        self.assertEqual(task.state, 'waiting')
        self.assertEqual(task.station_id, self.station_expeditor)
        self.assertTrue(task.available_time)

    # 4. Multiple production stations -------------------------------------------------
    def test_multi_station_packing_available_only_after_both_ready(self):
        order = self._order_two_stations()
        order.action_accept()
        order.line_ids.action_start()

        # Only Kitchen ready - Bar (Coffee) still Preparing.
        order.line_ids.filtered(lambda l: l.station_id == self.station_kitchen).action_ready()
        self.assertFalse(order.expeditor_task_ids,
                          "Packing must NOT start while a required production line is "
                          "still Preparing.")
        self.assertNotEqual(order.state, 'ready')

        # Now Coffee also ready -> Packing becomes available.
        order.line_ids.filtered(lambda l: l.station_id == self.station_coffee).action_ready()
        self.assertEqual(order.state, 'ready')
        self.assertEqual(len(order.expeditor_task_ids), 1)

    # 5 & 6 covered by test 4 above (all ready / one still preparing).

    # 7. Cancelled production line -------------------------------------------------
    def test_cancelled_production_line_does_not_block_expeditor_readiness(self):
        order = self._order_two_stations()
        order.action_accept()
        order.line_ids.filtered(lambda l: l.station_id == self.station_kitchen).action_start()
        coffee_line = order.line_ids.filtered(lambda l: l.station_id == self.station_coffee)
        coffee_line.action_cancel(reason='out of stock', bypass_check=True)

        kitchen_line = order.line_ids.filtered(lambda l: l.station_id == self.station_kitchen)
        kitchen_line.action_ready()

        self.assertEqual(
            order.state, 'ready',
            "With the only other line Cancelled, the order must be eligible for Packing.")
        self.assertEqual(len(order.expeditor_task_ids), 1)

    # 8. Reopened production line -------------------------------------------------
    def test_reopened_production_line_cancels_active_packing_task(self):
        order = self._order()
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_ready()
        task = order.expeditor_task_ids
        self.assertEqual(task.state, 'waiting')

        # Reopen the (only) production line back to Preparing (override, Administrator).
        order.line_ids.action_start(bypass_check=False)

        task.invalidate_recordset()
        self.assertEqual(task.state, 'cancelled',
                          "An active Packing task must be cancelled once required "
                          "production work is active again.")
        order.invalidate_recordset()
        self.assertEqual(order.state, 'preparing',
                          "The order must be pulled back out of 'ready' - it must not stay "
                          "Ready while a required production line is Preparing again.")

    def test_reopen_after_packing_already_started_still_cancels_it(self):
        """Safe behavior for an already-started Packing task, per the
        audit's explicit callout - not just a still-Waiting one."""
        order = self._order()
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_ready()
        task = order.expeditor_task_ids
        task.action_start()  # someone actually started packing
        self.assertEqual(task.state, 'packing')

        order.line_ids.action_start(bypass_check=False)  # production line reopened

        task.invalidate_recordset()
        self.assertEqual(task.state, 'cancelled')

    def test_final_ready_impossible_while_production_line_is_preparing_again(self):
        order = self._order()
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_ready()
        task = order.expeditor_task_ids
        order.line_ids.action_start(bypass_check=False)  # reopen

        task.invalidate_recordset()
        with self.assertRaises(UserError):
            # The cancelled task cannot be pushed to Ready/Completed -
            # confirms the system doesn't allow finalizing stale work.
            task.action_ready()

    # 9. POS Delta Updates -------------------------------------------------
    def test_new_production_line_after_packing_available_cancels_stale_task(self):
        order = self._order()
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_ready()
        task = order.expeditor_task_ids
        self.assertEqual(task.state, 'waiting')

        # A new production line arrives (simulating a POS delta-sync add).
        self.env['kds.order.line'].create({
            'order_id': order.id, 'product_id': self.product_cappuccino.id, 'qty': 1,
            'station_id': self.station_coffee.id,
        })

        task.invalidate_recordset()
        self.assertEqual(
            task.state, 'cancelled',
            "The old Packing task must be cancelled - it must not be finalized "
            "while new production work is pending.")
        order.invalidate_recordset()
        self.assertFalse(order.is_expeditor_ready)

    # 10. POS Cancellation during Packing -------------------------------------------------
    def test_pos_cancellation_during_packing_cancels_the_active_task(self):
        order = self._order()
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_ready()
        task = order.expeditor_task_ids
        task.action_start()
        self.assertEqual(task.state, 'packing')

        order.action_cancel()

        self.assertEqual(order.state, 'cancelled')
        task.invalidate_recordset()
        self.assertEqual(task.state, 'cancelled',
                          "No ghost Packing task may remain active on a cancelled order.")

    # 11. Expeditor workflow (states) -------------------------------------------------
    def test_expeditor_task_full_happy_path(self):
        order = self._order()
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_ready()
        task = order.expeditor_task_ids
        self.assertEqual(task.state, 'waiting')

        task.action_start()
        self.assertEqual(task.state, 'packing')
        self.assertTrue(task.start_time)

        task.action_ready()
        self.assertEqual(task.state, 'ready')
        self.assertTrue(task.ready_time)

    # 12. Packing completion -------------------------------------------------
    def test_expeditor_completion_finalizes_the_order(self):
        order = self._order()
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_ready()
        task = order.expeditor_task_ids
        task.action_start()
        task.action_ready()

        task.action_complete()

        self.assertEqual(task.state, 'completed')
        self.assertTrue(task.completion_time)
        order.invalidate_recordset()
        self.assertEqual(order.state, 'completed',
                          "Completing the Expeditor task must finalize the parent order.")
        # REAL BUG FIX, confirmed live on Odoo.sh ("Expeditor test still
        # expects all production lines to become COMPLETED" - inconsistent
        # with the new station-level lifecycle): production lines under
        # Expeditor are only ever expected to reach 'ready' and stop
        # there - final completion has always been the Packing task's
        # own responsibility, not each production station's (see
        # kds_order.py::_finalize_via_expeditor()'s own docstring for the
        # full explanation). Forcing them to 'completed' here too would
        # mean rewriting genuine production history to satisfy an old
        # assertion, not reflecting what the intended business workflow
        # actually does - explicitly not done, per that same guidance.
        for line in order.line_ids:
            line.invalidate_recordset()
            self.assertEqual(
                line.state, 'ready',
                "Production lines remain at their genuine 'ready' state, never "
                "force-rewritten to 'completed', when the order finalizes via "
                "Expeditor - completion there is the Packing task's own event, "
                "not each production line's own history being altered.")

    def test_packing_duration_computed_from_start_to_ready(self):
        order = self._order()
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_ready()
        task = order.expeditor_task_ids
        task.action_start()
        task.action_ready()
        self.assertGreaterEqual(task.packing_duration, 0.0)

    # 13. Audit Events -------------------------------------------------
    def test_expeditor_activation_creates_an_audit_event(self):
        order = self._order()
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_ready()
        events = self.env['kds.event'].search([
            ('order_id', '=', order.id), ('note', 'like', 'Expeditor/Packing task created%'),
        ])
        self.assertTrue(events)

    def test_expeditor_transitions_are_audit_logged(self):
        order = self._order()
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_ready()
        task = order.expeditor_task_ids
        task.action_start()
        events = self.env['kds.event'].search([
            ('order_id', '=', order.id),
            ('event_type', '=', 'status_changed'),
            ('new_value', '=', 'expeditor_packing'),
        ])
        self.assertTrue(events, "Every Expeditor transition must be audit-logged, matching "
                                 "the 'State Transition Consistency' fix applied module-wide.")

    # 14. Realtime notification trigger -------------------------------------------------
    def test_expeditor_activation_triggers_a_notification(self):
        # Full realtime delivery (bus.bus) isn't practically assertable in
        # a plain TransactionCase without a live longpolling client -
        # this confirms the notification call path itself doesn't raise
        # and that kds.station's own notify hook is reachable, which is
        # the same level of coverage the rest of this module's realtime
        # notification code gets elsewhere.
        order = self._order()
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_ready()  # should not raise while notifying the expeditor station
        self.assertTrue(order.expeditor_task_ids)

    # 15. Multi-company isolation -------------------------------------------------
    def test_expeditor_enabled_is_scoped_to_the_orders_own_company(self):
        # station_expeditor belongs to the default test company - an
        # order for company_b (from the shared fixtures) must NOT see it.
        order_b = self.env['kds.order'].create({
            'source': 'pos', 'order_type': 'dine_in', 'company_id': self.company_b.id,
        })
        self.assertFalse(
            order_b.expeditor_enabled,
            "A company with no is_expeditor station of its own must not be treated as "
            "Expeditor-enabled just because a *different* company has one.")

    # 16. Station/User permissions -------------------------------------------------
    def test_operator_assigned_to_expeditor_station_can_act(self):
        user = self._make_kds_user('exp_op', self.group_operator, self.station_expeditor)
        order = self._order()
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_ready()
        task = order.expeditor_task_ids.with_user(user)
        task.action_start()  # should not raise
        self.assertEqual(task.state, 'packing')

    def test_operator_not_assigned_to_expeditor_station_is_denied(self):
        user = self._make_kds_user('exp_op_wrong_station', self.group_operator, self.station_kitchen)
        order = self._order()
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_ready()
        task = order.expeditor_task_ids.with_user(user)
        with self.assertRaises(AccessError):
            task.action_start()

    def test_expeditor_bypass_check_operates_with_trusted_environment(self):
        """Same fix as kds_order_line.py's/kds_order.py's own
        bypass_check (dev request "Odoo.sh Runtime Failures Round 2",
        item 1) - proactively found and fixed here too while auditing
        the whole module for the same pattern, not from a reported
        failure specifically on this model. Confirms
        kds_expeditor_task.py's own _transition() also switches to a
        sudo'd recordset when bypass_check=True, exactly like the order/
        line-level methods - the same Operator, wrong station, denied
        without bypass and succeeding with it."""
        user = self._make_kds_user('exp_op_bypass', self.group_operator, self.station_kitchen)
        order = self._order()
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_ready()
        task = order.expeditor_task_ids.with_user(user)
        with self.assertRaises(AccessError):
            task.action_start(bypass_check=False)
        task.action_start(bypass_check=True)  # should not raise
        self.assertEqual(task.state, 'packing')

    def test_expeditor_cancel_requires_supervisor(self):
        # 'cancel' is Supervisor+ per ACTION_MIN_GROUP, reused as-is by
        # the Expeditor task's own _kds_check_action (inherited from the
        # shared mixin) - an Operator must not be able to cancel a
        # Packing task directly.
        user = self._make_kds_user('exp_op_cancel', self.group_operator, self.station_expeditor)
        order = self._order()
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_ready()
        task = order.expeditor_task_ids.with_user(user)
        with self.assertRaises(AccessError):
            task.action_cancel()

    # -----------------------------------------------------------------
    # Final Phase 1 Audit finding 2 (MEDIUM/FINAL VERIFICATION):
    # "Expeditor Completion Safety Check" - a server-side guard at the
    # moment of completion itself, protecting against stale UI,
    # concurrent requests, or race conditions - not relying only on the
    # earlier reconciliation that already runs when a line reopens.
    # -----------------------------------------------------------------
    def test_completion_rejected_if_production_line_reopened_just_before(self):
        """Acceptance criteria as stated: if a production line returns to
        Preparing immediately before an Expeditor completion request, the
        server must reject/block final order completion."""
        order = self._order()
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_ready()
        task = order.expeditor_task_ids
        task.action_start()
        task.action_ready()
        self.assertEqual(task.state, 'ready')

        # Simulate the race: production reopens via a DIFFERENT path
        # (bypassing the normal reconciliation this task would otherwise
        # already have gone through) - a raw state write standing in for
        # "some other concurrent request already reopened it a moment
        # ago, and this stale completion request is only now arriving."
        # with_context(kds_workflow_write=True): bypasses this module's
        # own write-protection guard (KDS_LINE_PROTECTED_FIELDS) - needed
        # here purely to simulate the external event for this test, not
        # something a real caller would ever legitimately do.
        order.line_ids.with_context(kds_workflow_write=True).write({'state': 'preparing'})

        with self.assertRaises(UserError):
            task.action_complete()

    def test_completion_succeeds_when_production_genuinely_still_ready(self):
        # Regression check: the new guard must not block the normal,
        # correct path.
        order = self._order()
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_ready()
        task = order.expeditor_task_ids
        task.action_start()
        task.action_ready()

        task.action_complete()  # should not raise

        self.assertEqual(task.state, 'completed')
        order.invalidate_recordset()
        self.assertEqual(order.state, 'completed')

    def test_reconcile_cron_stops_at_ready_when_expeditor_enabled(self):
        """Guard preservation, explicit (dev request "Odoo.sh Runtime
        Failures - Final", item 2, "preserve all current guards...
        Expeditor/Packing requirements"): the reconciliation cron's own
        auto-complete step (kds_order.py::_cron_reconcile_stuck_orders())
        must NEVER fire for an Expeditor-enabled order - action_ready()
        activates the Packing task instead of landing on plain 'ready',
        and completion is Expeditor's own responsibility from there, not
        this cron's. Confirms the cron correctly stops at 'ready' with
        an active task, exactly like the non-cron path already does -
        this test's own company has station_expeditor active (see this
        class's own setUpClass), unlike TestWorkflow's shared company."""
        order = self._order_two_stations()
        order.action_accept()
        order.line_ids.action_start()
        # Same stuck-order simulation as
        # test_reconcile_cron_pushes_a_stuck_ready_order_forward in
        # test_workflow.py - force both lines Ready directly, bypassing
        # the normal cascade, so the order itself never advances.
        order.line_ids.with_context(kds_workflow_write=True).write({'state': 'ready'})
        self.assertEqual(order.state, 'preparing')
        self.assertTrue(order.is_expeditor_ready)
        self.assertTrue(order.expeditor_enabled)

        self.env['kds.order']._cron_reconcile_stuck_orders()

        order.invalidate_recordset()
        self.assertEqual(
            order.state, 'ready',
            "An Expeditor-enabled order must stop at Ready, with the Packing task "
            "activated - the reconciliation cron must never auto-complete it.")
        self.assertTrue(
            order.expeditor_task_ids.filtered(lambda t: t.state not in ('cancelled', 'completed')),
            "The Packing task must have been activated, same as the normal action_ready() path.")

    # -----------------------------------------------------------------
    # Dev request "Odoo.sh BUG-07 Integration Fixes": Expeditor
    # finalization was failing after the BUG-07 guard was added to
    # action_complete() - fixed with a dedicated _finalize_via_expeditor()
    # path on kds.order (see that method's own docstring for the full
    # explanation). These two tests explicitly name and cover both
    # required scenarios from the dev request's own regression matrix.
    # -----------------------------------------------------------------
    def test_bug07_expeditor_enabled_finalizes_without_completing_production_lines_individually(self):
        """Expeditor Enabled scenario, explicit: Production Stations
        READY -> Expeditor/Packing -> Expeditor COMPLETE -> Overall
        Order COMPLETED, without violating the BUG-07 guard - and
        without ever force-completing each production line
        individually (they stay at 'ready', per "do not force every
        production station line to become COMPLETED... unless that is
        the intended lifecycle" - it explicitly isn't, here)."""
        order = self._order_two_stations()
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_ready()
        self.assertTrue(order.expeditor_enabled)
        for line in order.line_ids:
            self.assertEqual(
                line.state, 'ready',
                "Production lines must stay at Ready under Expeditor - never "
                "individually force-completed.")
        task = order.expeditor_task_ids
        task.action_start()
        task.action_ready()

        task.action_complete()  # should not raise - this is the real regression check

        order.invalidate_recordset()
        self.assertEqual(task.state, 'completed')
        self.assertEqual(order.state, 'completed')
        for line in order.line_ids:
            line.invalidate_recordset()
            self.assertEqual(
                line.state, 'ready',
                "Even after the whole order is Completed via Expeditor, each "
                "production line's own state remains 'ready', not force-rewritten "
                "to 'completed' - completion here is the Expeditor task's own "
                "responsibility, never each production station's.")

    # -----------------------------------------------------------------
    # TEST SUITE RESET ("Test Suite Reset & Cleanup" project, Phase 7 -
    # test_expeditor.py Duplicate Density Review): removed
    # test_bug07_expeditor_disabled_each_station_completes_independently
    # (was here - Expeditor explicitly deactivated, two production
    # stations each completing independently, order reaching Completed
    # only after the final one). Confirmed, by a direct side-by-side
    # comparison of both test bodies (not merely trusting this test's
    # own comment claiming duplication), that this scenario, this
    # sequence of actions, and this exact expected result are already
    # fully proven by
    # test_workflow.py::test_bug07_three_station_order_completes_independently_per_station
    # - with no Expeditor-specific layer exercised here at all (the
    # station is explicitly deactivated precisely to fall back to the
    # same plain per-station completion path that other test already
    # covers, now with three stations instead of two, superset
    # coverage). No coverage lost.
    # -----------------------------------------------------------------

    def test_activate_expeditor_task_fail_safe_completes_via_real_line_workflow(self):
        """REAL BUG FIX, found via a proactive sweep for hidden
        regressions (not a reported failure): _activate_expeditor_task()
        has a fail-safe for the narrow race where expeditor_enabled was
        true when action_ready() checked it, but the only active
        Expeditor station got deactivated before this method actually
        ran - "complete normally rather than leaving the order stuck at
        Ready forever". That fail-safe used to call the order-level
        action_complete() directly - correct before BUG-07, but that
        method's own new guard (is_fully_completed) rejects it, since
        lines here are freshly 'ready', never yet individually
        completed. Fixed to route through the real, per-line
        action_complete() instead (see kds_order.py's own updated
        comment for the full explanation). Simulated here by calling
        _activate_expeditor_task() directly on an order with no active
        Expeditor station at all - the same condition the fail-safe's
        own branch is designed for, even though the literal "narrow
        window" race can't be reproduced in a synchronous test."""
        self.station_expeditor.active = False
        order = self._order()
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_ready()
        self.assertEqual(order.line_ids.state, 'ready')
        self.assertFalse(order.expeditor_enabled)

        order._activate_expeditor_task(bypass_check=True)  # should not raise

        order.invalidate_recordset()
        self.assertEqual(
            order.state, 'completed',
            "The fail-safe must still complete the order normally, through the real "
            "line-level workflow, not get stuck behind the BUG-07 guard.")
        self.assertEqual(order.line_ids.state, 'completed')
