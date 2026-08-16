# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import FlexSysKdsTestCommon


@tagged('post_install', '-at_install')
class TestWorkflow(FlexSysKdsTestCommon):
    """Exercises ORDER_TRANSITIONS / LINE_TRANSITIONS directly. Uses an
    Administrator user throughout so permission checks (covered separately
    in test_permissions.py) never interfere with what's being tested here:
    whether a given state->state move is *legal*, independent of who's
    asking."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls._make_kds_user('wf_admin', cls.group_administrator)

    def _order(self):
        order = self._make_order([(self.product_burger, 2)])
        self._route_line_to_station(order.line_ids, self.station_kitchen)
        return order.with_user(self.admin)

    def test_full_happy_path_order(self):
        order = self._order()
        self.assertEqual(order.state, 'new')
        order.action_accept()
        self.assertEqual(order.state, 'accepted')
        order.action_start_preparing()
        self.assertEqual(order.state, 'preparing')
        order.action_ready()
        # DESIGN REVERSAL (v5.4): Ready no longer auto-completes -
        # Complete is a separate, deliberate manual step again.
        self.assertEqual(order.state, 'ready')
        order.action_complete()
        self.assertEqual(order.state, 'completed')

    def test_cannot_skip_states_forward(self):
        order = self._order()
        # new -> ready directly is not in ORDER_TRANSITIONS['new']
        with self.assertRaises(UserError):
            order.action_ready()

    def test_cannot_act_on_terminal_cancelled_order(self):
        order = self._order()
        order.action_cancel()
        self.assertEqual(order.state, 'cancelled')
        with self.assertRaises(UserError):
            order.action_accept()

    def test_hold_and_resume(self):
        order = self._order()
        order.action_accept()
        order.action_hold()
        self.assertEqual(order.state, 'on_hold')
        order.action_accept()  # on_hold -> accepted is allowed
        self.assertEqual(order.state, 'accepted')

    def test_reopen_completed_order_via_dedicated_action(self):
        # DESIGN REVERSAL (v5.4): Complete is a separate manual step
        # again - action_reopen() still accepts both 'ready' and
        # 'completed' as valid starting states.
        order = self._order()
        order.action_accept()
        order.action_start_preparing()
        order.action_ready()
        order.action_complete()
        self.assertEqual(order.state, 'completed')
        order.action_reopen()
        self.assertEqual(order.state, 'preparing')

    def test_reopen_only_allowed_from_ready_or_completed(self):
        order = self._order()  # still 'new'
        with self.assertRaises(UserError):
            order.action_reopen()

    def test_direct_override_transition_requires_override_permission(self):
        """Going completed -> preparing via the *generic* action (not the
        dedicated action_reopen helper) is treated as an override and
        requires the 'override' action permission. Documented distinction:
        action_reopen() is the intended, Supervisor-level API for this;
        calling action_start_preparing() directly on a Completed order is
        the harder-permission "edge case" path. See the ORDER_OVERRIDE_TRANSITIONS
        comment in models/kds_order.py."""
        order = self._order()
        order.action_accept()
        order.action_start_preparing()
        order.action_ready()
        order.action_complete()
        # DESIGN REVERSAL (v5.4): Complete is a separate manual step
        # again, called explicitly above.
        self.assertEqual(order.state, 'completed')
        # Admin has 'override' permission, so this succeeds:
        order.action_start_preparing()
        self.assertEqual(order.state, 'preparing')

    def test_line_full_happy_path(self):
        order = self._order()
        line = order.line_ids
        self.assertEqual(line.state, 'new')
        line.action_accept()
        self.assertEqual(line.state, 'accepted')
        line.action_start()
        self.assertEqual(line.state, 'preparing')
        line.action_ready()
        # DESIGN REVERSAL (v5.4): is_expeditor_ready still cascades up to
        # order.action_ready() (order reaches 'ready'), but that no
        # longer auto-completes - the line genuinely rests at 'ready'
        # now, not force-written to 'completed', until someone explicitly
        # completes the order.
        self.assertEqual(line.state, 'ready')

    def test_line_cannot_skip_states(self):
        order = self._order()
        line = order.line_ids
        with self.assertRaises(UserError):
            line.action_ready()  # new -> ready is illegal

    def test_line_start_bumps_order_to_preparing(self):
        order = self._order()
        line = order.line_ids
        self.assertEqual(order.state, 'new')
        line.action_start()
        self.assertEqual(order.state, 'preparing',
                          "Starting the first line should move the order forward as a side effect.")

    def test_line_start_stamps_order_preparation_start_time(self):
        """Real bug fixed: the order's own preparation_start_time (Timing
        tab on the order form) used to stay blank forever when the order
        reached 'preparing' via the normal KDS-screen line-start flow
        (_force_state), even though action_start_preparing() called
        directly on the order always stamped it correctly. Both paths
        must now stamp it."""
        order = self._order()
        line = order.line_ids
        self.assertFalse(order.preparation_start_time)
        line.action_start()
        self.assertTrue(order.preparation_start_time,
                         "Order's preparation_start_time must be stamped when a line "
                         "starts and pushes the order into 'preparing' as a side effect.")

    def test_all_lines_ready_marks_order_completed(self):
        order = self._make_order([(self.product_burger, 1), (self.product_cappuccino, 1)])
        self._route_line_to_station(order.line_ids, self.station_kitchen)
        order = order.with_user(self.admin)
        for line in order.line_ids:
            line.action_start()
        self.assertEqual(order.state, 'preparing')
        for line in order.line_ids:
            line.action_ready()
        # DESIGN REVERSAL (v5.4): reaching Ready (every non-cancelled
        # line Ready) advances the order to 'ready' but no longer
        # auto-completes it - Complete is a separate, deliberate step.
        self.assertEqual(order.state, 'ready',
                          "Order should auto-advance to Ready once every "
                          "non-cancelled line is Ready.")
        order.action_complete()
        self.assertEqual(order.state, 'completed')

    def test_cannot_cancel_completed_line(self):
        order = self._order()
        line = order.line_ids
        line.action_accept()
        line.action_start()
        line.action_ready()
        # DESIGN REVERSAL (v5.4): the order no longer auto-completes on
        # its own - explicitly completing it here is what force-writes
        # this line to 'completed' (action_complete()'s own line
        # cascade), matching what this test is actually about.
        line.order_id.action_complete()
        self.assertEqual(line.state, 'completed')
        with self.assertRaises(UserError):
            line.action_cancel(reason='test')

    # -----------------------------------------------------------------
    # Audit finding "POS Cancellation Propagation" (IMPORTANT) - surfaced
    # this same gap in action_cancel() itself, affecting the existing
    # manual backend Cancel button too, not just POS-triggered
    # cancellation (covered separately in test_pos_sync.py): cancelling
    # an order used to leave its lines in whatever state they were
    # already in, instead of cascading the cancellation down.
    # -----------------------------------------------------------------
    def test_action_cancel_cascades_to_active_lines(self):
        order = self._make_order(
            [(self.product_burger, 1), (self.product_cappuccino, 1)]).with_user(self.admin)
        self._route_line_to_station(order.line_ids, self.station_kitchen)
        order.action_accept()
        order.line_ids.action_start()
        self.assertTrue(all(l.state == 'preparing' for l in order.line_ids))

        order.action_cancel()

        self.assertEqual(order.state, 'cancelled')
        self.assertTrue(
            all(l.state == 'cancelled' for l in order.line_ids),
            "Cancelling the order must cascade to every active line, not leave them "
            "stuck in whatever state they were already in.")

    def test_action_cancel_preserves_completed_line_history(self):
        """The selective part of the fix: a line that already finished
        (Completed) must NOT be retroactively cancelled just because the
        order gets cancelled afterward - preserves production history.
        Realistic path to this: complete an order, reopen it (admin
        override), then cancel it - the line stays 'completed' through
        reopen (nothing resets it), so cancelling the reopened order must
        not touch it."""
        order = self._order()  # single line, qty=2
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_ready()
        order.action_complete()  # DESIGN REVERSAL (v5.4): explicit step now
        self.assertEqual(order.state, 'completed')
        self.assertEqual(order.line_ids.state, 'completed')

        order.action_reopen()
        self.assertEqual(order.state, 'preparing')
        self.assertEqual(order.line_ids.state, 'completed',
                          "Reopening doesn't touch line state on its own.")

        order.action_cancel()

        self.assertEqual(order.state, 'cancelled')
        self.assertEqual(
            order.line_ids.state, 'completed',
            "A line that already finished must keep its history, not be cancelled "
            "retroactively just because the reopened order got cancelled afterward.")

    # -----------------------------------------------------------------
    # Audit finding "Auto Accept" (MEDIUM): kds.station.auto_accept_orders
    # existed as configuration with no actual runtime effect until now.
    # -----------------------------------------------------------------
    def test_auto_accept_on_immediately_accepts_new_line(self):
        # REAL BUG FIX, confirmed at runtime (dev request "Runtime
        # Regression Fix Package", BUG-01): Auto Accept previously
        # stopped at 'accepted', which is displayed identically to 'new'
        # everywhere in the UI (same NEW tab bucket, same START button) -
        # the ticket looked completely unaffected by the setting. The
        # dev request's own acceptance test settles what "Auto Accept"
        # actually means operationally: straight through to 'preparing',
        # no manual click at all.
        self.station_kitchen.auto_accept_orders = True
        self.product_burger.kds_station_id = self.station_kitchen
        order = self.env['kds.order'].create({'source': 'pos', 'order_type': 'dine_in'})
        line = self.env['kds.order.line'].create({
            'order_id': order.id, 'product_id': self.product_burger.id, 'qty': 1,
        })
        self.assertEqual(line.station_id, self.station_kitchen)
        self.assertEqual(line.state, 'preparing',
                          "A line routed to a station with Auto Accept on must reach "
                          "Preparing automatically, with no manual Start click needed - "
                          "landing at 'accepted' and stopping there is NOT sufficient, "
                          "since 'accepted' is displayed identically to 'new' everywhere "
                          "else in this module.")
        self.assertTrue(line.accepted_time)
        self.assertTrue(line.preparation_start_time)

    def test_auto_accept_off_leaves_line_new(self):
        self.assertFalse(self.station_kitchen.auto_accept_orders)  # default
        self.product_burger.kds_station_id = self.station_kitchen
        order = self.env['kds.order'].create({'source': 'pos', 'order_type': 'dine_in'})
        line = self.env['kds.order.line'].create({
            'order_id': order.id, 'product_id': self.product_burger.id, 'qty': 1,
        })
        self.assertEqual(line.state, 'new')
        self.assertFalse(line.accepted_time)

    def test_auto_accept_mixed_station_settings(self):
        """Multi-station order, mixed settings - only the line routed to
        the Auto-Accept-enabled station should be accepted; the other
        must stay New."""
        self.station_kitchen.auto_accept_orders = True
        self.station_coffee.auto_accept_orders = False
        self.product_burger.kds_station_id = self.station_kitchen
        self.product_cappuccino.kds_station_id = self.station_coffee

        order = self.env['kds.order'].create({'source': 'pos', 'order_type': 'dine_in'})
        line_burger = self.env['kds.order.line'].create({
            'order_id': order.id, 'product_id': self.product_burger.id, 'qty': 1,
        })
        line_coffee = self.env['kds.order.line'].create({
            'order_id': order.id, 'product_id': self.product_cappuccino.id, 'qty': 1,
        })
        self.assertEqual(line_burger.state, 'preparing')
        self.assertEqual(line_coffee.state, 'new')

    def test_auto_accept_creates_exactly_one_audit_event(self):
        self.station_kitchen.auto_accept_orders = True
        self.product_burger.kds_station_id = self.station_kitchen
        order = self.env['kds.order'].create({'source': 'pos', 'order_type': 'dine_in'})
        line = self.env['kds.order.line'].create({
            'order_id': order.id, 'product_id': self.product_burger.id, 'qty': 1,
        })
        events = self.env['kds.event'].search([
            ('order_id', '=', order.id),
            ('event_type', '=', 'status_changed'),
            ('new_value', '=', 'accepted'),
        ])
        self.assertEqual(len(events), 1,
                          "Auto Accept must log exactly one status-changed audit event for "
                          "the Accepted step, not zero (the old gap) and not duplicated.")
        preparing_events = self.env['kds.event'].search([
            ('order_id', '=', order.id),
            ('event_type', '=', 'status_changed'),
            ('new_value', '=', 'preparing'),
        ])
        self.assertEqual(len(preparing_events), 1,
                          "BUG-01 fix: Auto Accept now also chains through to Preparing - "
                          "must log its own distinct audit event for that step too, not "
                          "just the Accepted one.")

    def test_auto_accept_never_raises_since_new_to_preparing_is_always_legal(self):
        # New -> Accepted -> Preparing is unconditionally valid in
        # LINE_TRANSITIONS, so auto-accepting on creation should never be
        # able to raise - this is really just confirming create() doesn't
        # itself blow up.
        self.station_kitchen.auto_accept_orders = True
        self.product_burger.kds_station_id = self.station_kitchen
        order = self.env['kds.order'].create({'source': 'pos', 'order_type': 'dine_in'})
        line = self.env['kds.order.line'].create({
            'order_id': order.id, 'product_id': self.product_burger.id, 'qty': 1,
        })  # should not raise
        self.assertEqual(line.state, 'preparing')

    def test_line_manual_accept_also_stamps_accepted_time(self):
        """Separate bug found while implementing Auto Accept: line-level
        action_accept() never passed a timestamp to _line_transition at
        all (unlike action_start/action_ready, which correctly do) - a
        manually-accepted line's own Accepted timestamp was silently
        always blank, independent of Auto Accept."""
        order = self._order()
        line = order.line_ids
        self.assertFalse(line.accepted_time)
        line.action_accept()
        self.assertTrue(line.accepted_time)

    # -----------------------------------------------------------------
    # Found via a live pilot report: an order can end up with every
    # line genuinely Ready (is_expeditor_ready True) while its own
    # aggregate state never advanced - a plausible race condition
    # between near-simultaneous line actions, where the cascade's own
    # "last line to become ready pushes the order forward" check never
    # got the chance to observe every sibling line's write. This
    # safety-net cron self-heals that, independent of pinning down the
    # exact root cause.
    # -----------------------------------------------------------------
    def test_reconcile_cron_pushes_a_stuck_ready_order_forward(self):
        order = self._make_order(
            [(self.product_burger, 1), (self.product_cappuccino, 1)]).with_user(self.admin)
        self._route_line_to_station(order.line_ids, self.station_kitchen)
        order.action_accept()
        order.line_ids.action_start()
        # Simulate the stuck scenario directly: both lines genuinely
        # Ready, but the order itself never advanced past 'preparing' -
        # bypassing the normal cascade entirely (with_context marks this
        # as a trusted internal manipulation, matching this module's
        # established pattern for test setup that needs to simulate an
        # already-happened external event).
        order.line_ids.with_context(kds_workflow_write=True).write({'state': 'ready'})
        self.assertEqual(order.state, 'preparing')
        self.assertTrue(order.is_expeditor_ready)

        self.env['kds.order']._cron_reconcile_stuck_orders()

        order.invalidate_recordset()
        self.assertEqual(
            order.state, 'completed',
            "The reconciliation cron must push a genuinely-ready-but-stuck order "
            "forward through the real action_ready()/action_complete() path.")

    def test_reconcile_cron_ignores_orders_that_are_not_actually_ready(self):
        order = self._order()
        order.action_accept()
        order.line_ids.action_start()
        self.assertEqual(order.state, 'preparing')
        self.assertFalse(order.is_expeditor_ready)

        self.env['kds.order']._cron_reconcile_stuck_orders()

        order.invalidate_recordset()
        self.assertEqual(
            order.state, 'preparing',
            "A genuinely still-in-progress order must not be touched by the "
            "reconciliation cron.")

    # -----------------------------------------------------------------
    # Dev request "Add COMPLETED Tab to KDS Screen": a completed order
    # stays visible on the KDS screens for a grace window (5 minutes,
    # COMPLETED_GRACE_MINUTES in both controllers) after finishing,
    # instead of disappearing the instant it completes - display
    # retention only, never deletion (see the "record and audit remain
    # intact" test further below). The actual query lives in the
    # controllers (controllers/kds.py, controllers/kds_kiosk.py), which
    # this project has no HTTP-level test coverage for (every existing
    # test is TransactionCase, exercising the model layer directly) -
    # these tests instead verify the exact domain pattern the
    # controllers use, against real records, so the underlying logic is
    # covered even without a live HTTP request.
    # -----------------------------------------------------------------
    def test_grace_period_domain_includes_recently_completed_order(self):
        from datetime import timedelta
        from odoo.fields import Datetime
        order = self._order()
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_ready()
        order.action_complete()  # DESIGN REVERSAL (v5.4): explicit step now
        self.assertEqual(order.state, 'completed')
        self.assertTrue(order.completion_time)

        grace_cutoff = Datetime.now() - timedelta(minutes=5)
        lines = self.env['kds.order.line'].search([
            ('station_id', '=', self.station_kitchen.id),
            ('state', '!=', 'cancelled'),
            '|',
                ('order_id.state', '!=', 'completed'),
                ('order_id.completion_time', '>=', grace_cutoff),
        ])
        self.assertIn(
            order.line_ids.id, lines.ids,
            "An order completed just now (well within the grace window) must still "
            "match the KDS screens' own query domain.")

    def test_grace_period_domain_excludes_order_completed_outside_the_window(self):
        from datetime import timedelta
        from odoo.fields import Datetime
        order = self._order()
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_ready()
        order.action_complete()  # DESIGN REVERSAL (v5.4): explicit step now
        self.assertEqual(order.state, 'completed')
        # Backdate completion_time well outside the grace window - same
        # with_context bypass pattern used elsewhere in this module for
        # tests that need to simulate an already-happened event.
        order.with_context(kds_workflow_write=True).write({
            'completion_time': Datetime.now() - timedelta(minutes=20),
        })

        grace_cutoff = Datetime.now() - timedelta(minutes=5)
        lines = self.env['kds.order.line'].search([
            ('station_id', '=', self.station_kitchen.id),
            ('state', '!=', 'cancelled'),
            '|',
                ('order_id.state', '!=', 'completed'),
                ('order_id.completion_time', '>=', grace_cutoff),
        ])
        self.assertNotIn(
            order.line_ids.id, lines.ids,
            "An order completed well outside the grace window must no longer match "
            "the KDS screens' own query domain.")

    def test_grace_period_domain_still_includes_genuinely_active_orders(self):
        # Regression check: the grace-period OR-branch must not
        # accidentally exclude orders that were never completed at all.
        from datetime import timedelta
        from odoo.fields import Datetime
        order = self._order()
        order.action_accept()
        order.line_ids.action_start()
        self.assertEqual(order.state, 'preparing')

        grace_cutoff = Datetime.now() - timedelta(minutes=5)
        lines = self.env['kds.order.line'].search([
            ('station_id', '=', self.station_kitchen.id),
            ('state', '!=', 'cancelled'),
            '|',
                ('order_id.state', '!=', 'completed'),
                ('order_id.completion_time', '>=', grace_cutoff),
        ])
        self.assertIn(order.line_ids.id, lines.ids)

    def test_expired_completed_order_record_and_audit_remain_intact(self):
        """Dev request acceptance criterion 9: "Database record and audit
        history remain intact after it disappears" - the grace period is
        display retention only, never deletion. Confirms the order,
        its lines, and its audit trail are all still fully present and
        queryable via a plain search with no grace-period domain at all
        (exactly what backend Order History / Analytics / any future
        HTTP endpoint that doesn't apply the grace filter would see),
        even once its completion_time is well outside the KDS screens'
        own 5-minute display window."""
        from datetime import timedelta
        from odoo.fields import Datetime
        order = self._order()
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_ready()
        order.action_complete()
        self.assertEqual(order.state, 'completed')
        events_before = self.env['kds.event'].search_count([('order_id', '=', order.id)])
        self.assertTrue(events_before, "A completed order must already have audit events logged.")

        order.with_context(kds_workflow_write=True).write({
            'completion_time': Datetime.now() - timedelta(minutes=20),
        })

        # No grace-period domain here at all - a plain, unfiltered lookup,
        # matching what backend history/analytics/audit screens do.
        found_order = self.env['kds.order'].search([('id', '=', order.id)])
        self.assertEqual(found_order, order, "The order record itself must never be deleted.")
        self.assertEqual(found_order.state, 'completed')
        self.assertTrue(found_order.line_ids, "Lines must remain intact.")
        events_after = self.env['kds.event'].search_count([('order_id', '=', order.id)])
        self.assertEqual(
            events_before, events_after,
            "Audit history must remain fully intact - expiring from the KDS screens' own "
            "display window must never touch it.")

    # -----------------------------------------------------------------
    # Dev request "Add COMPLETED Tab to KDS Screen" - acceptance criteria
    # not covered above. Honest note on test coverage: criteria 3, 4, 5
    # (the order visibly appearing under a COMPLETED tab, and the Ready/
    # Completed tab *counters* updating) are frontend JS behavior
    # (controllers/kds_kiosk.py's inline script, static/src/js/kds_app.js)
    # with no HTTP/JS-level test harness in this project (every existing
    # test is TransactionCase, exercising the model layer directly - see
    # the note on the grace-period tests above for the same limitation).
    # What IS covered here: the underlying *data* those tabs/counters key
    # off - order.state correctly distinguishing 'ready' from 'completed'
    # after each respective action - which is the actual source of truth
    # the frontend logic reads from.
    # -----------------------------------------------------------------
    def test_ready_and_completed_are_distinguishable_order_states(self):
        """The core data guarantee the new COMPLETED tab depends on:
        after Mark Ready, order.state is 'ready' (not yet 'completed');
        only after the separate Complete step does it become 'completed'
        - the two are genuinely distinct values a frontend tab/counter
        can branch on, not the same state observed at two different
        times."""
        order = self._order()
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_ready()
        self.assertEqual(order.state, 'ready')
        self.assertNotEqual(order.state, 'completed')

        order.action_complete()
        self.assertEqual(order.state, 'completed')
        self.assertNotEqual(order.state, 'ready')

    # -----------------------------------------------------------------
    # Dev request "Cancellation Visibility Improvement". Honest note on
    # test coverage, same limitation as the COMPLETED tab tests above:
    # criteria about the KDS screens actually *displaying* "CANCELLED"
    # and playing a distinguishable sound are frontend JS behavior with
    # no HTTP/JS-level test harness in this project. What's covered here
    # is the underlying data and server-side logic those screens read
    # from: the new cancelled_at timestamp, the audit trail's captured
    # previous-state, and the grace-period query pattern (same approach
    # as the existing COMPLETED grace-period domain tests further above
    # in this file).
    # -----------------------------------------------------------------
    def test_order_cancel_records_cancelled_at(self):
        order = self._order()
        self.assertFalse(order.cancelled_at)
        order.action_cancel()
        self.assertEqual(order.state, 'cancelled')
        self.assertTrue(order.cancelled_at)

    def test_line_cancel_audit_event_captures_previous_state(self):
        """Real gap found and fixed while implementing this feature: the
        line-level cancel event never recorded what state the line was
        actually IN before being cancelled - by the time log() ran, the
        write to 'cancelled' had already happened, so old_value was
        never meaningfully capturable after the fact. Now captured
        before the write, matching the equivalent order-level event
        (kds_order.py's _wf_transition already did this correctly)."""
        order = self._order()
        line = order.line_ids
        line.action_accept()
        line.action_start()
        self.assertEqual(line.state, 'preparing')

        events_before = self.env['kds.event'].search_count([('order_id', '=', order.id)])
        line.action_cancel(reason='Customer changed mind')
        self.assertEqual(line.state, 'cancelled')

        event = self.env['kds.event'].search(
            [('order_id', '=', order.id)], order='id desc', limit=1)
        self.assertEqual(
            self.env['kds.event'].search_count([('order_id', '=', order.id)]),
            events_before + 1)
        self.assertEqual(event.old_value, 'preparing',
                          "The audit event must record what state the line was actually in "
                          "right before cancellation, not the post-cancel state.")
        self.assertEqual(event.new_value, 'cancelled')
        self.assertIn(str(line.qty), event.note or '')
        self.assertIn(line.product_name, event.note or '')

    def test_full_order_cancel_cascades_cancelled_at_to_every_active_line(self):
        """Point 7 ('Multi-Station Behavior... if the entire order is
        cancelled, all affected stations must receive the
        cancellation'): confirms every active line - regardless of
        which station it's routed to - gets its own cancelled_at set by
        the order-level cascade, which is exactly what the KDS screens'
        own grace-period query (CANCELLED_GRACE_MINUTES in both
        controllers) checks per-line to decide what to keep showing."""
        order = self._make_order([(self.product_burger, 1), (self.product_cappuccino, 1)])
        self._route_line_to_station(order.line_ids[0], self.station_kitchen)
        self._route_line_to_station(order.line_ids[1], self.station_coffee)
        order = order.with_user(self.admin)
        order.action_accept()
        order.line_ids.action_start()
        for line in order.line_ids:
            self.assertFalse(line.cancelled_at)

        order.action_cancel()

        order.invalidate_recordset()
        self.assertEqual(order.state, 'cancelled')
        for line in order.line_ids:
            self.assertEqual(line.state, 'cancelled')
            self.assertTrue(
                line.cancelled_at,
                "Every active line must get its own cancelled_at set by the order-level "
                "cascade, regardless of which station it was routed to - this is what lets "
                "each affected station's own KDS screen apply its own grace-period window.")

    def test_grace_period_domain_includes_recently_cancelled_line(self):
        from datetime import timedelta
        from odoo.fields import Datetime
        order = self._order()
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_cancel(reason='test')
        self.assertEqual(order.line_ids.state, 'cancelled')

        cancelled_cutoff = Datetime.now() - timedelta(minutes=5)
        lines = self.env['kds.order.line'].search([
            ('station_id', '=', self.station_kitchen.id),
            '|', '|',
                ('state', 'not in', ('completed', 'cancelled')),
                '&', ('state', '=', 'completed'), ('order_id.completion_time', '>=', cancelled_cutoff),
                '&', ('state', '=', 'cancelled'), ('cancelled_at', '>=', cancelled_cutoff),
        ])
        self.assertIn(
            order.line_ids.id, lines.ids,
            "A line cancelled just now (well within the grace window) must still match "
            "the KDS screens' own query domain.")

    def test_grace_period_domain_excludes_line_cancelled_outside_the_window(self):
        from datetime import timedelta
        from odoo.fields import Datetime
        order = self._order()
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_cancel(reason='test')
        order.line_ids.with_context(kds_workflow_write=True).write({
            'cancelled_at': Datetime.now() - timedelta(minutes=20),
        })

        cancelled_cutoff = Datetime.now() - timedelta(minutes=5)
        lines = self.env['kds.order.line'].search([
            ('station_id', '=', self.station_kitchen.id),
            '|', '|',
                ('state', 'not in', ('completed', 'cancelled')),
                '&', ('state', '=', 'completed'), ('order_id.completion_time', '>=', cancelled_cutoff),
                '&', ('state', '=', 'cancelled'), ('cancelled_at', '>=', cancelled_cutoff),
        ])
        self.assertNotIn(
            order.line_ids.id, lines.ids,
            "A line cancelled well outside the grace window must no longer match the "
            "KDS screens' own query domain.")

    def test_cancelled_line_record_and_audit_remain_intact_after_expiry(self):
        """Point 3: 'Do NOT delete the database record. Do NOT delete
        audit history.' - same guarantee already established for
        Completed orders (test_expired_completed_order_record_and_audit_
        remain_intact above), confirmed here for a cancelled line too:
        the grace period is display retention only, never deletion,
        regardless of which terminal state (completed or cancelled) is
        involved."""
        from datetime import timedelta
        from odoo.fields import Datetime
        order = self._order()
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_cancel(reason='test')
        events_before = self.env['kds.event'].search_count([('order_id', '=', order.id)])

        order.line_ids.with_context(kds_workflow_write=True).write({
            'cancelled_at': Datetime.now() - timedelta(minutes=20),
        })

        found_order = self.env['kds.order'].search([('id', '=', order.id)])
        self.assertEqual(found_order, order, "The order record itself must never be deleted.")
        self.assertTrue(found_order.line_ids, "Lines must remain intact.")
        self.assertEqual(found_order.line_ids.state, 'cancelled')
        events_after = self.env['kds.event'].search_count([('order_id', '=', order.id)])
        self.assertEqual(
            events_before, events_after,
            "Audit history must remain fully intact - expiring from the KDS screens' own "
            "display window must never touch it.")

    # -----------------------------------------------------------------
    # Dev request "Runtime Regression Fix Package", BUG-02/BUG-02B:
    # reopening after Ready/Completed must preserve previously-completed
    # work's own history, and must record a richer audit trail (previous
    # state, reopening timestamp, modification source, added/updated
    # lines). The visible "resets to NEW" symptom itself was a frontend
    # display-precedence bug (fixed in kds_kiosk.py/kds_order_card.js -
    # no JS-level test harness exists for that, per this project's
    # established limitation) - order.state was never actually wrong in
    # the database; these tests confirm that directly.
    # -----------------------------------------------------------------
    def test_reopen_from_ready_lands_on_preparing_not_new(self):
        order = self._make_order([(self.product_burger, 1), (self.product_cappuccino, 1)])
        self._route_line_to_station(order.line_ids, self.station_kitchen)
        order = order.with_user(self.admin)
        order.line_ids.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_ready()
        self.assertEqual(order.state, 'ready')

        # A new line arriving via create() (matching how a POS Delta's
        # ADDED line actually reaches this model) must reopen straight
        # to 'preparing', never 'new'.
        self.env['kds.order.line'].create({
            'order_id': order.id, 'product_id': self.product_burger.id, 'qty': 1,
            'station_id': self.station_kitchen.id,
        })
        order.invalidate_recordset()
        self.assertEqual(order.state, 'preparing')
        self.assertNotEqual(order.state, 'new')

    def test_reopen_from_completed_preserves_previously_completed_lines(self):
        """The core BUG-02B guarantee: 'Previously completed preparation'
        must be distinguished from 'new preparation work received after
        completion' - the original lines stay historically Completed
        (their own state, timestamps, and audit trail untouched), only
        the order's own aggregate state and the new line need attention."""
        order = self._order()
        original_line = order.line_ids
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_ready()
        order.action_complete()
        self.assertEqual(order.state, 'completed')
        self.assertEqual(original_line.state, 'completed')
        original_completion_time = original_line.ready_time

        self.env['kds.order.line'].create({
            'order_id': order.id, 'product_id': self.product_cappuccino.id, 'qty': 1,
            'station_id': self.station_kitchen.id,
        })

        order.invalidate_recordset()
        self.assertEqual(
            order.state, 'preparing',
            "Reopening after Completed must land on 'preparing', never 'new' - the "
            "original completed work is not being redone.")
        self.assertEqual(
            original_line.state, 'completed',
            "The original line's own state must remain untouched - 'previously completed "
            "work remains historically completed', per the dev request's own wording.")
        self.assertEqual(original_line.ready_time, original_completion_time,
                          "The original line's own timestamps must not be rewritten.")

    def test_reopen_audit_event_captures_reason_and_previous_state(self):
        """BUG-02B: 'Record at minimum: previous state, reopening
        timestamp, modification source, added/updated lines.'"""
        order = self._order()
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_ready()
        order.action_complete()
        events_before = self.env['kds.event'].search_count([('order_id', '=', order.id)])

        new_line = self.env['kds.order.line'].create({
            'order_id': order.id, 'product_id': self.product_cappuccino.id, 'qty': 1,
            'station_id': self.station_kitchen.id,
        })

        reopen_event = self.env['kds.event'].search([
            ('order_id', '=', order.id),
            ('event_type', '=', 'status_changed'),
            ('new_value', '=', 'preparing'),
        ], order='id desc', limit=1)
        self.assertTrue(reopen_event, "A reopen audit event must exist.")
        self.assertEqual(reopen_event.old_value, 'completed',
                          "Must record the previous state (was Completed).")
        self.assertTrue(reopen_event.create_date, "Must have a reopening timestamp.")
        self.assertIn(new_line.product_name, reopen_event.note or '',
                      "Must identify what triggered the reopen (the new/modified line).")
        self.assertGreater(
            self.env['kds.event'].search_count([('order_id', '=', order.id)]),
            events_before,
            "Must add at least one new audit event for the reopen itself.")

    # -----------------------------------------------------------------
    # Dev request "Remaining Fixes After v19.0.7.0.0 Review", item 1:
    # a REAL regression found in review - the grace-period SEARCH domain
    # (tested above) was correct, but a separate, downstream .filtered()
    # call in both controllers (rebuilding the station-scoped line list
    # for the actual JSON payload) used a stricter condition that didn't
    # match it, silently re-excluding cancelled lines the search had
    # already correctly included. These tests replicate that exact
    # payload-building filter (not just the search domain) to catch this
    # specific class of divergence directly, since the two must always
    # agree - see controllers/kds.py's own `display_lines` for the fix.
    # -----------------------------------------------------------------
    def test_cancelled_line_payload_filter_includes_recently_cancelled(self):
        from datetime import timedelta
        from odoo.fields import Datetime
        order = self._order()
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_cancel(reason='test')
        self.assertEqual(order.line_ids.state, 'cancelled')

        cancelled_cutoff = Datetime.now() - timedelta(minutes=5)
        display_lines = order.line_ids.filtered(
            lambda l, sid=self.station_kitchen.id, cc=cancelled_cutoff: l.station_id.id == sid and (
                l.state != 'cancelled' or (l.cancelled_at and l.cancelled_at >= cc)
            ))
        self.assertIn(
            order.line_ids, display_lines,
            "A recently-cancelled line must survive the payload-building filter, not just "
            "the initial search - both must apply the identical grace-period condition.")

    def test_fully_cancelled_order_still_produces_a_non_empty_payload(self):
        """The exact symptom reported: 'Cancel Order -> immediately
        disappears'. A fully-cancelled single-station order's display_lines
        must never come back empty within the grace window - an empty
        result is what made the controller's `if not display_lines:
        continue` skip the whole order."""
        from datetime import timedelta
        from odoo.fields import Datetime
        order = self._order()
        order.action_accept()
        order.line_ids.action_start()
        order.action_cancel()
        self.assertEqual(order.state, 'cancelled')
        self.assertEqual(order.line_ids.state, 'cancelled')

        cancelled_cutoff = Datetime.now() - timedelta(minutes=5)
        display_lines = order.line_ids.filtered(
            lambda l, sid=self.station_kitchen.id, cc=cancelled_cutoff: l.station_id.id == sid and (
                l.state != 'cancelled' or (l.cancelled_at and l.cancelled_at >= cc)
            ))
        self.assertTrue(
            display_lines,
            "A fully cancelled order's own station must still receive a non-empty line "
            "list within the grace window - never silently disappear.")

    def test_cancelled_line_payload_filter_excludes_expired_cancellation(self):
        from datetime import timedelta
        from odoo.fields import Datetime
        order = self._order()
        order.action_accept()
        order.line_ids.action_start()
        order.line_ids.action_cancel(reason='test')
        order.line_ids.with_context(kds_workflow_write=True).write({
            'cancelled_at': Datetime.now() - timedelta(minutes=20),
        })

        cancelled_cutoff = Datetime.now() - timedelta(minutes=5)
        display_lines = order.line_ids.filtered(
            lambda l, sid=self.station_kitchen.id, cc=cancelled_cutoff: l.station_id.id == sid and (
                l.state != 'cancelled' or (l.cancelled_at and l.cancelled_at >= cc)
            ))
        self.assertFalse(
            display_lines,
            "A cancellation well outside the grace window must correctly disappear from "
            "the payload filter too, same as the search domain.")

    # -----------------------------------------------------------------
    # REAL BUG FIX, confirmed live on Odoo.sh: calling action_ready() on
    # a multi-line recordset (a realistic "mark everything ready at
    # once" usage - not just a test artifact, this exact scenario was
    # first surfaced by an unrelated refund test that happened to use a
    # 2-product order) used to call order.action_ready() once PER LINE
    # instead of once per distinct order - by the second line's own
    # iteration, is_expeditor_ready was already True (every line had
    # just been written to 'ready' by the same batch), so its own call
    # tried an invalid 'ready' -> 'ready' self-transition and raised
    # "cannot move order ... from 'ready' to 'ready'."
    # -----------------------------------------------------------------
    def test_batch_action_ready_on_multiline_order_does_not_raise(self):
        order = self._make_order([(self.product_burger, 1), (self.product_cappuccino, 1)])
        order.line_ids.write({'station_id': self.station_kitchen.id})
        order = order.with_user(self.admin)
        order.line_ids.action_accept()
        order.line_ids.action_start()

        order.line_ids.action_ready()  # should not raise

        order.invalidate_recordset()
        self.assertEqual(order.line_ids.mapped('state'), ['ready', 'ready'])
        self.assertEqual(
            order.state, 'ready',
            "The order itself must still correctly advance to Ready exactly once, "
            "regardless of how many of its own lines were in the batch call.")

    def test_batch_action_ready_across_two_different_orders_does_not_raise(self):
        """Same fix, the other direction: a batch spanning lines from
        TWO different orders must still advance each order exactly
        once, not skip one or double-transition the other."""
        order_a = self._order()
        order_b = self._order()
        lines = order_a.line_ids | order_b.line_ids
        lines.action_accept()
        lines.action_start()

        lines.action_ready()  # should not raise

        order_a.invalidate_recordset()
        order_b.invalidate_recordset()
        self.assertEqual(order_a.state, 'ready')
        self.assertEqual(order_b.state, 'ready')
