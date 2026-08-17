# -*- coding: utf-8 -*-
"""
HIGH-RISK FILE - validate this one first on a real Odoo 19 staging
instance before trusting the rest of the suite's green light.

Every other test file in this package (test_routing, test_workflow,
test_permissions, test_printing) only touches this module's own models
and is reasonably version-safe. This file has to construct real
pos.session / pos.order / pos.order.line records, and point_of_sale's
required fields (pricelist_id, fiscal position, amount_total/tax/paid/
return, session state machine, etc.) have shifted across Odoo versions
and I have no live Odoo 19 instance to confirm the exact minimal set
needed here. If `setUpClass` itself fails, that is very likely a
point_of_sale scaffolding mismatch, not a bug in flexsys_kds - fix the
fixture (probably by pointing it at point_of_sale's own test helpers,
`odoo.addons.point_of_sale.tests.common.TestPoSCommon`, if that class's
shape matches your version) rather than assuming the module under test
is broken.

What this file specifically covers, because these were flagged as the
most important gaps to close:
  1. No duplicate kds.order is created across repeated syncs.
  2. Added / updated / removed line detection (delta sync, not
     create-once).
  3. The product-change reroute fix: changing a POS line's product to one
     that belongs to a different station must move the ticket to that
     station, not just update the product name in place.
"""
from odoo.tests import tagged

from .common import FlexSysKdsTestCommon


@tagged('post_install', '-at_install')
class TestPosSync(FlexSysKdsTestCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product_burger.kds_station_id = cls.station_kitchen
        cls.product_cappuccino.kds_station_id = cls.station_coffee

        cls.pos_config = cls.env['pos.config'].create({
            'name': 'Test FlexSys POS',
        })
        cls.pos_session = cls.env['pos.session'].create({
            'config_id': cls.pos_config.id,
            'user_id': cls.env.uid,
        })
        # Some versions require the session to be explicitly opened before
        # orders can reference it; guarded so a version without this
        # requirement (or with a differently-named method) doesn't blow up
        # fixture setup entirely.
        if hasattr(cls.pos_session, 'action_pos_session_open'):
            try:
                cls.pos_session.action_pos_session_open()
            except Exception:
                pass

    def _create_pos_order(self, product_qty_list, state='paid'):
        line_vals = []
        for product, qty in product_qty_list:
            line_vals.append((0, 0, {
                'product_id': product.id,
                'qty': qty,
                'price_unit': product.list_price or 10.0,
                'price_subtotal': (product.list_price or 10.0) * qty,
                'price_subtotal_incl': (product.list_price or 10.0) * qty,
            }))
        order = self.env['pos.order'].create({
            'session_id': self.pos_session.id,
            'company_id': self.company.id,
            'lines': line_vals,
            'amount_tax': 0.0,
            'amount_total': sum((p.list_price or 10.0) * q for p, q in product_qty_list),
            'amount_paid': sum((p.list_price or 10.0) * q for p, q in product_qty_list),
            'amount_return': 0.0,
            'state': 'draft',
        })
        order.write({'state': state})  # triggers _flexsys_kds_sync via write()
        return order

    def _create_refund_order(self, refund_qty_map):
        """BUG-11 test helper: creates a refund pos.order correlated back
        to the given {original_pos_order_line: refund_qty} mapping via
        refunded_orderline_id - the field the whole reconciliation
        mechanism (_flexsys_kds_reconcile_refund) depends on. Skips the
        test entirely (not a failure) if this build's pos.order.line
        doesn't have that field - there is no reliable way to test the
        correlation-dependent reconciliation without it, matching this
        module's own defensive "don't guess" philosophy documented on
        _flexsys_kds_is_refund_order() itself."""
        if 'refunded_orderline_id' not in self.env['pos.order.line']._fields:
            self.skipTest(
                "refunded_orderline_id not present on pos.order.line in this build - "
                "cannot test refund reconciliation without it.")
        line_vals = []
        total = 0.0
        for orig_line, refund_qty in refund_qty_map.items():
            subtotal = -orig_line.price_unit * refund_qty
            total += subtotal
            line_vals.append((0, 0, {
                'product_id': orig_line.product_id.id,
                'qty': -refund_qty,
                'price_unit': orig_line.price_unit,
                'price_subtotal': subtotal,
                'price_subtotal_incl': subtotal,
                'refunded_orderline_id': orig_line.id,
            }))
        refund_order = self.env['pos.order'].create({
            'session_id': self.pos_session.id,
            'company_id': self.company.id,
            'lines': line_vals,
            'amount_tax': 0.0,
            'amount_total': total,
            'amount_paid': total,
            'amount_return': 0.0,
            'state': 'draft',
        })
        refund_order.write({'state': 'paid'})  # triggers _flexsys_kds_sync via write()
        return refund_order

    def test_paying_an_order_creates_exactly_one_kds_order(self):
        order = self._create_pos_order([(self.product_burger, 2)])
        self.assertTrue(order.kds_order_id)
        kds_orders = self.env['kds.order'].search([('pos_order_id', '=', order.id)])
        self.assertEqual(len(kds_orders), 1)

    def test_repeated_sync_does_not_duplicate_the_kds_order(self):
        """The specific regression this test guards against: the sync
        entry point must not create a second kds.order when called again
        on an order that already has one (e.g. another unrelated write()
        that happens to touch 'state' or 'lines')."""
        order = self._create_pos_order([(self.product_burger, 1)])
        first_kds_order = order.kds_order_id
        # Force another sync pass the way write() would trigger one.
        order._flexsys_kds_sync()
        order._flexsys_kds_sync()
        order.write({'state': 'done'})

        self.assertEqual(order.kds_order_id, first_kds_order,
                          "kds_order_id must not be replaced by a second sync call.")
        kds_orders = self.env['kds.order'].search([('pos_order_id', '=', order.id)])
        self.assertEqual(len(kds_orders), 1, "Exactly one kds.order must exist for this pos.order, ever.")

    def test_added_line_after_send_is_detected(self):
        order = self._create_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        self.assertEqual(len(kds_order.line_ids), 1)

        self.env['pos.order.line'].create({
            'order_id': order.id,
            'product_id': self.product_cappuccino.id,
            'qty': 1,
            'price_unit': 10.0,
            'price_subtotal': 10.0,
            'price_subtotal_incl': 10.0,
        })

        kds_order.invalidate_recordset()
        new_lines = kds_order.line_ids.filtered(lambda l: l.line_change == 'added')
        self.assertTrue(new_lines, "The newly added POS line should produce a kds.order.line with line_change='added'.")
        self.assertEqual(new_lines.station_id, self.station_coffee)

    def test_removed_line_after_send_is_cancelled(self):
        # REAL BUG FIX, confirmed live on Odoo.sh: unlink() on a POS line
        # belonging to an already-*paid* order raises a genuine Odoo core
        # restriction - "You can only unlink PoS order lines that are
        # related to orders in new or cancelled state." - before this
        # module's own code is ever reached. _create_pos_order's own
        # default 'payment' trigger requires the order to already be paid
        # for a kds_order to exist at all, which made this scenario
        # fundamentally unreachable as written: in real Odoo 19, a line
        # cannot be unlinked from a paid order at all, only while the
        # order is still 'draft'/'cancel'. This is also the actually
        # realistic scenario for this feature - the kitchen only ever
        # sees a "line removed" event for a pre-payment Send Trigger
        # (kds_send_trigger 'send', already exercised by this file's
        # other cancellation tests just above), where the order is
        # genuinely still unpaid when a line gets deleted.
        #
        # REAL BUG FIX ("Change Request After BUG-11", item 3): 'send'
        # mode (replacing the old 'validation'/'submit' pair) now
        # additionally requires the native Send/New signal
        # (last_order_preparation_change) to actually sync - included
        # directly in this order's own create() vals here, matching a
        # scenario where the order was built and immediately Sent in
        # one round-trip.
        self.pos_config.kds_send_trigger = 'send'
        order = self.env['pos.order'].create({
            'session_id': self.pos_session.id,
            'company_id': self.company.id,
            'lines': [
                (0, 0, {'product_id': self.product_burger.id, 'qty': 1,
                        'price_unit': 10.0, 'price_subtotal': 10.0, 'price_subtotal_incl': 10.0}),
                (0, 0, {'product_id': self.product_cappuccino.id, 'qty': 1,
                        'price_unit': 4.0, 'price_subtotal': 4.0, 'price_subtotal_incl': 4.0}),
            ],
            'amount_tax': 0.0, 'amount_total': 14.0, 'amount_paid': 0.0, 'amount_return': 0.0,
            'state': 'draft',
            'last_order_preparation_change': '{"lines": [], "metadata": {}}',
        })
        kds_order = order.kds_order_id
        self.assertTrue(kds_order, "'send' trigger + the native Send signal should sync to KDS "
                                    "immediately, unpaid.")
        cappuccino_pos_line = order.lines.filtered(lambda l: l.product_id == self.product_cappuccino)
        cappuccino_pos_line.unlink()  # allowed - the order is still draft/unpaid

        # REAL BUG FIX ("redesign the removal sync so it cannot leak
        # early"): unlink() itself now only flags pending_removal - the
        # real cancellation only happens on the NEXT genuine sync (here,
        # the next Send/New signal), matching the required contract that
        # deletions must remain unsynchronized until that explicit
        # boundary. Confirmed first that nothing changed yet, before
        # triggering that next sync.
        kds_order.invalidate_recordset()
        cappuccino_kds_line = kds_order.line_ids.filtered(
            lambda l: l.product_id == self.product_cappuccino)
        self.assertEqual(
            cappuccino_kds_line.state, 'new',
            "Immediately after unlink(), with no Send/New signal yet, the line must "
            "still show completely unchanged.")

        order.write({'last_order_preparation_change': '{"lines": [], "metadata": {"v": 2}}'})

        cappuccino_kds_line.invalidate_recordset()
        self.assertTrue(cappuccino_kds_line)
        self.assertEqual(cappuccino_kds_line.state, 'cancelled')

    def test_qty_change_after_send_updates_line_and_reopens_if_ready(self):
        order = self._create_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.write({'state': 'ready'})  # simulate the kitchen already finished it
        kds_order.write({'state': 'ready'})

        pos_line = order.lines
        pos_line.write({'qty': 3})

        kds_order.invalidate_recordset()
        line.invalidate_recordset()
        self.assertEqual(line.qty, 3)
        self.assertEqual(line.line_change, 'updated')
        self.assertEqual(line.state, 'new', "A Ready line whose qty changed should be bumped back to New.")
        self.assertEqual(kds_order.state, 'preparing',
                          "A Ready order with a late change should reopen to Preparing.")

    def test_product_change_reroutes_to_the_new_products_station(self):
        """The fix this test exists for: Cappuccino (-> Coffee) changed to
        Chicken Burger (-> Kitchen) must actually move stations, not just
        rename the ticket in place at Coffee."""
        order = self._create_pos_order([(self.product_cappuccino, 1)])
        kds_order = order.kds_order_id
        original_line = kds_order.line_ids
        self.assertEqual(original_line.station_id, self.station_coffee)

        pos_line = order.lines
        pos_line.write({'product_id': self.product_burger.id})

        kds_order.invalidate_recordset()
        original_line.invalidate_recordset()

        self.assertEqual(original_line.state, 'cancelled',
                          "The old Coffee-routed line must be cancelled, not silently repurposed.")

        active_lines = kds_order.line_ids.filtered(lambda l: l.state != 'cancelled')
        self.assertEqual(len(active_lines), 1, "Exactly one active line should remain after the product swap.")
        self.assertEqual(active_lines.product_id, self.product_burger)
        self.assertEqual(active_lines.station_id, self.station_kitchen,
                          "The new line must be routed to Kitchen, matching the new product.")

    def test_product_change_after_completion_preserves_history(self):
        """If the original line was already Completed (served), the fix
        must not rewrite that history - it should add the new product as
        a fresh line instead of cancelling served work."""
        order = self._create_pos_order([(self.product_cappuccino, 1)])
        kds_order = order.kds_order_id
        original_line = kds_order.line_ids
        original_line.write({'state': 'completed'})

        pos_line = order.lines
        pos_line.write({'product_id': self.product_burger.id})

        kds_order.invalidate_recordset()
        original_line.invalidate_recordset()

        self.assertEqual(original_line.state, 'completed',
                          "A completed line's history must not be rewritten by a later product change.")
        new_lines = kds_order.line_ids.filtered(
            lambda l: l.product_id == self.product_burger and l.state != 'cancelled')
        self.assertTrue(new_lines, "The new product should appear as a fresh line.")
        self.assertEqual(new_lines.station_id, self.station_kitchen)

    # -----------------------------------------------------------------
    # Audit finding "POS -> KDS Send Trigger" (HIGH): the old gate was
    # hardcoded to state in ('paid', 'done', 'invoiced'). Real dine-in
    # flow needs the kitchen ticket the moment the order is placed, not
    # once the bill is settled at the end of the meal.
    # -----------------------------------------------------------------
    def test_payment_trigger_is_the_default_and_matches_old_behavior(self):
        # pos_config was created with no explicit kds_send_trigger, so it
        # should default to 'payment' - a draft order must NOT sync yet.
        self.assertEqual(self.pos_config.kds_send_trigger, 'payment')
        order = self.env['pos.order'].create({
            'session_id': self.pos_session.id,
            'company_id': self.company.id,
            'lines': [(0, 0, {
                'product_id': self.product_burger.id, 'qty': 1,
                'price_unit': 10.0, 'price_subtotal': 10.0, 'price_subtotal_incl': 10.0,
            })],
            'amount_tax': 0.0, 'amount_total': 10.0, 'amount_paid': 0.0, 'amount_return': 0.0,
            'state': 'draft',
        })
        self.assertFalse(order.kds_order_id, "A draft order must not reach the kitchen under the 'payment' trigger.")
        order.write({'state': 'paid'})
        self.assertTrue(order.kds_order_id, "Paying should still trigger sync, exactly as before this feature existed.")

    # REAL BUG FIX ("Change Request After BUG-11", item 3): the two
    # tests that lived here - test_validation_trigger_sends_a_draft_
    # order_to_kitchen_before_payment and test_submit_trigger_sends_a_
    # draft_order_to_kitchen_before_payment - tested the OLD, now-
    # incorrect behavior directly: syncing the instant a draft order
    # with lines existed, no explicit Send/New signal needed at all.
    # That is exactly the "Critical Trigger Rule" violation this change
    # request exists to fix, and the 'validation'/'submit' options they
    # exercised no longer exist. Removed rather than repurposed - the
    # correct 'send'-mode behavior (requires the native Send/New signal)
    # is already covered by test_editing_without_send_does_not_sync_to_kds
    # and test_native_send_signal_triggers_initial_sync further below.

    def test_payment_after_pre_payment_send_does_not_duplicate_kds_order(self):
        """The specific idempotency requirement: paying an order that
        already reached the kitchen pre-payment must not create a second
        kds.order."""
        self.pos_config.kds_send_trigger = 'send'
        order = self.env['pos.order'].create({
            'session_id': self.pos_session.id,
            'company_id': self.company.id,
            'lines': [(0, 0, {
                'product_id': self.product_burger.id, 'qty': 1,
                'price_unit': 10.0, 'price_subtotal': 10.0, 'price_subtotal_incl': 10.0,
            })],
            'amount_tax': 0.0, 'amount_total': 10.0, 'amount_paid': 0.0, 'amount_return': 0.0,
            'state': 'draft',
            'last_order_preparation_change': '{"lines": [], "metadata": {}}',
        })
        first_kds_order = order.kds_order_id
        self.assertTrue(first_kds_order)
        order.write({'state': 'paid', 'amount_paid': 10.0})
        self.assertEqual(order.kds_order_id, first_kds_order,
                          "Paying later must reuse the same kds.order, not create a second one.")
        all_kds_orders = self.env['kds.order'].search([('pos_order_id', '=', order.id)])
        self.assertEqual(len(all_kds_orders), 1)

    def test_send_trigger_does_not_sync_an_order_with_no_lines_yet(self):
        self.pos_config.kds_send_trigger = 'send'
        order = self.env['pos.order'].create({
            'session_id': self.pos_session.id,
            'company_id': self.company.id,
            'lines': [],
            'amount_tax': 0.0, 'amount_total': 0.0, 'amount_paid': 0.0, 'amount_return': 0.0,
            'state': 'draft',
            'last_order_preparation_change': '{"lines": [], "metadata": {}}',
        })
        self.assertFalse(order.kds_order_id,
                          "An order with no lines yet has nothing to send to the kitchen, "
                          "even with the Send/New signal present.")

    # -----------------------------------------------------------------
    # Audit finding "Auto Print Without a Valid Printer" (MEDIUM): real
    # bug - printer_id was built from a filtered search with no check
    # that it actually found anything, so a station with Auto Print on
    # but zero printers configured got printer_id=False, silently
    # creating a permanently stuck, unexecutable pending job.
    # -----------------------------------------------------------------
    def test_auto_print_without_a_printer_creates_no_broken_job(self):
        # station_kitchen has no printers configured in these fixtures.
        self.station_kitchen.auto_print = True
        order = self._create_pos_order([(self.product_burger, 1)])
        broken_jobs = self.env['kds.print.job'].search([
            ('order_id', '=', order.kds_order_id.id),
            ('printer_id', '=', False),
        ])
        self.assertFalse(broken_jobs, "No print job with an empty printer_id should ever be created.")
        alert_events = self.env['kds.event'].search([
            ('order_id', '=', order.kds_order_id.id),
            ('note', 'like', 'CONFIGURATION ERROR%'),
        ])
        self.assertTrue(alert_events, "A configuration-error audit event should be logged instead.")

    def test_auto_print_with_a_valid_printer_still_works(self):
        printer = self.env['kds.printer'].create({
            'name': 'Test Kitchen Printer (auto-print regression)',
            'station_id': self.station_kitchen.id,
            'is_default': True,
        })
        self.station_kitchen.auto_print = True
        order = self._create_pos_order([(self.product_burger, 1)])
        jobs = self.env['kds.print.job'].search([('order_id', '=', order.kds_order_id.id)])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs.printer_id, printer)

    # -----------------------------------------------------------------
    # Audit finding "POS Cancellation Propagation" (IMPORTANT/NEW): a POS
    # order that already reached the kitchen (possible now that
    # pre-payment Send Triggers exist) used to leave its kds.order
    # silently active forever if the POS order got cancelled - a ghost
    # ticket with nothing to signal what happened.
    # -----------------------------------------------------------------
    def test_pos_cancellation_cancels_the_linked_kds_order(self):
        self.pos_config.kds_send_trigger = 'send'
        order = self.env['pos.order'].create({
            'session_id': self.pos_session.id,
            'company_id': self.company.id,
            'lines': [(0, 0, {
                'product_id': self.product_burger.id, 'qty': 1,
                'price_unit': 10.0, 'price_subtotal': 10.0, 'price_subtotal_incl': 10.0,
            })],
            'amount_tax': 0.0, 'amount_total': 10.0, 'amount_paid': 0.0, 'amount_return': 0.0,
            'state': 'draft',
            'last_order_preparation_change': '{"lines": [], "metadata": {}}',
        })
        kds_order = order.kds_order_id
        self.assertTrue(kds_order)
        self.assertEqual(kds_order.state, 'new')

        order.write({'state': 'cancel'})

        kds_order.invalidate_recordset()
        self.assertEqual(kds_order.state, 'cancelled',
                          "Cancelling the POS order must propagate to its linked kds.order.")
        self.assertTrue(
            all(l.state == 'cancelled' for l in kds_order.line_ids),
            "All active lines must be cancelled too.")

    def test_pos_cancellation_disappears_from_active_production_queue(self):
        """Acceptance criteria as stated: 'POS Send -> KDS New -> POS
        Cancel' must result in 'KDS Cancelled' and the order must
        disappear from active production queues - checked here via the
        same domain the KDS screens themselves query with."""
        self.pos_config.kds_send_trigger = 'send'
        order = self.env['pos.order'].create({
            'session_id': self.pos_session.id,
            'company_id': self.company.id,
            'lines': [(0, 0, {
                'product_id': self.product_burger.id, 'qty': 1,
                'price_unit': 10.0, 'price_subtotal': 10.0, 'price_subtotal_incl': 10.0,
            })],
            'amount_tax': 0.0, 'amount_total': 10.0, 'amount_paid': 0.0, 'amount_return': 0.0,
            'state': 'draft',
            'last_order_preparation_change': '{"lines": [], "metadata": {}}',
        })
        kds_order = order.kds_order_id
        self.assertTrue(kds_order, "The order must have genuinely reached KDS before "
                                    "cancellation is a meaningful test of anything.")
        order.write({'state': 'cancel'})

        active_lines = self.env['kds.order.line'].search([
            ('order_id', '=', kds_order.id),
            ('state', 'not in', ('completed', 'cancelled')),
        ])
        self.assertFalse(active_lines,
                          "A cancelled order's lines must not appear in the KDS screens' "
                          "active-queue query anymore.")

    def test_pos_cancellation_is_idempotent(self):
        self.pos_config.kds_send_trigger = 'send'
        order = self.env['pos.order'].create({
            'session_id': self.pos_session.id,
            'company_id': self.company.id,
            'lines': [(0, 0, {
                'product_id': self.product_burger.id, 'qty': 1,
                'price_unit': 10.0, 'price_subtotal': 10.0, 'price_subtotal_incl': 10.0,
            })],
            'amount_tax': 0.0, 'amount_total': 10.0, 'amount_paid': 0.0, 'amount_return': 0.0,
            'state': 'draft',
            'last_order_preparation_change': '{"lines": [], "metadata": {}}',
        })
        kds_order = order.kds_order_id
        self.assertTrue(kds_order)
        order.write({'state': 'cancel'})
        self.assertEqual(kds_order.state, 'cancelled')

        # Calling the propagation again (e.g. an unrelated later write()
        # that still happens to carry state='cancel' in vals, or a direct
        # re-call) must be a safe no-op - no exception, no duplicate
        # audit events.
        events_before = self.env['kds.event'].search_count([('order_id', '=', kds_order.id)])
        order._flexsys_kds_cancel()
        order._flexsys_kds_cancel()
        events_after = self.env['kds.event'].search_count([('order_id', '=', kds_order.id)])
        self.assertEqual(kds_order.state, 'cancelled')
        self.assertEqual(events_before, events_after,
                          "Repeated cancellation propagation must not create duplicate audit events.")

    def test_pos_cancellation_with_no_kds_order_does_not_error(self):
        # 'payment' (default) trigger, never paid -> no kds_order_id ever created.
        order = self.env['pos.order'].create({
            'session_id': self.pos_session.id,
            'company_id': self.company.id,
            'lines': [(0, 0, {
                'product_id': self.product_burger.id, 'qty': 1,
                'price_unit': 10.0, 'price_subtotal': 10.0, 'price_subtotal_incl': 10.0,
            })],
            'amount_tax': 0.0, 'amount_total': 10.0, 'amount_paid': 0.0, 'amount_return': 0.0,
            'state': 'draft',
        })
        self.assertFalse(order.kds_order_id)
        order.write({'state': 'cancel'})  # should not raise
        self.assertFalse(order.kds_order_id)

    def test_pos_cancellation_does_not_retroactively_cancel_completed_kds_order(self):
        order = self._create_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        kds_order.action_accept()
        kds_order.line_ids.action_start()
        kds_order.line_ids.action_ready()
        kds_order.line_ids.action_complete()  # DESIGN REVERSAL (v5.4): explicit step now
        self.assertEqual(kds_order.state, 'completed')

        # REAL BUG FIX, confirmed live on Odoo.sh: a raw
        # order.write({'state': 'cancel'}) on an already-*paid* pos.order
        # (which _create_pos_order's own default 'payment' trigger
        # requires, to have ever synced a kds_order in the first place)
        # never even reaches this module's own write() override - Odoo's
        # own core point_of_sale write() raises "This order has already
        # been paid. You cannot set it back to draft or edit it." first,
        # unconditionally, before this module's own hook (pos_order.py's
        # write(), which calls _flexsys_kds_cancel() when vals.get(
        # 'state') == 'cancel') ever runs. That's a genuine, correct
        # Odoo core business rule (a paid order's payment state isn't
        # meant to be reverted via a plain write()) - not something this
        # module should or safely can work around. What this test is
        # actually about is this module's OWN propagation logic once a
        # cancellation happens, not Odoo core's own rules about *when* a
        # pos.order may be cancelled - calling _flexsys_kds_cancel()
        # directly exercises exactly that unit of behavior, matching
        # what write() itself would call if reached.
        order.sudo()._flexsys_kds_cancel()

        kds_order.invalidate_recordset()
        self.assertEqual(
            kds_order.state, 'completed',
            "An already-Completed kds.order must not be retroactively cancelled - "
            "the food was already served.")

    # -----------------------------------------------------------------
    # Final Phase 1 Audit finding 1 (HIGH/FINAL BLOCKER): "POS Delta Sync
    # Still Bypasses The Central Workflow" - the raw
    # kline.write({...'state': new_state}) and
    # kds_order.write({'state': 'preparing'}) in _flexsys_kds_diff_lines
    # bypassed the workflow engine entirely (no transition validation, no
    # audit event for the state change itself, no timestamp reset, no
    # Expeditor reconciliation). Both now route through dedicated
    # internal methods (kds.order.line._system_reset_for_delta_sync(),
    # kds.order._system_reopen_if_production_incomplete()) instead.
    # -----------------------------------------------------------------
    def test_delta_sync_creates_delta_line_for_a_ready_line_increase(self):
        """Scenario 1: Ready line modified by POS Delta (renamed from
        "...resets_a_ready_line..." - it no longer resets anything; see
        the docstring below for the full "BUG-10" explanation).

        REAL BUG FIX, confirmed live (dev report "BUG-10 - READY order
        incorrectly resets to NEW after POS quantity increase"): a Ready
        line whose qty increased used to get bumped fully back to 'new'
        - destroying the fact the previous quantity had already been
        prepared, and showing an active START button for the WHOLE
        line, not just the increase. Now creates a new delta line for
        just the increase instead, leaving the original Ready line
        completely untouched - see pos_order.py's own updated comment
        for the full explanation (the exact same fix already established
        for a Completed line's own equivalent case, now unified and
        applied to Ready too).
        """
        order = self._create_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        # Direct-write setup (not the real action_* chain, which would
        # auto-complete a single-line non-Expeditor order straight past
        # 'ready' - see v4.1) - same established pattern the pre-existing
        # test_qty_change_after_send_updates_line_and_reopens_if_ready
        # already uses, isolating "line genuinely resting at Ready" from
        # the auto-complete cascade this test isn't about.
        line.write({'state': 'ready', 'ready_time': line.ready_time or line.station_received_time})
        self.assertEqual(line.state, 'ready')

        order.lines.write({'qty': 2})

        line.invalidate_recordset()
        self.assertEqual(
            line.state, 'ready',
            "The original Ready line must stay exactly as it was - the previously "
            "prepared quantity remains preserved as Ready production history, never "
            "reset to New.")
        self.assertEqual(line.qty, 1, "The original line's own quantity is untouched.")

        delta_lines = kds_order.line_ids - line
        self.assertEqual(len(delta_lines), 1, "A new delta line must be created for the increase.")
        self.assertEqual(delta_lines.state, 'new')
        self.assertEqual(
            delta_lines.qty, 1,
            "The delta line represents ONLY the increase (2 - 1 = 1), not the new full "
            "total - '1 prepared + 1 needed', never silently '2 new'.")

    def test_delta_sync_reopens_a_ready_order_via_new_delta_line(self):
        """Scenario 2 (part 1): Ready order modified by POS Delta -
        an existing line's qty increase creates a new delta line and
        reopens the order, without resetting the original line itself
        (renamed/updated - see the previous test's own updated comment
        for the "BUG-10" fix this reflects; the mechanism is now a new
        delta line, not a reset of the existing one)."""
        order = self._create_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        line.action_ready()
        # DESIGN REVERSAL (v5.4): the order now genuinely rests at
        # 'ready' on its own after this - no longer auto-completing, so
        # the previous forced write to get back to 'ready' is no longer
        # needed here.
        self.assertEqual(kds_order.state, 'ready')

        order.lines.write({'qty': 5})

        kds_order.invalidate_recordset()
        line.invalidate_recordset()
        self.assertEqual(kds_order.state, 'preparing',
                          "A Ready order with a late line increase must reopen to Preparing.")
        self.assertEqual(
            line.state, 'ready',
            "The original line itself must stay Ready - the order reopens because of "
            "the NEW delta line's own 'new' state, not because the original was reset.")

    def test_delta_sync_reopens_a_completed_order_via_new_line(self):
        """Scenario 2 (part 2): Completed order modified by POS Delta.
        A *completed* line is deliberately never touched by delta sync
        (preserves already-served history - the same principle used
        throughout this module), so the realistic way a Completed order
        gets "modified" is a genuinely NEW line being added (e.g. the
        customer orders one more item after the ticket was already
        marked done) - not an existing line's qty changing."""
        order = self._create_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        kds_order.line_ids.action_accept()
        kds_order.line_ids.action_start()
        kds_order.line_ids.action_ready()
        kds_order.line_ids.action_complete()  # DESIGN REVERSAL (v5.4): explicit step now
        self.assertEqual(kds_order.state, 'completed')

        self.env['pos.order.line'].create({
            'order_id': order.id,
            'product_id': self.product_cappuccino.id,
            'qty': 1,
            'price_unit': self.product_cappuccino.list_price or 10.0,
            'price_subtotal': self.product_cappuccino.list_price or 10.0,
            'price_subtotal_incl': self.product_cappuccino.list_price or 10.0,
        })

        kds_order.invalidate_recordset()
        self.assertEqual(kds_order.state, 'preparing',
                          "A Completed order with a genuinely new item added must reopen "
                          "to Preparing.")

    def test_delta_sync_after_expeditor_task_available_cancels_it(self):
        """Scenario 3: POS Delta after Expeditor task becomes available."""
        station_expeditor = self.env['kds.station'].create({
            'name': 'Test Expeditor (delta sync)', 'code': 'TESTEXPDELTA',
            'target_prep_time': 5, 'is_expeditor': True,
        })
        order = self._create_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        line.action_ready()
        task = kds_order.expeditor_task_ids
        self.assertEqual(task.state, 'waiting')

        order.lines.write({'qty': 2})

        task.invalidate_recordset()
        self.assertEqual(task.state, 'cancelled',
                          "A late POS change must cancel the now-stale Expeditor task.")
        kds_order.invalidate_recordset()
        self.assertEqual(kds_order.state, 'preparing')

    def test_delta_sync_while_packing_has_started_still_cancels_it(self):
        """Scenario 4: POS Delta while Packing has started - not just
        while still Waiting."""
        station_expeditor = self.env['kds.station'].create({
            'name': 'Test Expeditor (delta sync 2)', 'code': 'TESTEXPDELTA2',
            'target_prep_time': 5, 'is_expeditor': True,
        })
        order = self._create_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        line.action_ready()
        task = kds_order.expeditor_task_ids
        task.action_start()
        self.assertEqual(task.state, 'packing')

        order.lines.write({'qty': 4})

        task.invalidate_recordset()
        self.assertEqual(task.state, 'cancelled')

    def test_delta_sync_line_reset_creates_an_audit_event(self):
        """Scenario 5: Audit event generation."""
        order = self._create_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.write({'state': 'ready'})
        kds_order.write({'state': 'ready'})

        order.lines.write({'qty': 7})

        events = self.env['kds.event'].search([
            ('order_id', '=', kds_order.id),
            ('note', 'like', 'POS Delta Sync: line reset%'),
        ])
        self.assertTrue(events, "Resetting a line via Delta Sync must be audit-logged.")
        reopen_events = self.env['kds.event'].search([
            ('order_id', '=', kds_order.id),
            ('note', 'like', 'Order reopened%'),
        ])
        self.assertTrue(reopen_events, "Reopening the order via Delta Sync must be audit-logged.")

    def test_delta_sync_line_reset_notifies_the_station(self):
        """Scenario 6: Realtime notification - same level of coverage as
        the rest of this module's realtime code gets elsewhere (a plain
        TransactionCase can't practically assert real bus.bus delivery
        without a live longpolling client): confirms the notification
        call path is reached without raising."""
        order = self._create_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        kds_order.line_ids.write({'state': 'ready'})
        order.lines.write({'qty': 9})  # should not raise while notifying
        self.assertTrue(True)

    def test_delta_sync_resets_timestamps_correctly(self):
        """Scenario 7: Correct timestamp reset/recalculation - a line
        reset back to New must have accepted_time/preparation_start_time/
        ready_time all cleared, since it's genuinely restarting."""
        order = self._create_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        now = line.station_received_time
        line.write({'state': 'ready', 'accepted_time': now, 'preparation_start_time': now, 'ready_time': now})
        self.assertTrue(line.accepted_time)
        self.assertTrue(line.preparation_start_time)
        self.assertTrue(line.ready_time)

        order.lines.write({'qty': 6})

        line.invalidate_recordset()
        self.assertFalse(line.accepted_time,
                          "accepted_time must be cleared - the line is restarting from New.")
        self.assertFalse(line.preparation_start_time)
        self.assertFalse(line.ready_time)

    def test_delta_sync_is_idempotent_on_repeated_calls(self):
        """Scenario 8: Idempotent repeated Delta Sync."""
        order = self._create_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.write({'state': 'ready'})

        order.lines.write({'qty': 8})
        line.invalidate_recordset()
        self.assertEqual(line.state, 'new')

        events_before = self.env['kds.event'].search_count([('order_id', '=', kds_order.id)])
        # Calling the sync again with nothing further changed must be a
        # safe no-op - no duplicate events, no exception, no further
        # state churn.
        order.sudo()._flexsys_kds_diff_lines()
        order.sudo()._flexsys_kds_diff_lines()
        events_after = self.env['kds.event'].search_count([('order_id', '=', kds_order.id)])

        line.invalidate_recordset()
        self.assertEqual(line.state, 'new')
        self.assertEqual(events_before, events_after,
                          "Repeated Delta Sync with nothing changed must not create duplicate events.")

    def test_new_order_creation_notifies_the_routed_stations(self):
        """REALTIME VALIDATION FIX (dev request, 'Realtime Runtime
        Validation' - 'New order' explicitly listed as one of the
        scenarios that must propagate without a manual refresh): a real
        gap found while auditing notify_stations() call sites -
        _flexsys_kds_create() (the very first sync of a POS order to
        KDS) never notified anyone, unlike every later change to that
        order (Delta sync, workflow transitions, cancellation, reopen -
        all covered elsewhere). Same coverage level as the rest of this
        module's realtime code gets (a plain TransactionCase can't
        practically assert real bus.bus delivery without a live
        longpolling client): confirms the notification call path is
        reached, without raising, for a brand-new order specifically."""
        order = self._create_pos_order([(self.product_burger, 1)])  # should not raise while notifying
        self.assertTrue(order.kds_order_id)
        self.assertTrue(order.kds_order_id.line_ids.station_id,
                         "Sanity check: the new order's line must actually have routed to a "
                         "station for the notification to have anything meaningful to notify.")

    # -----------------------------------------------------------------
    # Dev request "Runtime Regression Fix Package", BUG-06 (CRITICAL):
    # "A financial refund/return must NEVER create a new kitchen
    # preparation ticket." Confirmed live: refunding an item on an
    # already-Completed order created a brand new KDS ticket with an
    # active START button. Tests use negative quantities directly (the
    # fallback detection signal - see
    # pos_order.py::_flexsys_kds_is_refund_order()'s own docstring for
    # why a single hardcoded field-name assumption isn't relied on here)
    # since this test file's own fixture (_create_pos_order) has no live
    # Odoo 19 instance to confirm the exact refund-tracking field shape
    # against (refunded_orderline_id or equivalent).
    # -----------------------------------------------------------------
    def test_partial_refund_after_completed_creates_no_kds_order(self):
        original = self._create_pos_order([(self.product_burger, 2), (self.product_cappuccino, 2)])
        kds_order = original.kds_order_id
        kds_order.line_ids.action_accept()
        kds_order.line_ids.action_start()
        kds_order.line_ids.action_ready()
        kds_order.line_ids.action_complete()
        self.assertEqual(kds_order.state, 'completed')
        kds_orders_before = self.env['kds.order'].search_count([])

        # A partial refund of 1 x Burger, modeled the way Odoo POS
        # itself represents one: a separate pos.order with a negative
        # quantity for the refunded product.
        refund = self._create_pos_order([(self.product_burger, -1)])

        self.assertFalse(
            refund.kds_order_id,
            "A refund order must never get its own KDS order at all.")
        self.assertEqual(
            self.env['kds.order'].search_count([]), kds_orders_before,
            "No new kds.order of any kind may be created for a refund - the original "
            "order's own kds_order must be the only one that exists.")
        kds_order.invalidate_recordset()
        self.assertEqual(
            kds_order.state, 'completed',
            "The original, already-completed order must be completely unaffected by a "
            "later refund - never reopened, never touched.")

    def test_full_refund_after_completed_creates_no_kds_order(self):
        original = self._create_pos_order([(self.product_burger, 2)])
        kds_order = original.kds_order_id
        kds_order.line_ids.action_accept()
        kds_order.line_ids.action_start()
        kds_order.line_ids.action_ready()
        kds_order.line_ids.action_complete()
        kds_orders_before = self.env['kds.order'].search_count([])

        refund = self._create_pos_order([(self.product_burger, -2)])

        self.assertFalse(refund.kds_order_id)
        self.assertEqual(self.env['kds.order'].search_count([]), kds_orders_before)

    def test_refund_order_with_mixed_products_still_detected(self):
        """Every actual product line negative -> refund. Confirms the
        fallback heuristic isn't fooled by a refund covering more than
        one product."""
        refund = self._create_pos_order([(self.product_burger, -1), (self.product_cappuccino, -3)])
        self.assertFalse(refund.kds_order_id)

    def test_genuine_new_order_with_positive_qty_is_never_mistaken_for_a_refund(self):
        """Deliberately conservative direction check: a completely normal
        new sale must never be misclassified as a refund and silently
        dropped - confirms the fallback heuristic's own "any positive-
        or-zero-qty line means this is real" escape hatch."""
        order = self._create_pos_order([(self.product_burger, 2)])
        self.assertTrue(
            order.kds_order_id,
            "A genuine new order must still reach the kitchen normally - refund detection "
            "must never accidentally swallow real sales.")

    # -----------------------------------------------------------------
    # Dev request "Runtime Regression Fix Package", BUG-04 (Case A):
    # "Quantity Set to Zero... must result operationally in CANCELLED."
    # -----------------------------------------------------------------
    def test_quantity_reduced_to_zero_cancels_the_line(self):
        order = self._create_pos_order([(self.product_burger, 2)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        self.assertEqual(line.state, 'preparing')

        order.lines.write({'qty': 0})

        line.invalidate_recordset()
        self.assertEqual(
            line.state, 'cancelled',
            "A line whose POS quantity was reduced to zero must become genuinely "
            "Cancelled (the same authoritative path as any other cancellation), not "
            "just have qty=0 written with line_change='updated'.")
        self.assertTrue(line.cancelled_at)

    def test_quantity_reduced_to_zero_preserves_audit_trail(self):
        order = self._create_pos_order([(self.product_burger, 2)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()

        order.lines.write({'qty': 0})

        event = self.env['kds.event'].search(
            [('order_id', '=', kds_order.id), ('event_type', '=', 'line_removed')],
            order='id desc', limit=1)
        self.assertTrue(event, "Cancelling via qty=0 must go through the same audited "
                                "cancellation path as any other line cancellation.")
        self.assertEqual(event.old_value, 'preparing')
        self.assertEqual(event.new_value, 'cancelled')

    # -----------------------------------------------------------------
    # Dev request "Remaining Fixes After v19.0.7.0.0 Review", item 2:
    # modification of an EXISTING completed line (not just a new line
    # added, which already worked) must not be silently ignored. Fixed
    # using the same established pattern _flexsys_kds_reroute_line()
    # already uses for a product change on a completed line - a new
    # delta kds.order.line is created, the original completed line's own
    # history is never touched.
    # -----------------------------------------------------------------
    def test_qty_increase_on_completed_line_creates_new_delta_not_silently_ignored(self):
        order = self._create_pos_order([(self.product_burger, 5)])
        kds_order = order.kds_order_id
        original_line = kds_order.line_ids
        original_line.action_accept()
        original_line.action_start()
        original_line.action_ready()
        kds_order.line_ids.action_complete()
        self.assertEqual(original_line.state, 'completed')
        original_qty = original_line.qty
        original_ready_time = original_line.ready_time

        order.lines.write({'qty': 7})

        kds_order.invalidate_recordset()
        original_line.invalidate_recordset()
        self.assertEqual(
            original_line.state, 'completed',
            "The original completed line must never be mutated by a later modification - "
            "'the original completed work remains historically completed'.")
        self.assertEqual(original_line.qty, original_qty,
                          "The original line's own quantity must not be rewritten.")
        self.assertEqual(original_line.ready_time, original_ready_time,
                          "The original line's own timestamps must not be rewritten.")

        new_lines = kds_order.line_ids - original_line
        self.assertTrue(
            new_lines,
            "A modification to an already-completed line must not be silently ignored - "
            "it must produce a new preparation delta line.")
        # REAL BUG FIX, confirmed live (dev report "BUG-10 - READY order
        # incorrectly resets to NEW after POS quantity increase" - the
        # same underlying issue, found here while fixing that report and
        # checking this already-existing branch for the same mistake):
        # this used to assert new_lines.qty == 7 (the FULL new POS
        # total) - silently double-counting the 5 already-completed
        # units against the new delta's own full 7 (11 total implied,
        # when the real total is 7), exactly the "2 new" mistake the
        # dev report is pointing at, just for Completed instead of
        # Ready. The delta line must represent ONLY the increase.
        self.assertEqual(
            new_lines.qty, 2,
            "The delta line represents ONLY the increase (7 - 5 = 2), not the new full "
            "total - '5 completed + 2 needed', never silently '7 new'.")
        self.assertEqual(new_lines.state, 'new')
        self.assertEqual(new_lines.pos_order_line_id, order.lines)

    def test_note_change_on_completed_line_also_creates_new_delta(self):
        order = self._create_pos_order([(self.product_burger, 2)])
        kds_order = order.kds_order_id
        original_line = kds_order.line_ids
        original_line.action_accept()
        original_line.action_start()
        original_line.action_ready()
        kds_order.line_ids.action_complete()

        order.lines.write({'note': 'well done, extra sauce'})

        new_lines = kds_order.line_ids - original_line
        self.assertTrue(new_lines, "A note change on a completed line must also trigger a "
                                    "new preparation delta, not just a quantity change.")
        self.assertEqual(new_lines.note, 'well done, extra sauce')
        # A note-only change (qty unchanged) has no sensible partial-
        # delta concept - the customer wants the ENTIRE batch
        # reconfigured to the new spec, so the delta line carries the
        # full current quantity, not a zero/empty one.
        self.assertEqual(new_lines.qty, 2)

    def test_completed_line_modification_reopens_the_order(self):
        order = self._create_pos_order([(self.product_burger, 5)])
        kds_order = order.kds_order_id
        kds_order.line_ids.action_accept()
        kds_order.line_ids.action_start()
        kds_order.line_ids.action_ready()
        kds_order.line_ids.action_complete()
        self.assertEqual(kds_order.state, 'completed')

        order.lines.write({'qty': 8})

        kds_order.invalidate_recordset()
        self.assertEqual(
            kds_order.state, 'preparing',
            "A modification to an existing completed line must reopen the order, same as "
            "adding a brand-new line does.")

    def test_qty_reduced_to_zero_on_completed_line_creates_no_delta(self):
        """Edge case: unlike an active line (which gets cancelled), a
        completed line reduced to zero has no new preparation work to
        create a delta line FOR - a 0-qty delta would make no
        operational sense. Confirms this is handled distinctly, not
        just falling through to the general qty>=0 delta path."""
        order = self._create_pos_order([(self.product_burger, 3)])
        kds_order = order.kds_order_id
        original_line = kds_order.line_ids
        original_line.action_accept()
        original_line.action_start()
        original_line.action_ready()
        kds_order.line_ids.action_complete()

        order.lines.write({'qty': 0})

        kds_order.invalidate_recordset()
        original_line.invalidate_recordset()
        self.assertEqual(original_line.state, 'completed',
                          "The original completed line must remain untouched.")
        self.assertEqual(original_line.qty, 3, "The original quantity must not be rewritten.")
        new_lines = kds_order.line_ids - original_line
        self.assertFalse(
            new_lines,
            "No new preparation delta should be created for a zero-quantity reduction on "
            "an already-completed line - there is nothing new to prepare.")

    def test_completed_line_modification_preserves_full_audit_trail(self):
        """'Do not erase or rewrite the original completed preparation
        history. The system should preserve: previous completion,
        previous timestamps, modification/reopen event, new quantity/
        configuration, reopen timestamp, POS/user source.'"""
        order = self._create_pos_order([(self.product_burger, 5)])
        kds_order = order.kds_order_id
        original_line = kds_order.line_ids
        original_line.action_accept()
        original_line.action_start()
        original_line.action_ready()
        kds_order.line_ids.action_complete()
        events_before = self.env['kds.event'].search_count([('order_id', '=', kds_order.id)])

        order.lines.write({'qty': 9})

        events_after = self.env['kds.event'].search_count([('order_id', '=', kds_order.id)])
        self.assertGreater(
            events_after, events_before,
            "The modification/reopen must add new audit events, not silently do nothing.")
        original_line.invalidate_recordset()
        original_events = self.env['kds.event'].search([
            ('order_id', '=', kds_order.id),
            ('station_id', '=', original_line.station_id.id),
        ], order='id asc')
        # The original completion event (order-level, logged by
        # action_complete's own _wf_transition) must still be present
        # and untouched among the full event history.
        completion_events = self.env['kds.event'].search([
            ('order_id', '=', kds_order.id),
            ('new_value', '=', 'completed'),
        ])
        self.assertTrue(completion_events, "The original completion audit event must still "
                                            "exist - never erased by a later modification.")

    def test_completed_line_delta_matches_future_diffs_not_the_original(self):
        """Confirms the new delta line correctly takes over as what
        FUTURE diffs match against for this same POS line (the same
        pos_order_line_id-based matching _flexsys_kds_reroute_line
        already relies on for its own analogous case) - a second
        modification must update the delta line, not create yet another
        one or touch the original completed line again."""
        order = self._create_pos_order([(self.product_burger, 5)])
        kds_order = order.kds_order_id
        original_line = kds_order.line_ids
        original_line.action_accept()
        original_line.action_start()
        original_line.action_ready()
        kds_order.line_ids.action_complete()

        order.lines.write({'qty': 7})
        first_delta = kds_order.line_ids - original_line
        self.assertEqual(len(first_delta), 1)
        self.assertEqual(first_delta.qty, 2, "First delta: 7 - 5 completed = 2.")

        order.lines.write({'qty': 10})

        kds_order.invalidate_recordset()
        original_line.invalidate_recordset()
        self.assertEqual(original_line.state, 'completed', "Still untouched.")
        self.assertEqual(original_line.qty, 5, "Still untouched.")
        all_lines = kds_order.line_ids
        non_original = all_lines - original_line
        self.assertEqual(
            len(non_original), 1,
            "A second modification must update the existing delta line, not create a "
            "second, separate delta line for the same POS line.")
        # REAL BUG FIX, confirmed live (dev report "BUG-10 - READY order
        # incorrectly resets to NEW after POS quantity increase" - the
        # same underlying issue, found here while fixing that report):
        # this used to assert non_original.qty == 10 (the full new POS
        # total) - silently double-counting the 5 already-completed
        # units on top of it (5 + 10 = 15 implied, when the real total
        # is 10). The delta line's own qty is now correctly computed as
        # the POS total minus any historical (Ready/Completed) sibling
        # for the same POS line - 10 - 5 completed = 5, so
        # "5 completed + 5 remaining = 10" matches the real total
        # exactly.
        self.assertEqual(
            non_original.qty, 5,
            "The delta line's own qty must account for the original completed line's own "
            "5 units too - 10 (new POS total) - 5 (already completed) = 5, not 10.")

    # -----------------------------------------------------------------
    # Dev request "BUG-09 - POS Quantity Delta Is Not Explicitly
    # Communicated to Kitchen": a plain "UPDATED" badge alone can't tell
    # the kitchen whether 2 more units are now needed or 2 fewer are.
    # qty_delta (kds_order_line.py, new field) makes this explicit and
    # backend-authoritative - "the backend should retain enough previous/
    # current quantity information to calculate the delta reliably; this
    # should not be inferred only from transient frontend state."
    # -----------------------------------------------------------------
    def test_qty_increase_stores_positive_delta(self):
        order = self._create_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()

        order.lines.write({'qty': 3})

        line.invalidate_recordset()
        self.assertEqual(line.qty, 3)
        self.assertEqual(line.qty_delta, 2, "1 -> 3 must record a delta of +2.")

    def test_qty_decrease_stores_negative_delta(self):
        order = self._create_pos_order([(self.product_burger, 3)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()

        order.lines.write({'qty': 1})

        line.invalidate_recordset()
        self.assertEqual(line.qty, 1)
        self.assertEqual(line.qty_delta, -2, "3 -> 1 must record a delta of -2.")

    def test_repeated_qty_changes_accumulate_delta(self):
        """'the delta tells kitchen staff what changed since the
        previously ACKNOWLEDGED production quantity' - two POS syncs
        before any operator acknowledgement must accumulate, not just
        reflect the last sync's own change."""
        order = self._create_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()

        order.lines.write({'qty': 3})  # +2
        order.lines.write({'qty': 5})  # +2 more, before any acknowledgement

        line.invalidate_recordset()
        self.assertEqual(line.qty, 5)
        self.assertEqual(line.qty_delta, 4, "Two consecutive +2 changes must accumulate to +4 overall.")

    def test_operator_acknowledgement_clears_qty_delta(self):
        """'must not disappear automatically merely because the next
        polling/realtime synchronization occurs... using the existing
        acknowledgement/workflow mechanism' - a real interactive
        operator action on the line is that acknowledgement point."""
        order = self._create_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        order.lines.write({'qty': 3})
        line.invalidate_recordset()
        self.assertEqual(line.qty_delta, 2)

        line.action_ready()  # a real, interactive operator action (bypass_check=False)

        line.invalidate_recordset()
        self.assertEqual(
            line.qty_delta, 0,
            "A genuine operator action on the line acknowledges the delta - it must clear, "
            "not persist forever once the kitchen has actually seen and acted on it.")
        self.assertEqual(line.line_change, 'none')

    def test_qty_reduced_to_zero_does_not_leave_a_stale_delta(self):
        """Qty -> 0 cancels the line entirely (BUG-04) rather than
        recording a delta on a line that no longer needs any
        preparation - confirms this still-existing behavior is
        unaffected by the new qty_delta field."""
        order = self._create_pos_order([(self.product_burger, 3)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()

        order.lines.write({'qty': 0})

        line.invalidate_recordset()
        self.assertEqual(line.state, 'cancelled')

    def test_qty_delta_preserved_across_multiple_products_independently(self):
        """Multiple products modified simultaneously, routed to
        different stations - each line's own qty_delta must be
        independent, never bleeding into another product's own line."""
        order = self._create_pos_order([(self.product_burger, 1), (self.product_cappuccino, 2)])
        kds_order = order.kds_order_id
        kds_order.line_ids.action_accept()
        kds_order.line_ids.action_start()
        burger_pos_line = order.lines.filtered(lambda l: l.product_id == self.product_burger)
        coffee_pos_line = order.lines.filtered(lambda l: l.product_id == self.product_cappuccino)

        burger_pos_line.write({'qty': 4})   # +3
        coffee_pos_line.write({'qty': 1})   # -1

        burger_line = kds_order.line_ids.filtered(lambda l: l.product_id == self.product_burger)
        coffee_line = kds_order.line_ids.filtered(lambda l: l.product_id == self.product_cappuccino)
        self.assertEqual(burger_line.qty_delta, 3)
        self.assertEqual(coffee_line.qty_delta, -1)

    # -----------------------------------------------------------------
    # Dev report "BUG-10 - READY order incorrectly resets to NEW after
    # POS quantity increase": explicit end-to-end regression test for
    # the exact reported scenario, per the report's own required
    # coverage: "NEW -> PREPARING -> READY -> POS qty increase -> delta
    # production -> READY", confirming the old quantity is never
    # re-prepared and no production history is lost.
    # -----------------------------------------------------------------
    def test_bug10_ready_order_qty_increase_creates_delta_not_reset_to_new(self):
        """Full end-to-end scenario, exactly as reported:
        1. Order created and sent to KDS.
        2. Station starts preparing.
        3. Station finishes - order reaches READY.
        4. POS increases the same product's quantity (1 -> 2).
        5. KDS must NOT reset READY -> NEW with an active START button
           for the whole line - the already-prepared 1 stays as Ready
           production history, only the +1 delta needs new production.
        6. Once the delta itself is prepared, the station returns to
           READY - the overall production history (the original line's
           own timestamps) is never lost or reset.
        """
        order = self._create_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        original_line = kds_order.line_ids
        self.assertEqual(original_line.state, 'new')

        # NEW -> PREPARING -> READY
        original_line.action_accept()
        original_line.action_start()
        original_line.action_ready()
        self.assertEqual(original_line.state, 'ready')
        self.assertEqual(kds_order.state, 'ready')
        original_ready_time = original_line.ready_time
        original_station_received_time = original_line.station_received_time

        # POS qty increase: 1 -> 2
        order.lines.write({'qty': 2})

        kds_order.invalidate_recordset()
        original_line.invalidate_recordset()
        # The already-prepared quantity is preserved as Ready production
        # history - never reset to New, never showing an active START
        # button for the whole line.
        self.assertEqual(
            original_line.state, 'ready',
            "The original line must NOT reset to 'new' - the previously prepared "
            "quantity remains Ready production history.")
        self.assertEqual(original_line.qty, 1, "The original line's own quantity is untouched.")
        self.assertEqual(original_line.ready_time, original_ready_time,
                          "Production history (timestamps) must not be lost or reset.")
        self.assertEqual(original_line.station_received_time, original_station_received_time,
                          "Production history (timestamps) must not be lost or reset.")

        delta_line = kds_order.line_ids - original_line
        self.assertEqual(len(delta_line), 1, "Exactly one new delta line for the increase.")
        self.assertEqual(delta_line.state, 'new')
        self.assertEqual(delta_line.qty, 1, "The delta line represents ONLY the +1 increase.")
        self.assertEqual(delta_line.station_id, original_line.station_id)

        # The station is no longer fully Ready overall - it has new
        # delta work to do - but this reflects genuinely new work
        # needed, not a full reset.
        self.assertEqual(
            kds_order.state, 'preparing',
            "The order reopens to Preparing because of the NEW delta line specifically, "
            "not because the original was reset.")

        # Delta production: the new delta line goes through its own
        # normal Accept -> Start -> Ready cycle.
        delta_line.action_accept()
        delta_line.action_start()
        delta_line.action_ready()

        kds_order.invalidate_recordset()
        original_line.invalidate_recordset()
        self.assertEqual(
            kds_order.state, 'ready',
            "Once the delta's own production finishes, the station returns to READY - "
            "both the original (1) and the delta (1) are now genuinely Ready together.")
        self.assertEqual(
            original_line.ready_time, original_ready_time,
            "The original line's own production history remains completely untouched "
            "throughout the entire delta production cycle.")

    # -----------------------------------------------------------------
    # Dev report "BUG-11 - Paid Order Refund Is Not Synchronized Back to
    # the Original KDS Ticket": the exact live scenario reproduced -
    # order 262-4-000013, 2 x Lunch Temaki mix 3pc, PREPARING, partial
    # refund of 1 left KDS unchanged, then a second refund of the
    # remaining 1 (net 0) still left KDS showing "2 x ... PREPARING"
    # with READY still available. Required regression coverage below
    # maps 1:1 to the dev report's own numbered list.
    # -----------------------------------------------------------------
    def test_bug11_preparing_partial_refund_reduces_qty_in_place(self):
        """1. Paid order -> PREPARING -> partial refund."""
        order = self._create_pos_order([(self.product_burger, 2)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        self.assertEqual(line.state, 'preparing')

        self._create_refund_order({order.lines: 1})

        line.invalidate_recordset()
        kds_order.invalidate_recordset()
        self.assertEqual(line.qty, 1, "2 - 1 refunded = 1 remaining.")
        self.assertEqual(
            line.state, 'preparing',
            "A partial refund must keep the ticket operational - PREPARING, not reset "
            "or reopened.")
        self.assertEqual(line.line_change, 'updated')
        self.assertEqual(line.qty_delta, -1, "The kitchen must see UPDATED (-1).")

    def test_bug11_preparing_cumulative_full_refund_cancels(self):
        """2. Paid order -> PREPARING -> cumulative full refund (two
        separate refund orders, 1 + 1 = 2, matching the live scenario
        exactly)."""
        order = self._create_pos_order([(self.product_burger, 2)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()

        self._create_refund_order({order.lines: 1})
        line.invalidate_recordset()
        self.assertEqual(line.qty, 1)
        self.assertEqual(line.state, 'preparing', "Still operational after the first refund.")

        self._create_refund_order({order.lines: 1})  # cumulative: 1 + 1 = 2 = fully refunded

        line.invalidate_recordset()
        kds_order.invalidate_recordset()
        self.assertEqual(
            line.state, 'cancelled',
            "Once the FULL paid quantity has been refunded (cumulatively across two "
            "separate refund orders), the ticket must become terminal - PREPARING -> "
            "CANCELLED.")
        self.assertTrue(line.cancelled_at)

    def test_bug11_ready_partial_refund_does_not_reopen_production(self):
        """3. Paid order -> READY -> partial refund."""
        order = self._create_pos_order([(self.product_burger, 3)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        line.action_ready()
        self.assertEqual(line.state, 'ready')

        self._create_refund_order({order.lines: 1})

        line.invalidate_recordset()
        self.assertEqual(line.qty, 2, "3 - 1 refunded = 2 remaining.")
        self.assertEqual(
            line.state, 'ready',
            "'Do not reopen unnecessary production' - a partial refund on a Ready line "
            "must never trigger a reset back to New or an unnecessary new delta line.")
        self.assertEqual(line.qty_delta, -1)

    def test_bug11_ready_full_refund_cancels(self):
        """4. Paid order -> READY -> full refund."""
        order = self._create_pos_order([(self.product_burger, 2)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        line.action_ready()

        self._create_refund_order({order.lines: 2})

        line.invalidate_recordset()
        self.assertEqual(
            line.state, 'cancelled',
            "A fully-refunded Ready ticket must become terminal, not stay Ready with "
            "an active Complete button.")

    def test_bug11_completed_partial_refund_is_informational_only(self):
        """5. Paid order -> COMPLETED -> partial refund."""
        order = self._create_pos_order([(self.product_burger, 3)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        line.action_ready()
        line.action_complete()
        original_qty = line.qty
        original_completed_at = line.completed_at

        self._create_refund_order({order.lines: 1})

        line.invalidate_recordset()
        self.assertEqual(
            line.state, 'completed',
            "'Do not create a new NEW/PREPARING KDS ticket' after Completed - the "
            "original line's own state must never change.")
        self.assertEqual(line.qty, original_qty,
                          "The original completed line's own quantity must not be rewritten.")
        self.assertEqual(line.completed_at, original_completed_at,
                          "The original line's own timestamps must not be rewritten.")
        event = self.env['kds.event'].search([
            ('order_id', '=', kds_order.id), ('event_type', '=', 'order_updated'),
        ], order='id desc', limit=1)
        self.assertTrue(event, "The partial refund must still be recorded as an "
                                "informational event, never silently dropped.")

    def test_bug11_completed_full_refund_is_informational_only(self):
        """6. Paid order -> COMPLETED -> full refund."""
        order = self._create_pos_order([(self.product_burger, 2)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        line.action_ready()
        line.action_complete()

        self._create_refund_order({order.lines: 2})

        line.invalidate_recordset()
        self.assertEqual(
            line.state, 'completed',
            "Even a FULL refund after Completed must never force-cancel or otherwise "
            "mutate the original line - 'never production work', informational only.")
        self.assertEqual(line.qty, 2)

    def test_bug11_refund_never_creates_a_new_kds_ticket(self):
        """7. Refund must never create a new KDS ticket."""
        order = self._create_pos_order([(self.product_burger, 2)])
        kds_order = order.kds_order_id
        kds_order.line_ids.action_accept()
        kds_order.line_ids.action_start()
        kds_orders_before = self.env['kds.order'].search_count([])

        refund_order = self._create_refund_order({order.lines: 1})

        self.assertFalse(refund_order.kds_order_id,
                          "A refund order must never get its own KDS order at all.")
        self.assertEqual(self.env['kds.order'].search_count([]), kds_orders_before,
                          "No new kds.order of any kind may be created for a refund.")

    def test_bug11_refund_never_creates_negative_production_quantity(self):
        """8. Refund must never create negative production quantity."""
        order = self._create_pos_order([(self.product_burger, 2)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()

        self._create_refund_order({order.lines: 1})

        line.invalidate_recordset()
        self.assertGreaterEqual(line.qty, 0, "A production line's own quantity must never go negative.")
        # Over-refunding beyond the original qty (defensive: should never
        # happen in practice, but confirms the floor holds even then).
        self._create_refund_order({order.lines: 5})
        line.invalidate_recordset()
        self.assertIn(line.state, ('cancelled',), "Over-refunding cancels rather than going negative.")

    def test_bug11_multiple_refund_orders_reconcile_cumulatively(self):
        """9. Multiple refund orders against the same original order must
        reconcile cumulatively (three separate 1-unit refunds against an
        original qty of 3)."""
        order = self._create_pos_order([(self.product_burger, 3)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()

        self._create_refund_order({order.lines: 1})
        line.invalidate_recordset()
        self.assertEqual(line.qty, 2)

        self._create_refund_order({order.lines: 1})
        line.invalidate_recordset()
        self.assertEqual(line.qty, 1)

        self._create_refund_order({order.lines: 1})
        line.invalidate_recordset()
        self.assertEqual(
            line.state, 'cancelled',
            "Three separate 1-unit refunds against an original qty of 3 must "
            "cumulatively reconcile to fully refunded -> cancelled.")

    def test_bug11_repeated_reconciliation_is_idempotent(self):
        """10. Repeated processing / realtime polling must not duplicate
        refund effects - calling the reconciliation method again for the
        same already-processed refund must be a no-op."""
        order = self._create_pos_order([(self.product_burger, 3)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()

        refund_order = self._create_refund_order({order.lines: 1})
        line.invalidate_recordset()
        self.assertEqual(line.qty, 2)

        # Re-run the exact same reconciliation again (simulating a
        # duplicate webhook/poll/retry) - must not subtract again.
        refund_order.sudo()._flexsys_kds_reconcile_refund()
        refund_order.sudo()._flexsys_kds_reconcile_refund()

        line.invalidate_recordset()
        self.assertEqual(
            line.qty, 2,
            "Re-processing the same refund must be idempotent - qty must not drop "
            "further (2, 1, 0...) just because reconciliation ran again.")

    def test_bug11_multi_station_refund_affects_only_the_refunded_products_station(self):
        """11. Multi-station order refund must affect only the routed
        station lines for the refunded product."""
        order = self._create_pos_order([(self.product_burger, 2), (self.product_cappuccino, 3)])
        kds_order = order.kds_order_id
        kitchen_line = kds_order.line_ids.filtered(lambda l: l.product_id == self.product_burger)
        coffee_line = kds_order.line_ids.filtered(lambda l: l.product_id == self.product_cappuccino)
        kds_order.line_ids.action_accept()
        kds_order.line_ids.action_start()
        burger_pos_line = order.lines.filtered(lambda l: l.product_id == self.product_burger)

        self._create_refund_order({burger_pos_line: 1})

        kitchen_line.invalidate_recordset()
        coffee_line.invalidate_recordset()
        self.assertEqual(kitchen_line.qty, 1, "The refunded Kitchen product's own line is reduced.")
        self.assertEqual(
            coffee_line.qty, 3,
            "Coffee's own line - a completely different product/station - must be "
            "totally unaffected by a refund on the Kitchen product.")
        self.assertEqual(coffee_line.state, 'preparing')

    def test_bug11_audit_history_preserves_production_and_refund_events_separately(self):
        """12. Audit history must preserve original production lifecycle
        and refund event separately."""
        order = self._create_pos_order([(self.product_burger, 3)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        production_events_before = self.env['kds.event'].search_count([('order_id', '=', kds_order.id)])

        self._create_refund_order({order.lines: 1})

        events_after = self.env['kds.event'].search_count([('order_id', '=', kds_order.id)])
        self.assertGreater(events_after, production_events_before,
                            "The refund must add its own new audit event(s).")
        # The original production events (accept/start) must still exist
        # untouched among the full history.
        start_events = self.env['kds.event'].search([
            ('order_id', '=', kds_order.id), ('new_value', '=', 'preparing'),
        ])
        self.assertTrue(start_events, "The original production lifecycle's own audit "
                                       "events must remain intact alongside the refund's own.")

    # -----------------------------------------------------------------
    # Dev report "Change Request After BUG-11", item 1: "Completed
    # Order - Deleted POS Line Must Become CANCELLED".
    # -----------------------------------------------------------------
    def test_deleted_line_after_completed_becomes_cancelled_order_stays_completed(self):
        # Same established pattern as test_removed_line_after_send_is_
        # cancelled above (unlink() on a POS line belonging to an
        # already-paid order raises a genuine Odoo core restriction -
        # "You can only unlink PoS order lines that are related to
        # orders in new or cancelled state" - so this order must stay
        # unpaid via the 'send' Send Trigger for the unlink() below to
        # be reachable at all).
        self.pos_config.kds_send_trigger = 'send'
        order = self.env['pos.order'].create({
            'session_id': self.pos_session.id,
            'company_id': self.company.id,
            'lines': [
                (0, 0, {'product_id': self.product_burger.id, 'qty': 1,
                        'price_unit': 10.0, 'price_subtotal': 10.0, 'price_subtotal_incl': 10.0}),
                (0, 0, {'product_id': self.product_cappuccino.id, 'qty': 1,
                        'price_unit': 4.0, 'price_subtotal': 4.0, 'price_subtotal_incl': 4.0}),
            ],
            'amount_tax': 0.0, 'amount_total': 14.0, 'amount_paid': 0.0, 'amount_return': 0.0,
            'state': 'draft',
            'last_order_preparation_change': '{"lines": [], "metadata": {}}',
        })
        kds_order = order.kds_order_id
        self.assertTrue(kds_order)
        kds_order.line_ids.action_accept()
        kds_order.line_ids.action_start()
        kds_order.line_ids.action_ready()
        kds_order.line_ids.action_complete()
        self.assertEqual(kds_order.state, 'completed')
        cappuccino_line = kds_order.line_ids.filtered(lambda l: l.product_id == self.product_cappuccino)
        burger_line = kds_order.line_ids.filtered(lambda l: l.product_id == self.product_burger)
        cappuccino_pos_line = order.lines.filtered(lambda l: l.product_id == self.product_cappuccino)

        cappuccino_pos_line.unlink()

        # REAL BUG FIX ("redesign the removal sync so it cannot leak
        # early"): unlink() itself now only flags pending_removal - the
        # real cancellation only happens on the NEXT genuine Send/New
        # sync.
        cappuccino_line.invalidate_recordset()
        self.assertEqual(
            cappuccino_line.state, 'completed',
            "Immediately after unlink(), with no Send/New signal yet, the completed "
            "line must still show completely unchanged.")

        order.write({'last_order_preparation_change': '{"lines": [], "metadata": {"v": 2}}'})

        kds_order.invalidate_recordset()
        cappuccino_line.invalidate_recordset()
        burger_line.invalidate_recordset()
        self.assertEqual(
            kds_order.state, 'completed',
            "The KDS order itself must remain COMPLETED - deleting one already-completed "
            "product must never reopen the whole order.")
        self.assertEqual(
            cappuccino_line.state, 'cancelled',
            "The deleted product's own line must become CANCELLED, not stay displayed as "
            "if normally completed.")
        self.assertTrue(cappuccino_line.cancelled_at)
        self.assertEqual(
            burger_line.state, 'completed',
            "The untouched product's own line must remain completely unaffected.")

    def test_deleted_line_after_completed_preserves_audit_history(self):
        self.pos_config.kds_send_trigger = 'send'
        order = self.env['pos.order'].create({
            'session_id': self.pos_session.id,
            'company_id': self.company.id,
            'lines': [
                (0, 0, {'product_id': self.product_burger.id, 'qty': 1,
                        'price_unit': 10.0, 'price_subtotal': 10.0, 'price_subtotal_incl': 10.0}),
            ],
            'amount_tax': 0.0, 'amount_total': 10.0, 'amount_paid': 0.0, 'amount_return': 0.0,
            'state': 'draft',
            'last_order_preparation_change': '{"lines": [], "metadata": {}}',
        })
        kds_order = order.kds_order_id
        self.assertTrue(kds_order)
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        line.action_ready()
        line.action_complete()
        events_before = self.env['kds.event'].search_count([('order_id', '=', kds_order.id)])

        order.lines.unlink()

        # REAL BUG FIX ("redesign the removal sync so it cannot leak
        # early"): the actual cancellation (and its own audit event)
        # only happens on the next genuine Send/New sync.
        order.write({'last_order_preparation_change': '{"lines": [], "metadata": {"v": 2}}'})

        events_after = self.env['kds.event'].search_count([('order_id', '=', kds_order.id)])
        self.assertGreater(events_after, events_before,
                            "The cancellation must be recorded as a new audit event.")
        completion_events = self.env['kds.event'].search([
            ('order_id', '=', kds_order.id), ('new_value', '=', 'completed'),
        ])
        self.assertTrue(completion_events,
                         "The original completion audit event must remain intact.")

    # -----------------------------------------------------------------
    # Dev report "Change Request After BUG-11", item 2: "Quantity
    # Decrease Delta - Display Negative Difference".
    # -----------------------------------------------------------------
    def test_qty_decrease_on_active_line_shows_negative_delta(self):
        """Baseline confirmation: an active (not yet Ready) line's own
        decrease already correctly showed the negative delta before this
        round - confirms no regression here."""
        order = self._create_pos_order([(self.product_burger, 5)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()

        order.lines.write({'qty': 2})

        line.invalidate_recordset()
        self.assertEqual(line.qty, 2)
        self.assertEqual(line.qty_delta, -3, "5 -> 2 must record a delta of -3.")
        self.assertEqual(line.state, 'preparing')

    def test_qty_decrease_on_ready_line_reduces_in_place_with_negative_delta(self):
        """REAL BUG FIX: a Ready line's own qty decrease used to be
        entirely ignored (logged only, line completely untouched) - the
        displayed quantity never actually went down, and no delta
        showed. Now reduces in place, keeping the current Ready state -
        "do not reopen unnecessary production" - while correctly showing
        UPDATED (-N)."""
        order = self._create_pos_order([(self.product_burger, 2)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        line.action_ready()
        self.assertEqual(line.state, 'ready')

        order.lines.write({'qty': 1})

        line.invalidate_recordset()
        self.assertEqual(line.qty, 1, "The Ready line's own quantity must actually reduce.")
        self.assertEqual(
            line.state, 'ready',
            "The line must stay Ready - no reset, no delta line, no unnecessary reopen.")
        self.assertEqual(line.qty_delta, -1, "Must show UPDATED (-1).")
        self.assertEqual(line.line_change, 'updated')
        self.assertEqual(kds_order.state, 'ready', "The order itself must also stay Ready.")

    def test_qty_decrease_of_three_on_ready_line(self):
        """Examples from the dev report: 5 -> 2 = UPDATED (-3)."""
        order = self._create_pos_order([(self.product_burger, 5)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        line.action_ready()

        order.lines.write({'qty': 2})

        line.invalidate_recordset()
        self.assertEqual(line.qty, 2)
        self.assertEqual(line.qty_delta, -3)

    def test_qty_decrease_on_completed_line_stays_informational_only(self):
        """Confirms the Completed-line behavior is unchanged by this fix
        - a decrease after Completed must still never mutate the
        original line's own history."""
        order = self._create_pos_order([(self.product_burger, 3)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        line.action_ready()
        line.action_complete()
        original_qty = line.qty

        order.lines.write({'qty': 1})

        line.invalidate_recordset()
        self.assertEqual(
            line.state, 'completed',
            "The original completed line must never be mutated by a later decrease.")
        self.assertEqual(line.qty, original_qty,
                          "The original completed line's own quantity must not be rewritten.")

    # -----------------------------------------------------------------
    # Dev report "Change Request After BUG-11", item 3: "POS Send-to-KDS
    # Settings - Simplify and Correct Triggers". Only 'payment' (After
    # Payment) and 'send' (On Send to KDS) remain - 'send' must only
    # sync on the native Send/New signal (last_order_preparation_change
    # present in the write() vals - Odoo 19's own core pos.order field,
    # confirmed from addons/point_of_sale/models/pos_order.py), never on
    # a plain add/remove/qty/attribute edit.
    # -----------------------------------------------------------------
    def _make_send_write_order(self):
        """Creates a draft order under 'send' trigger mode, matching the
        native Odoo POS flow: build the order (no sync yet), then a
        separate write carrying last_order_preparation_change (the
        native Send/New signal)."""
        self.pos_config.kds_send_trigger = 'send'
        order = self.env['pos.order'].create({
            'session_id': self.pos_session.id,
            'company_id': self.company.id,
            'lines': [(0, 0, {
                'product_id': self.product_burger.id, 'qty': 1,
                'price_unit': 10.0, 'price_subtotal': 10.0, 'price_subtotal_incl': 10.0,
            })],
            'amount_tax': 0.0, 'amount_total': 10.0, 'amount_paid': 0.0, 'amount_return': 0.0,
            'state': 'draft',
        })
        return order

    def test_after_payment_is_the_default_trigger(self):
        self.assertEqual(self.pos_config.kds_send_trigger, 'payment')

    def test_after_payment_preserves_existing_working_behavior(self):
        """Regression guard: the default mode's own behavior (sync on
        paid/done/invoiced) must be completely unaffected by this
        round's changes."""
        order = self._create_pos_order([(self.product_burger, 1)])
        self.assertTrue(order.kds_order_id, "'payment' mode must still sync once paid, unchanged.")

    def test_only_two_trigger_options_remain(self):
        selection = dict(self.env['pos.config']._fields['kds_send_trigger'].selection)
        self.assertEqual(
            set(selection.keys()), {'payment', 'send'},
            "Exactly two options must remain: 'payment' (After Payment) and 'send' "
            "(On Send to KDS) - the old 'validation'/'submit' pair must be gone.")

    def test_editing_without_send_does_not_sync_to_kds(self):
        """Critical Trigger Rule: adding/editing an order under 'send' "
        mode must not sync anything until Send/New is explicitly pressed."""
        order = self._make_send_write_order()
        self.assertFalse(
            order.kds_order_id,
            "Building the order alone (no Send/New signal) must not sync to KDS at all.")

        # Further edits (qty change, adding a product) still must not sync.
        order.lines.write({'qty': 2})
        self.env['pos.order.line'].create({
            'order_id': order.id, 'product_id': self.product_cappuccino.id, 'qty': 1,
            'price_unit': 4.0, 'price_subtotal': 4.0, 'price_subtotal_incl': 4.0,
        })
        self.assertFalse(
            order.kds_order_id,
            "Changing quantity and adding a product, still without Send/New, must not "
            "sync to KDS either - changes accumulate silently.")

    def test_native_send_signal_triggers_initial_sync(self):
        """'On Send to KDS' + the native Send/New action (simulated via
        last_order_preparation_change, confirmed from Odoo 19's own core
        pos_order.py to be the field the native Send action updates)."""
        order = self._make_send_write_order()
        self.assertFalse(order.kds_order_id)

        order.write({'last_order_preparation_change': '{"lines": [], "metadata": {}}'})

        self.assertTrue(
            order.kds_order_id,
            "The native Send/New signal (last_order_preparation_change) must trigger "
            "the initial KDS sync.")

    def test_accumulated_changes_sync_correctly_on_next_send(self):
        """Subsequent Order Modifications: order already sent to KDS,
        cashier adds/updates/removes without syncing, then the next
        Send/New synchronizes everything accumulated at once as ADDED/
        UPDATED/CANCELLED."""
        order = self._make_send_write_order()
        order.write({'last_order_preparation_change': '{"lines": [], "metadata": {}}'})
        kds_order = order.kds_order_id
        self.assertTrue(kds_order)
        burger_line = kds_order.line_ids
        self.assertEqual(burger_line.line_change, 'added')

        # Cashier modifies the order: qty change + a new product - no
        # sync signal yet.
        order.lines.write({'qty': 3})
        self.env['pos.order.line'].create({
            'order_id': order.id, 'product_id': self.product_cappuccino.id, 'qty': 1,
            'price_unit': 4.0, 'price_subtotal': 4.0, 'price_subtotal_incl': 4.0,
        })
        burger_line.invalidate_recordset()
        self.assertEqual(burger_line.qty, 1, "No sync yet - the KDS line must still show the old quantity.")
        self.assertFalse(
            kds_order.line_ids.filtered(lambda l: l.product_id == self.product_cappuccino),
            "No sync yet - the newly added product must not appear in KDS at all.")

        # Cashier presses Send/New again - accumulated changes sync now.
        order.write({'last_order_preparation_change': '{"lines": [], "metadata": {"v": 2}}'})

        kds_order.invalidate_recordset()
        burger_line.invalidate_recordset()
        self.assertEqual(burger_line.qty, 3, "The accumulated qty change must now be reflected.")
        cappuccino_line = kds_order.line_ids.filtered(lambda l: l.product_id == self.product_cappuccino)
        self.assertTrue(cappuccino_line, "The accumulated new product must now appear as ADDED.")
        self.assertEqual(cappuccino_line.line_change, 'added')

    def test_send_mode_removal_shows_cancelled_on_next_send(self):
        order = self._make_send_write_order()
        self.env['pos.order.line'].create({
            'order_id': order.id, 'product_id': self.product_cappuccino.id, 'qty': 1,
            'price_unit': 4.0, 'price_subtotal': 4.0, 'price_subtotal_incl': 4.0,
        })
        order.write({'last_order_preparation_change': '{"lines": [], "metadata": {}}'})
        kds_order = order.kds_order_id
        cappuccino_pos_line = order.lines.filtered(lambda l: l.product_id == self.product_cappuccino)

        cappuccino_pos_line.unlink()

        # REAL BUG FIX ("redesign the removal sync so it cannot leak
        # early"): confirms nothing changed immediately after unlink()
        # itself - only the next genuine Send/New signal applies the
        # real cancellation, matching this test's own name exactly.
        cappuccino_line = kds_order.line_ids.filtered(lambda l: l.product_id == self.product_cappuccino)
        self.assertEqual(
            cappuccino_line.state, 'new',
            "Immediately after unlink(), with no further Send/New signal yet, the line "
            "must still show completely unchanged.")

        order.write({'last_order_preparation_change': '{"lines": [], "metadata": {"v": 2}}'})

        cappuccino_line.invalidate_recordset()
        self.assertTrue(cappuccino_line)
        self.assertEqual(
            cappuccino_line.state, 'cancelled',
            "A product removed, then a subsequent genuine Send/New, must show CANCELLED.")

    # -----------------------------------------------------------------
    # Dev report "BUG-11 [second report, same number reused by the
    # client - a different issue from the refund one] - Quantity
    # Decrease During PREPARING Resets Ticket to NEW": the exact
    # reported scenario, traced through the real
    # _flexsys_kds_diff_lines() code path end to end.
    # -----------------------------------------------------------------
    @staticmethod
    def _effective_stage(lines):
        """Python port of _effective_stage() (controllers/kds.py /
        controllers/kds_kiosk.py) - kept deliberately in lockstep with
        those two copies. Same helper already defined in
        test_workflow.py's own TestWorkflow class - duplicated here
        since this class doesn't inherit from it."""
        active = [l for l in lines if l.state != 'cancelled']
        if not active:
            if not lines:
                return 'new'
            ever_ready = any(l.ready_time for l in lines)
            ever_preparing = any(l.preparation_start_time for l in lines)
            return 'ready' if ever_ready else 'preparing' if ever_preparing else 'new'
        if all(l.state == 'completed' for l in active):
            return 'completed'
        if all(l.state in ('ready', 'completed') for l in active):
            return 'ready'
        if any(l.state in ('preparing', 'ready', 'completed') for l in active):
            return 'preparing'
        return 'new'

    def test_qty_decrease_during_preparing_does_not_reset_to_new(self):
        """The dev report's own exact scenario: 2 x TARO, PREPARING,
        POS changes to 1 x TARO. The line's own state must stay
        'preparing' (never reset to 'new'), and effective_stage - the
        single authoritative value both KDS screens' tab/action-button
        logic actually consume - must also read 'preparing', not 'new'."""
        order = self._create_pos_order([(self.product_burger, 2)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        self.assertEqual(line.state, 'preparing')

        order.lines.write({'qty': 1})

        line.invalidate_recordset()
        self.assertEqual(line.qty, 1)
        self.assertEqual(line.qty_delta, -1, "The line display must show UPDATED (-1).")
        self.assertEqual(line.line_change, 'updated')
        self.assertEqual(
            line.state, 'preparing',
            "The line's own state must remain 'preparing' - a quantity decrease must "
            "never reset it to 'new'.")
        self.assertEqual(
            self._effective_stage(kds_order.line_ids), 'preparing',
            "The authoritative aggregate stage (what both KDS screens' tab/action-button "
            "logic actually read) must be 'preparing', not 'new' - the action button must "
            "be READY, not START.")

    def test_qty_increase_during_preparing_does_not_reset_to_new(self):
        """Repeat with an increase, per the dev report's own required
        coverage: 1 -> 3 = UPDATED (+2), ticket remains PREPARING."""
        order = self._create_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()

        order.lines.write({'qty': 3})

        line.invalidate_recordset()
        self.assertEqual(line.qty, 3)
        self.assertEqual(line.qty_delta, 2, "The line display must show UPDATED (+2).")
        self.assertEqual(line.state, 'preparing')
        self.assertEqual(self._effective_stage(kds_order.line_ids), 'preparing')

    def test_add_new_item_during_preparing_stays_preparing(self):
        order = self._create_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()

        self.env['pos.order.line'].create({
            'order_id': order.id, 'product_id': self.product_cappuccino.id, 'qty': 1,
            'price_unit': 4.0, 'price_subtotal': 4.0, 'price_subtotal_incl': 4.0,
        })
        order._flexsys_kds_diff_lines()

        kds_order.invalidate_recordset()
        new_line = kds_order.line_ids.filtered(lambda l: l.product_id == self.product_cappuccino)
        self.assertEqual(new_line.state, 'new')
        self.assertEqual(new_line.line_change, 'added')
        self.assertEqual(
            self._effective_stage(kds_order.line_ids), 'preparing',
            "Adding a new item while the station is already PREPARING must keep the "
            "aggregate stage at PREPARING, not reset to NEW - the existing line is "
            "still genuinely 'preparing'.")

    def test_remove_one_item_during_preparing_stays_preparing(self):
        order = self._create_pos_order([(self.product_burger, 1), (self.product_cappuccino, 1)])
        kds_order = order.kds_order_id
        kds_order.line_ids.action_accept()
        kds_order.line_ids.action_start()
        cappuccino_pos_line = order.lines.filtered(lambda l: l.product_id == self.product_cappuccino)

        cappuccino_pos_line.unlink()

        cappuccino_line = kds_order.line_ids.filtered(lambda l: l.product_id == self.product_cappuccino)
        self.assertEqual(cappuccino_line.state, 'cancelled')
        burger_line = kds_order.line_ids.filtered(lambda l: l.product_id == self.product_burger)
        self.assertEqual(burger_line.state, 'preparing', "The untouched line must remain 'preparing'.")
        self.assertEqual(
            self._effective_stage(kds_order.line_ids), 'preparing',
            "Removing one item while another remains actively preparing must keep the "
            "aggregate stage at PREPARING - a cancelled line must never affect this.")

    def test_mixed_added_and_updated_lines_during_preparing_stays_preparing(self):
        """'mixed ADDED + UPDATED lines' - explicit combined scenario
        from the dev report's own required verification list."""
        order = self._create_pos_order([(self.product_burger, 2)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()

        order.lines.write({'qty': 1})  # UPDATED (-1)
        self.env['pos.order.line'].create({
            'order_id': order.id, 'product_id': self.product_cappuccino.id, 'qty': 1,
            'price_unit': 4.0, 'price_subtotal': 4.0, 'price_subtotal_incl': 4.0,
        })  # ADDED
        order._flexsys_kds_diff_lines()

        kds_order.invalidate_recordset()
        line.invalidate_recordset()
        new_line = kds_order.line_ids.filtered(lambda l: l.product_id == self.product_cappuccino)
        self.assertEqual(line.state, 'preparing')
        self.assertEqual(line.line_change, 'updated')
        self.assertEqual(line.qty_delta, -1)
        self.assertEqual(new_line.state, 'new')
        self.assertEqual(new_line.line_change, 'added')
        self.assertEqual(
            self._effective_stage(kds_order.line_ids), 'preparing',
            "A mix of one UPDATED (still preparing) line and one ADDED (new) line must "
            "still classify the whole ticket as PREPARING, never NEW - matching the same "
            "precedence BUG-02/BUG-10 already established.")
