# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import FlexSysKdsTestCommon


@tagged('post_install', '-at_install')
class TestPermissions(FlexSysKdsTestCommon):

    def _order_at_kitchen(self):
        order = self._make_order([(self.product_burger, 1)])
        self._route_line_to_station(order.line_ids, self.station_kitchen)
        return order

    def test_operator_with_no_station_is_denied(self):
        """Point 1 hardening: an Operator with no station assignment is
        denied by default rather than implicitly seeing/acting on
        everything."""
        user = self._make_kds_user('op_no_station', self.group_operator)
        order = self._order_at_kitchen()
        line = order.line_ids.with_user(user)
        with self.assertRaises(AccessError):
            line.action_accept()

    def test_operator_assigned_to_station_can_act(self):
        user = self._make_kds_user('op_kitchen', self.group_operator, self.station_kitchen)
        order = self._order_at_kitchen()
        line = order.line_ids.with_user(user)
        line.action_accept()  # should not raise
        self.assertEqual(line.state, 'accepted')

    def test_operator_assigned_to_other_station_is_denied(self):
        user = self._make_kds_user('op_coffee_only', self.group_operator, self.station_coffee)
        order = self._order_at_kitchen()  # order is at Kitchen, user is only on Coffee
        line = order.line_ids.with_user(user)
        with self.assertRaises(AccessError):
            line.action_accept()

    def test_operator_cannot_cancel_supervisor_only_action(self):
        user = self._make_kds_user('op_kitchen2', self.group_operator, self.station_kitchen)
        order = self._order_at_kitchen()
        line = order.line_ids.with_user(user)
        with self.assertRaises(AccessError):
            line.action_cancel(reason='test')

    # -----------------------------------------------------------------
    # Audit finding 01 (CRITICAL): _kds_check_order_access() used to
    # `continue` instead of raising for a user with zero assigned
    # stations, silently skipping the check entirely for ORDER-level
    # actions specifically (action_accept/action_start_preparing/
    # action_ready/action_complete/action_cancel/action_hold/
    # action_reopen, called directly on kds.order - as opposed to the
    # LINE-level actions the tests above already covered). This gap in
    # test coverage is exactly why the bug went unnoticed - these tests
    # close it.
    # -----------------------------------------------------------------
    def test_order_level_action_denied_for_operator_with_no_station(self):
        user = self._make_kds_user('order_op_no_station', self.group_operator)
        order = self._order_at_kitchen().with_user(user)
        with self.assertRaises(AccessError):
            order.action_accept()

    def test_order_level_start_preparing_denied_for_operator_with_no_station(self):
        user = self._make_kds_user('order_op_no_station2', self.group_operator)
        order = self._order_at_kitchen().with_user(user)
        with self.assertRaises(AccessError):
            order.action_start_preparing()

    def test_order_level_action_denied_for_supervisor_with_no_station(self):
        # Point: the fix applies to Supervisor too, not just Operator -
        # station scope is about *station assignment*, independent of
        # which action-tier permission the user otherwise holds.
        user = self._make_kds_user('order_sup_no_station', self.group_supervisor)
        order = self._order_at_kitchen().with_user(user)
        with self.assertRaises(AccessError):
            order.action_cancel()

    def test_order_level_action_allowed_for_operator_assigned_to_station(self):
        user = self._make_kds_user('order_op_kitchen', self.group_operator, self.station_kitchen)
        order = self._order_at_kitchen().with_user(user)
        order.action_accept()  # should not raise
        self.assertEqual(order.state, 'accepted')

    def test_order_level_action_still_allowed_for_administrator_with_no_station(self):
        # Administrator legitimately bypasses station scope entirely -
        # confirms the fix didn't overcorrect into blocking admins too.
        user = self._make_kds_user('order_admin_no_station', self.group_administrator)
        order = self._order_at_kitchen().with_user(user)
        order.action_accept()  # should not raise
        self.assertEqual(order.state, 'accepted')

    # -----------------------------------------------------------------
    # Audit finding 02 (CRITICAL): kds.order/kds.order.line grant
    # Operators write=1 via ir.model.access.csv, but nothing stopped a
    # direct write({'state': ...}) bypassing the workflow engine
    # entirely - no transition validation, no permission check, no
    # timestamp/audit-event logging. Protected fields (state, priority,
    # and the workflow timestamps on kds.order; state, station_id, and
    # the workflow timestamps on kds.order.line) may now only be written
    # by the workflow engine's own internal context or a genuine sudo()
    # context - never a plain user-level write().
    # -----------------------------------------------------------------
    def test_direct_state_write_blocked_on_order(self):
        user = self._make_kds_user('direct_write_op', self.group_operator, self.station_kitchen)
        order = self._order_at_kitchen().with_user(user)
        with self.assertRaises(AccessError):
            order.write({'state': 'completed'})

    def test_direct_state_write_blocked_even_for_administrator(self):
        # Point: this is NOT a permission-tier gate that a higher role
        # can clear - it's "state must move through the workflow engine,
        # full stop", per the audit's own fix description ("Allow direct
        # writes only through a controlled internal context used by
        # trusted system flows"). An Administrator user has no more
        # right to hand-edit state than an Operator does.
        user = self._make_kds_user('direct_write_admin', self.group_administrator)
        order = self._order_at_kitchen().with_user(user)
        with self.assertRaises(AccessError):
            order.write({'state': 'completed'})

    def test_direct_priority_write_blocked_on_order(self):
        user = self._make_kds_user('direct_write_op2', self.group_operator, self.station_kitchen)
        order = self._order_at_kitchen().with_user(user)
        with self.assertRaises(AccessError):
            order.write({'priority': 'vip'})

    def test_direct_state_write_blocked_on_line(self):
        user = self._make_kds_user('direct_write_op3', self.group_operator, self.station_kitchen)
        order = self._order_at_kitchen()
        line = order.line_ids.with_user(user)
        with self.assertRaises(AccessError):
            line.write({'state': 'ready'})

    def test_direct_station_id_write_blocked_on_line(self):
        user = self._make_kds_user('direct_write_op4', self.group_operator, self.station_kitchen)
        order = self._order_at_kitchen()
        line = order.line_ids.with_user(user)
        # REAL BUG FIX, confirmed live on Odoo.sh: a previous round's
        # automated find-and-replace (fixing dozens of *other* tests that
        # incorrectly used a raw, unprotected write() just to set up
        # fixtures) blindly matched this test too and swapped its write()
        # for the new _route_line_to_station() helper - which
        # deliberately uses kds_workflow_write=True internally to
        # legitimately bypass the same protection this specific test
        # exists to confirm blocks a real user. That made the assertion
        # "AccessError not raised" fail, since the helper made the write
        # succeed on purpose. Reverted to a raw write() here specifically
        # - this is the one test in the whole suite that must NOT use
        # the bypass helper, since bypassing the protection is exactly
        # what it's testing against.
        with self.assertRaises(AccessError):
            line.write({'station_id': self.station_coffee.id})

    def test_non_protected_fields_still_writable_directly(self):
        # The guard is scoped to specific fields, not a blanket lockdown -
        # a legitimate field like the free-text customer_name should
        # still be directly writable by whoever already has model-level
        # write access.
        user = self._make_kds_user('direct_write_op5', self.group_operator, self.station_kitchen)
        order = self._order_at_kitchen().with_user(user)
        order.write({'customer_name': 'Ahmed'})  # should not raise
        self.assertEqual(order.customer_name, 'Ahmed')

    def test_workflow_actions_unaffected_by_write_protection(self):
        # The whole point: normal action-driven workflow must keep
        # working exactly as before - only raw write() bypassing it is
        # newly blocked.
        order = self._order_at_kitchen()
        order.action_accept()
        self.assertEqual(order.state, 'accepted')
        self.assertTrue(order.accepted_time)
        order.action_start_preparing()
        self.assertEqual(order.state, 'preparing')
        self.assertTrue(order.preparation_start_time)

    def test_action_change_priority_works_and_is_audited(self):
        order = self._order_at_kitchen()
        self.assertEqual(order.priority, 'normal')
        order.action_change_priority('vip')
        self.assertEqual(order.priority, 'vip')
        events = self.env['kds.event'].search([
            ('order_id', '=', order.id), ('event_type', '=', 'priority_changed')])
        self.assertTrue(events, "Priority change should be audit-logged.")

    def test_action_change_priority_denied_for_operator(self):
        # change_priority is Supervisor+ per ACTION_MIN_GROUP.
        user = self._make_kds_user('priority_op', self.group_operator, self.station_kitchen)
        order = self._order_at_kitchen().with_user(user)
        with self.assertRaises(AccessError):
            order.action_change_priority('vip')

    # -----------------------------------------------------------------
    # Audit finding 3/Record Rules & Station Scope (HIGH): read/search/
    # read_group must be scoped by station assignment too, not just the
    # action-level checks above (kds.access.mixin) - those only guard the
    # public action_* methods, they say nothing about what a user can
    # plainly *see* via the backend's own list/search/read_group, or via
    # direct RPC reads that never call an action method at all.
    # -----------------------------------------------------------------
    def test_station_with_no_users_is_invisible_to_random_operator(self):
        """Real bug fixed: the old rule's `station_id.user_ids = False`
        branch meant a station with NO users assigned became visible to
        EVERY Operator company-wide - exactly backwards from "an empty
        station.user_ids must not automatically provide global access."
        station_coffee has no users assigned in these fixtures."""
        user = self._make_kds_user('search_op_no_coffee', self.group_operator, self.station_kitchen)
        order = self._make_order([(self.product_cappuccino, 1)])
        self._route_line_to_station(order.line_ids, self.station_coffee)
        found = self.env['kds.order.line'].with_user(user).search(
            [('id', '=', order.line_ids.id)])
        self.assertFalse(
            found,
            "An Operator assigned only to Kitchen must not see lines at Coffee, "
            "even though Coffee has no users of its own assigned.")

    def test_operator_search_scoped_to_own_station_only(self):
        user = self._make_kds_user('search_op_kitchen', self.group_operator, self.station_kitchen)
        kitchen_order = self._order_at_kitchen()
        coffee_order = self._make_order([(self.product_cappuccino, 1)])
        self._route_line_to_station(coffee_order.line_ids, self.station_coffee)
        visible_lines = self.env['kds.order.line'].with_user(user).search([])
        self.assertIn(kitchen_order.line_ids.id, visible_lines.ids)
        self.assertNotIn(coffee_order.line_ids.id, visible_lines.ids)

    def test_operator_order_search_scoped_to_stations_touched(self):
        user = self._make_kds_user('search_op_kitchen2', self.group_operator, self.station_kitchen)
        kitchen_order = self._order_at_kitchen()
        coffee_order = self._make_order([(self.product_cappuccino, 1)])
        self._route_line_to_station(coffee_order.line_ids, self.station_coffee)
        visible_orders = self.env['kds.order'].with_user(user).search([])
        self.assertIn(kitchen_order.id, visible_orders.ids)
        self.assertNotIn(coffee_order.id, visible_orders.ids)

    def test_operator_with_no_station_sees_no_orders_at_all(self):
        user = self._make_kds_user('search_op_none', self.group_operator)
        self._order_at_kitchen()
        visible = self.env['kds.order'].with_user(user).search([])
        self.assertFalse(visible)

    def test_read_group_also_respects_station_scope(self):
        # read_group is a separate ORM code path from search() - the
        # audit specifically calls it out, since a naive fix that only
        # patches search() can still leak counts/aggregates through
        # read_group.
        #
        # ODOO 19 API MIGRATION, confirmed live on Odoo.sh
        # (DeprecationWarning: "Since 19.0, read_group is deprecated.
        # Please use _read_group in the backend code or
        # formatted_read_group for a complete formatted result"):
        # switched to _read_group (the backend-code method the warning
        # names first) rather than formatted_read_group, since this test
        # only needs the grouped station values themselves, not a fully
        # formatted display-ready result. _read_group's return shape is
        # a list of tuples, one element per groupby/aggregate requested
        # in order - with only groupby=['station_id'] and no aggregates,
        # each tuple holds a single kds.station recordset (not a
        # formatted [id, name] pair the way the old read_group's dict
        # output did), so station.id is read directly rather than
        # indexing into a dict by field name.
        user = self._make_kds_user('readgroup_op', self.group_operator, self.station_kitchen)
        self._order_at_kitchen()
        coffee_order = self._make_order([(self.product_cappuccino, 1)])
        self._route_line_to_station(coffee_order.line_ids, self.station_coffee)
        groups = self.env['kds.order.line'].with_user(user)._read_group(
            [], groupby=['station_id'])
        seen_station_ids = {station.id for (station,) in groups if station}
        self.assertIn(self.station_kitchen.id, seen_station_ids)
        self.assertNotIn(self.station_coffee.id, seen_station_ids)

    def test_branch_manager_sees_own_company_regardless_of_station_assignment(self):
        # Branch Manager's scope is company, not explicit station
        # assignment - confirms the new operator-tier rule doesn't
        # accidentally over-restrict the branch_manager tier too (the two
        # rules are OR-combined, so branch_manager should see everything
        # in-company even with zero kds_station_ids of their own).
        user = self._make_kds_user('bm_no_station', self.group_branch_manager)
        order = self._order_at_kitchen()
        visible = self.env['kds.order'].with_user(user).search([('id', '=', order.id)])
        self.assertIn(order.id, visible.ids)

    def test_administrator_sees_everything_regardless_of_station_assignment(self):
        user = self._make_kds_user('admin_no_station', self.group_administrator)
        kitchen_order = self._order_at_kitchen()
        coffee_order = self._make_order([(self.product_cappuccino, 1)])
        self._route_line_to_station(coffee_order.line_ids, self.station_coffee)
        visible = self.env['kds.order'].with_user(user).search([])
        self.assertIn(kitchen_order.id, visible.ids)
        self.assertIn(coffee_order.id, visible.ids)

    def test_supervisor_assigned_to_station_can_cancel(self):
        user = self._make_kds_user('sup_kitchen', self.group_supervisor, self.station_kitchen)
        order = self._order_at_kitchen()
        line = order.line_ids.with_user(user)
        line.action_cancel(reason='test')  # should not raise
        self.assertEqual(line.state, 'cancelled')

    def test_supervisor_at_wrong_station_still_denied(self):
        """Being a Supervisor grants the *action* permission but station
        assignment is still checked independently."""
        user = self._make_kds_user('sup_coffee_only', self.group_supervisor, self.station_coffee)
        order = self._order_at_kitchen()
        line = order.line_ids.with_user(user)
        with self.assertRaises(AccessError):
            line.action_cancel(reason='test')

    def test_branch_manager_can_act_on_any_station_in_company(self):
        user = self._make_kds_user('branch_mgr', self.group_branch_manager)
        # deliberately no explicit kds_station_ids - branch manager scope
        # comes from company, not station assignment.
        order = self._order_at_kitchen()
        line = order.line_ids.with_user(user)
        line.action_accept()
        self.assertEqual(line.state, 'accepted')

    def test_administrator_bypasses_station_assignment(self):
        user = self._make_kds_user('admin_user', self.group_administrator)
        order = self._order_at_kitchen()
        line = order.line_ids.with_user(user)
        line.action_accept()
        self.assertEqual(line.state, 'accepted')

    def test_reprint_requires_supervisor(self):
        user = self._make_kds_user('op_reprint', self.group_operator, self.station_kitchen)
        order = self._order_at_kitchen()
        with self.assertRaises(AccessError):
            self.env['kds.print.job'].with_user(user).create_reprint(
                order, self.station_kitchen, reason='kitchen_request')

    def test_reprint_allowed_for_supervisor_at_station(self):
        user = self._make_kds_user('sup_reprint', self.group_supervisor, self.station_kitchen)
        order = self._order_at_kitchen()
        job = self.env['kds.print.job'].with_user(user).create_reprint(
            order, self.station_kitchen, reason='kitchen_request')
        self.assertEqual(job.job_type, 'reprint')
        self.assertEqual(job.station_id, self.station_kitchen)

    def test_wrong_station_operator_denied_without_bypass(self):
        """1 of 3 required scenarios: normal unauthorized user -> denied.
        An Operator IS assigned a station and DOES have base model
        access (group_kds_operator) - this specifically isolates the
        KDS station-tier permission check, not the base ACL (a
        completely unprivileged user fails even earlier, at the base
        ACL/Record Rule layer - a different, already-covered scenario;
        see test_operator_search_scoped_to_own_station_only and
        friends)."""
        wrong_station_operator = self._make_kds_user(
            'wrong_station_op1', self.group_operator, self.station_coffee)
        order = self._order_at_kitchen()
        line = order.line_ids.with_user(wrong_station_operator)
        with self.assertRaises(AccessError):
            line.action_accept(bypass_check=False)

    def test_bypass_check_succeeds_for_trusted_internal_call(self):
        """2 of 3 required scenarios: trusted internal call with bypass
        -> succeeds.

        REAL BUG FIX, confirmed live on Odoo.sh: bypass_check=True used
        to still operate on the recordset exactly as the caller passed
        it in - meaning even with the flag set, the call still hit the
        calling user's own station-scoped Record Rule the moment it
        tried to just READ line.state, before bypass_check's own meaning
        (skip the KDS action/station permission tier) was ever
        consulted: "doesn't have 'read' access to... FlexSys KDS Order
        Line", a Record Rule denial, not the KDS-tier check this flag is
        actually meant to skip. Fixed by clarifying the contract
        precisely: bypass_check=True now switches the actual transition
        work onto a sudo'd recordset internally
        (_line_transition/_wf_transition), matching how every other
        genuinely trusted internal flow in this module already operates
        (_flexsys_kds_diff_lines() runs under self.sudo() at its own
        call site) - not a weakening of normal Operator Record Rules,
        which still apply exactly as before to every bypass_check=False
        call (see the test just above, and every interactive action
        reachable from either KDS screen, which never pass bypass_check
        at all - see the next test)."""
        wrong_station_operator = self._make_kds_user(
            'wrong_station_op2', self.group_operator, self.station_coffee)
        order = self._order_at_kitchen()
        line = order.line_ids.with_user(wrong_station_operator)
        line.action_accept(bypass_check=True)  # should not raise
        self.assertEqual(line.state, 'accepted')

    def test_bypass_check_not_reachable_from_any_controller_route(self):
        """3 of 3 required scenarios: bypass cannot be abused externally.

        Structural check, not just a code-review claim: inspects the
        actual signatures of every controller route that can trigger a
        line/order action on behalf of a real HTTP request
        (controllers/kds.py's line_action/order_action) and confirms
        `bypass_check` is not among their parameters at all - there is
        no request field an external caller could ever set to reach it,
        regardless of what a request sends. Also confirms neither route
        body passes bypass_check positionally when calling the
        underlying action methods."""
        import inspect
        from odoo.addons.flexsys_kds.controllers.kds import FlexSysKdsController

        line_action_sig = inspect.signature(FlexSysKdsController.line_action)
        self.assertNotIn(
            'bypass_check', line_action_sig.parameters,
            "line_action must never expose bypass_check as a request parameter.")

        order_action_sig = inspect.signature(FlexSysKdsController.order_action)
        self.assertNotIn(
            'bypass_check', order_action_sig.parameters,
            "order_action must never expose bypass_check as a request parameter.")

        source = inspect.getsource(FlexSysKdsController.line_action) \
            + inspect.getsource(FlexSysKdsController.order_action)
        self.assertNotIn(
            'bypass_check', source,
            "Neither controller route may pass bypass_check to the underlying action "
            "methods under any name - every call must rely on the default (False).")
    # Dev request "Full Runtime Regression" acceptance criterion: "No
    # cross-company data leakage" - a real gap found while auditing this
    # file's own coverage against that checklist: every existing
    # cross-company test lived in test_routing.py/test_expeditor.py
    # (confirming a *routing rule* never matches across companies), but
    # nothing here confirmed the equivalent for a station-scoped
    # *Operator* directly - that they cannot see or act on another
    # company's order at all, not even indirectly through search/read,
    # using the same company_b/station_kitchen_b fixture already
    # established in common.py for exactly this purpose.
    # -----------------------------------------------------------------
    def test_operator_cannot_act_on_a_different_companys_order(self):
        user = self._make_kds_user(
            'op_company_b', self.group_operator, self.station_kitchen_b)
        order = self._order_at_kitchen()  # Company A's default test company, Kitchen station
        line = order.line_ids.with_user(user)
        with self.assertRaises(
            AccessError,
            msg="An Operator scoped to a station in Company B must never be able to act "
                "on an order that belongs to Company A."
        ):
            line.action_accept()

    def test_operator_search_never_returns_a_different_companys_order(self):
        user = self._make_kds_user(
            'op_company_b_search', self.group_operator, self.station_kitchen_b)
        order = self._order_at_kitchen()  # Company A
        found = self.env['kds.order'].with_user(user).search([('id', '=', order.id)])
        self.assertFalse(
            found,
            "A record-rule-scoped search for a station-scoped Operator in Company B must "
            "never return an order belonging to Company A, even by exact id.")
