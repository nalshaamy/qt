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
        order.action_complete()
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
        self.assertTrue(all(l.state == 'completed' for l in order.line_ids))

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
