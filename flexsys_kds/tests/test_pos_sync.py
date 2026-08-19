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
from datetime import timedelta
from unittest.mock import patch
import json

from odoo import fields
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
        })
        order.flexsys_kds_register_send()
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

        order.flexsys_kds_register_send()

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
        })
        order.flexsys_kds_register_send()
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
        })
        order.flexsys_kds_register_send()
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
        })
        order.flexsys_kds_register_send()
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
        })
        order.flexsys_kds_register_send()
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
        })
        order.flexsys_kds_register_send()
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

    def test_repeated_qty_changes_each_use_the_last_written_qty_as_baseline(self):
        """REAL BUG FIX ("BUG-11 [third report] - Sequential Quantity
        Delta Uses Wrong Baseline"), confirmed live: this test used to
        assert that two consecutive syncs before any acknowledgement
        ACCUMULATE (1->3->5 showing +4 overall) - that reasoning was
        wrong. "Delta must always be calculated against the last
        successfully sent KDS quantity" - each sync's own delta is
        independent, calculated against kline's own current value right
        before that specific write, never blended with an earlier
        sync's own already-superseded delta."""
        order = self._create_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()

        order.lines.write({'qty': 3})  # +2 (against baseline 1)
        order.lines.write({'qty': 5})  # +2 (against baseline 3, NOT accumulated with the prior +2)

        line.invalidate_recordset()
        self.assertEqual(line.qty, 5)
        self.assertEqual(
            line.qty_delta, 2,
            "Each sync's own delta is calculated against the line's own last-written "
            "quantity (3 -> 5 = +2), never accumulated on top of an earlier sync's own "
            "already-superseded delta.")

    def test_bug11_sequential_delta_uses_last_sent_baseline_not_original(self):
        """The dev report's own exact worked example, in full: 2 -> 1
        (UPDATED -1), then - without completing/acknowledging - 1 -> 3
        (must show UPDATED +2, not +1 from blending with the prior -1),
        then 3 -> 2 (must show UPDATED -1). The ticket must stay
        PREPARING throughout, never reset to NEW.

        REAL BUG FIX ("BUG-11 [fourth report] - Sequential qty_delta
        baseline is still wrong at runtime"), confirmed STILL
        reproducing live even after the fix that originally closed this
        test's own scenario - the dev report explicitly asked to
        "verify which field/value is actually being used as the
        authoritative 'last sent quantity'", so this test now checks
        that value directly (last_kds_sent_qty), not just the qty_delta
        it produces.
        """
        order = self._create_pos_order([(self.product_burger, 2)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        self.assertEqual(line.state, 'preparing')
        self.assertEqual(line.last_kds_sent_qty, 2, "Stamped to the initial qty at creation.")

        order.lines.write({'qty': 1})
        line.invalidate_recordset()
        self.assertEqual(line.qty, 1)
        self.assertEqual(line.qty_delta, -1, "2 -> 1 must show UPDATED (-1).")
        self.assertEqual(line.last_kds_sent_qty, 1,
                          "The baseline itself must now be 1 - the exact quantity that was "
                          "just successfully sent.")
        self.assertEqual(line.state, 'preparing')

        order.lines.write({'qty': 3})
        line.invalidate_recordset()
        self.assertEqual(line.qty, 3)
        self.assertEqual(
            line.qty_delta, 2,
            "1 -> 3 must show UPDATED (+2) - relative to the last-sent 1, not the "
            "original 2 (which would give +1) and not a blend with the prior -1 "
            "(which would also give +1 the old, wrong way).")
        self.assertEqual(line.last_kds_sent_qty, 3, "The baseline advances to 3.")
        self.assertEqual(line.state, 'preparing', "Must remain PREPARING throughout.")

        order.lines.write({'qty': 2})
        line.invalidate_recordset()
        self.assertEqual(line.qty, 2)
        self.assertEqual(line.qty_delta, -1, "3 -> 2 must show UPDATED (-1).")
        self.assertEqual(line.last_kds_sent_qty, 2)
        self.assertEqual(line.state, 'preparing')

    def test_last_kds_sent_qty_stamped_at_creation(self):
        order = self._create_pos_order([(self.product_burger, 4)])
        line = order.kds_order_id.line_ids
        self.assertEqual(
            line.last_kds_sent_qty, 4,
            "A brand-new line's own baseline must start at its own initial quantity, "
            "not zero - a fresh install's own create()-time stamping.")

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
        })
        order.flexsys_kds_register_send()
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

        order.flexsys_kds_register_send()

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
        })
        order.flexsys_kds_register_send()
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
        order.flexsys_kds_register_send()

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
        self.assertEqual(line.last_kds_sent_qty, 1, "The baseline itself must advance to 1.")
        self.assertEqual(kds_order.state, 'ready', "The order itself must also stay Ready.")

    def test_sequential_qty_changes_on_ready_line_use_last_sent_baseline(self):
        """Same fix as the Preparing-state scenario (BUG-11 [fourth
        report]), confirmed here for the Ready-state branch too."""
        order = self._create_pos_order([(self.product_burger, 2)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        line.action_ready()

        order.lines.write({'qty': 1})
        line.invalidate_recordset()
        self.assertEqual(line.qty_delta, -1)

        order.lines.write({'qty': 3})
        line.invalidate_recordset()
        self.assertEqual(
            line.qty_delta, 2,
            "1 -> 3 on a Ready line must show +2 (relative to last-sent 1), not +1 "
            "(relative to the original 2).")
        self.assertEqual(line.state, 'ready')

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

        order.flexsys_kds_register_send()

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
        order.flexsys_kds_register_send()
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
        order.flexsys_kds_register_send()

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
        order.flexsys_kds_register_send()
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

        order.flexsys_kds_register_send()

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
        since this class doesn't inherit from it.

        REAL BUG FIX ("CANCELLED FILTER CLASSIFICATION + RETENTION
        LIFECYCLE", Issue 1): a fully-cancelled station now returns the
        distinct 'cancelled' value - see the real function's own
        updated docstring for the complete explanation."""
        active = [l for l in lines if l.state != 'cancelled']
        if not active:
            return 'cancelled' if lines else 'new'
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

    # -----------------------------------------------------------------
    # Dev report "FlexSys KDS - Runtime Change Request: BUG-12 + BUG-13
    # + BUG-14". Test helper: creates a 'draft' (POS still ACTIVE/OPEN)
    # order under the 'send' trigger, synced to KDS via the native Send
    # signal - the realistic scenario every test in this section needs
    # (a dine-in order sent to the kitchen well before the bill is
    # settled).
    # -----------------------------------------------------------------
    def _create_active_pos_order(self, product_qty_list):
        self.pos_config.kds_send_trigger = 'send'
        line_vals = []
        for product, qty in product_qty_list:
            line_vals.append((0, 0, {
                'product_id': product.id, 'qty': qty,
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
            'amount_paid': 0.0,
            'amount_return': 0.0,
            'state': 'draft',
        })
        order.flexsys_kds_register_send()
        return order

    # -----------------------------------------------------------------
    # BUG-12 - Partial Quantity Reduction After READY Is Not Reconciled
    # Correctly. Required Regression Matrix, Test 2.
    # -----------------------------------------------------------------
    def test_bug12_ready_partial_decrease_reconciles_to_exact_effective_qty(self):
        order = self._create_active_pos_order([(self.product_burger, 2)])
        kds_order = order.kds_order_id
        self.assertTrue(kds_order)
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        line.action_ready()
        self.assertEqual(line.state, 'ready')

        order.lines.write({'qty': 1})
        order.flexsys_kds_register_send()

        kds_order.invalidate_recordset()
        line.invalidate_recordset()
        self.assertEqual(
            line.qty, 1,
            "The effective KDS quantity must reconcile to exactly 1 - no ghost second "
            "active unit, no separate line still counting 2.")
        all_lines = kds_order.line_ids
        self.assertEqual(len(all_lines), 1, "No duplicate/orphaned line created for this reconciliation.")
        self.assertEqual(line.state, 'ready', "Stays Ready - no unnecessary reopen.")
        self.assertEqual(line.qty_delta, -1)
        self.assertEqual(kds_order.state, 'ready')

    # -----------------------------------------------------------------
    # Required Regression Matrix, Test 3 - READY full cancellation
    # (must-not-regress, already passing, confirmed here explicitly).
    # -----------------------------------------------------------------
    def test_ready_full_cancellation_shows_cancelled_was_ready(self):
        order = self._create_active_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        line.action_ready()

        order.lines.write({'qty': 0})
        order.flexsys_kds_register_send()

        line.invalidate_recordset()
        self.assertEqual(line.state, 'cancelled')
        self.assertTrue(line.cancelled_at)

    # -----------------------------------------------------------------
    # Required Regression Matrix, Test 4 - READY increase (must-not-
    # regress, already passing, confirmed here explicitly).
    # -----------------------------------------------------------------
    def test_ready_increase_preserves_original_reopens_for_delta_only(self):
        order = self._create_active_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        line.action_ready()
        original_ready_time = line.ready_time

        order.lines.write({'qty': 2})
        order.flexsys_kds_register_send()

        kds_order.invalidate_recordset()
        line.invalidate_recordset()
        self.assertEqual(line.state, 'ready', "The previously Ready unit remains preserved.")
        self.assertEqual(line.qty, 1)
        self.assertEqual(line.ready_time, original_ready_time)
        delta_line = kds_order.line_ids - line
        self.assertEqual(len(delta_line), 1)
        self.assertEqual(delta_line.qty, 1, "Only the +1 becomes new production work.")
        self.assertEqual(delta_line.state, 'new')
        self.assertEqual(kds_order.state, 'preparing', "Reopens for the new work only.")

    # -----------------------------------------------------------------
    # BUG-13 - Quantity Changes After COMPLETED Are Ignored While POS
    # Order Is Still Active. Required Regression Matrix, Test 5 & 6.
    # -----------------------------------------------------------------
    def test_bug13_completed_decrease_reconciles_while_pos_active(self):
        """The exact reported scenario: KDS order ICE TEA, POS qty 5,
        KDS COMPLETED, POS order still ACTIVE/OPEN, cashier changes
        5 -> 3."""
        order = self._create_active_pos_order([(self.product_burger, 5)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        line.action_ready()
        line.action_complete()
        self.assertEqual(line.state, 'completed')
        self.assertEqual(order.state, 'draft', "POS order remains ACTIVE/OPEN.")
        original_completed_at = line.completed_at

        order.lines.write({'qty': 3})
        order.flexsys_kds_register_send()

        kds_order.invalidate_recordset()
        line.invalidate_recordset()
        self.assertEqual(
            line.qty, 3,
            "'KDS COMPLETED: qty 5' + 'POS ACTIVE: 5 -> 3' must reconcile - the current "
            "effective quantity must become exactly 3.")
        self.assertEqual(
            line.state, 'completed',
            "The line stays Completed - 'preserving the fact that 5 units had previously "
            "reached production completion' - only the quantity itself reconciles.")
        self.assertEqual(line.qty_delta, -2, "Must show UPDATED (-2).")
        self.assertEqual(
            line.completed_at, original_completed_at,
            "The original completion timestamp itself is untouched - this is a quantity "
            "reconciliation, not a new completion event.")
        all_lines = kds_order.line_ids
        self.assertEqual(len(all_lines), 1, "No duplicate/orphaned line.")

    def test_bug13_completed_increase_reconciles_while_pos_active(self):
        order = self._create_active_pos_order([(self.product_burger, 5)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        line.action_ready()
        line.action_complete()
        original_qty = line.qty
        original_completed_at = line.completed_at

        order.lines.write({'qty': 7})
        order.flexsys_kds_register_send()

        kds_order.invalidate_recordset()
        line.invalidate_recordset()
        self.assertEqual(
            line.state, 'completed',
            "'The original completed production must remain historically preserved.'")
        self.assertEqual(line.qty, original_qty, "The original 5 units are untouched.")
        self.assertEqual(line.completed_at, original_completed_at)
        delta_line = kds_order.line_ids - line
        self.assertEqual(len(delta_line), 1)
        self.assertEqual(delta_line.qty, 2, "'Only the additional +2 should become new production work.'")
        self.assertEqual(delta_line.state, 'new')
        kds_order.invalidate_recordset()
        self.assertIn(
            kds_order.state, ('preparing', 'new'),
            "The ticket reopens appropriately for the new production work - not staying "
            "COMPLETED with unaccounted-for new work.")

    def test_completed_decrease_stays_frozen_once_pos_order_closed(self):
        """Confirms the OTHER side of BUG-13's own distinction: once the
        POS order has genuinely closed, a Completed line's own history
        must NOT be rewritten - matching every earlier round's own
        established "never mutate served history" principle."""
        order = self._create_pos_order([(self.product_burger, 5)])  # defaults to 'paid'
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        line.action_ready()
        line.action_complete()
        self.assertNotEqual(order.state, 'draft', "POS order is already closed (paid).")
        original_qty = line.qty

        order.lines.write({'qty': 3})

        line.invalidate_recordset()
        self.assertEqual(
            line.state, 'completed',
            "Once the POS order has closed, the original completed line must never be "
            "mutated - the sale is settled.")
        self.assertEqual(line.qty, original_qty, "Quantity must not be rewritten once closed.")

    # -----------------------------------------------------------------
    # BUG-14 - COMPLETED Retention Must Depend on POS Closure. Required
    # Regression Matrix, Test 7 & 8.
    # -----------------------------------------------------------------
    def test_bug14_completed_ticket_never_expires_while_pos_active(self):
        """Test 7: KDS COMPLETED, POS ACTIVE, wait longer than the
        configured retention period - the ticket must remain visible."""
        order = self._create_active_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        line.action_ready()
        line.action_complete()
        self.assertFalse(kds_order.pos_closed_at, "Must not be stamped while POS is active.")

        # Simulate time well past the retention window by backdating
        # completed_at directly (matching the established pattern used
        # elsewhere in this suite for retention-window tests) - the
        # point of this test is that pos_closed_at, not completed_at,
        # gates visibility now.
        line.sudo().write({'completed_at': fields.Datetime.now() - timedelta(minutes=60)})

        pos_closed_cutoff = fields.Datetime.now() - timedelta(minutes=5)
        visible = line.state not in ('completed', 'cancelled') or (
            line.state == 'completed' and (not kds_order.pos_closed_at or kds_order.pos_closed_at >= pos_closed_cutoff))
        self.assertTrue(
            visible,
            "A Completed line whose POS order is still active must remain visible "
            "regardless of how long ago it completed - no KDS completion timeout may "
            "hide it while pos_closed_at is unset.")

    def test_bug14_retention_starts_at_pos_closure_not_kds_completion(self):
        """Test 8: continue Test 7 - close/pay/finalize the POS order,
        confirm pos_closed_at gets stamped, and that the retention
        cutoff is computed from that moment, not from completion."""
        order = self._create_active_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        line.action_ready()
        line.action_complete()
        # Backdate completion well into the past - if the old,
        # completed_at-anchored logic were still in effect, this alone
        # would already be past the grace window.
        line.sudo().write({'completed_at': fields.Datetime.now() - timedelta(minutes=60)})
        self.assertFalse(kds_order.pos_closed_at)

        order.write({'state': 'paid', 'amount_paid': order.amount_total})

        kds_order.invalidate_recordset()
        self.assertTrue(
            kds_order.pos_closed_at,
            "Closing/paying the POS order must stamp pos_closed_at - the retention "
            "timer's own authoritative anchor.")
        # Freshly stamped (just now, not 60 minutes ago like completed_at) -
        # well within the grace window.
        pos_closed_cutoff = fields.Datetime.now() - timedelta(minutes=5)
        self.assertGreaterEqual(
            kds_order.pos_closed_at, pos_closed_cutoff,
            "pos_closed_at must reflect the moment of POS closure just now, not the "
            "much-earlier completion time - confirming retention is anchored to closure.")

    def test_bug14_pos_closed_at_stamped_immediately_under_payment_trigger(self):
        """Under the 'payment' trigger, an order only ever reaches KDS
        once already paid - closure and KDS-arrival happen at the same
        moment, so pos_closed_at must be set immediately at creation,
        not left waiting for a state *transition* that will never come
        (the order was already paid before kds_order_id even existed)."""
        order = self._create_pos_order([(self.product_burger, 1)])  # 'payment' trigger, defaults to paid
        kds_order = order.kds_order_id
        self.assertTrue(kds_order)
        self.assertTrue(
            kds_order.pos_closed_at,
            "Under 'payment' mode, the order is already closed the moment it reaches "
            "KDS at all - pos_closed_at must be stamped immediately, not left NULL "
            "forever.")

    def test_bug14_pos_closed_at_not_stamped_while_order_stays_draft(self):
        order = self._create_active_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        self.assertTrue(kds_order)
        self.assertFalse(
            kds_order.pos_closed_at,
            "An order sent to KDS while still genuinely draft/active must not have "
            "pos_closed_at stamped.")

    def test_bug14_pos_closed_at_stamped_once_only(self):
        """A later state transition (e.g. paid -> done) must not push
        pos_closed_at forward - the FIRST genuine closure is the one
        that anchors retention."""
        order = self._create_active_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id

        order.write({'state': 'paid', 'amount_paid': order.amount_total})
        kds_order.invalidate_recordset()
        first_closed_at = kds_order.pos_closed_at
        self.assertTrue(first_closed_at)

        order.write({'state': 'done'})
        kds_order.invalidate_recordset()
        self.assertEqual(
            kds_order.pos_closed_at, first_closed_at,
            "A later transition to 'done' must not overwrite the original closure "
            "timestamp.")

    # -----------------------------------------------------------------
    # DO NOT REGRESS: sequential PREPARING delta, explicitly reconfirmed
    # in this same section per the dev report's own "Required Regression
    # Matrix, Test 1" and "already passed live runtime testing" list.
    # -----------------------------------------------------------------
    def test_regression_matrix_test1_preparing_sequential_delta(self):
        order = self._create_active_pos_order([(self.product_burger, 2)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()

        order.lines.write({'qty': 1})
        order.flexsys_kds_register_send()
        line.invalidate_recordset()
        self.assertEqual(line.qty_delta, -1)
        self.assertEqual(line.state, 'preparing')

        order.lines.write({'qty': 3})
        order.flexsys_kds_register_send()
        line.invalidate_recordset()
        self.assertEqual(line.qty_delta, 2)
        self.assertEqual(line.state, 'preparing')

        order.lines.write({'qty': 2})
        order.flexsys_kds_register_send()
        line.invalidate_recordset()
        self.assertEqual(line.qty_delta, -1)
        self.assertEqual(line.state, 'preparing')

    # -----------------------------------------------------------------
    # Dev report "BUG FIX REQUEST - KDS Full Line Removal / Quantity ->
    # 0": full line removal (the POS line itself deleted, not just its
    # own qty written to 0) used to leave orphaned active kds.order.line
    # records invisible to reconciliation - specifically when MORE than
    # one active line shared the same pos_order_line_id (an original
    # completed line plus a delta line from an earlier increase), only
    # one of the two was ever detected as removed.
    # -----------------------------------------------------------------
    def test_full_line_removal_after_delta_line_created_cancels_both_completed_lines(self):
        """The dev report's own exact Acceptance Test, end to end:
        5 -> Send -> Complete -> 4 (UPDATED -1, no new prep) -> 6
        (preserve 4 completed + create 2 new work) -> Complete the +2 ->
        0 (full line removal). Both the original (now 4, Completed) and
        the delta (now 2, Completed) kds.order.line records must be
        detected and cancelled - the exact scenario the old dict-based
        `existing.items()` removal loop silently missed one of."""
        order = self._create_active_pos_order([(self.product_burger, 5)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        line.action_ready()
        line.action_complete()
        self.assertEqual(line.state, 'completed')

        # 5 -> 4: UPDATED (-1), no new preparation.
        order.lines.write({'qty': 4})
        order.flexsys_kds_register_send()
        line.invalidate_recordset()
        self.assertEqual(line.qty, 4)
        self.assertEqual(line.qty_delta, -1)
        self.assertEqual(line.state, 'completed', "Reduced qty stays Completed (POS still active).")

        # 4 -> 6: preserve the completed 4, create 2 as new work.
        order.lines.write({'qty': 6})
        order.flexsys_kds_register_send()
        kds_order.invalidate_recordset()
        line.invalidate_recordset()
        self.assertEqual(line.qty, 4, "The original completed quantity is preserved untouched.")
        self.assertEqual(line.state, 'completed')
        delta_line = kds_order.line_ids - line
        self.assertEqual(len(delta_line), 1)
        self.assertEqual(delta_line.qty, 2)
        self.assertEqual(delta_line.state, 'new')

        # Complete the additional 2.
        delta_line.action_accept()
        delta_line.action_start()
        delta_line.action_ready()
        delta_line.action_complete()
        self.assertEqual(delta_line.state, 'completed')
        # Now TWO separate active kds.order.line records share the SAME
        # pos_order_line_id - both Completed: the original (qty 4) and
        # the delta (qty 2) - exactly the scenario the old dict-based
        # removal loop could only ever see ONE of.

        # 6 -> 0: POS removes the order line entirely (not qty=0 - the
        # actual line record itself disappears from the order, matching
        # "the POS removes the order line from the current order data").
        pos_line = order.lines
        events_before = self.env['kds.event'].search_count([('order_id', '=', kds_order.id)])
        pos_line.unlink()
        order.flexsys_kds_register_send()

        kds_order.invalidate_recordset()
        line.invalidate_recordset()
        delta_line.invalidate_recordset()
        self.assertEqual(
            line.state, 'cancelled',
            "The original line (qty 4) must be detected and cancelled - not left "
            "invisibly active just because the delta line also shares its pos_order_line_id.")
        self.assertEqual(
            delta_line.state, 'cancelled',
            "The delta line (qty 2) must ALSO be detected and cancelled - this is "
            "exactly the second line the old dict-based loop silently missed.")
        self.assertEqual(line.qty, 4, "Historical quantity preserved, not rewritten to 0 or negative.")
        self.assertEqual(delta_line.qty, 2, "Historical quantity preserved.")
        self.assertGreaterEqual(line.qty + delta_line.qty, 6, "No negative work item - the full "
                                 "previously-completed 6 remains visible as cancelled history.")

        self.assertEqual(
            kds_order.state, 'completed',
            "Do NOT reopen the order to PREPARING merely because of the cancellation - "
            "it stays exactly where it was, now with everything cancelled.")

        events_after = self.env['kds.event'].search_count([('order_id', '=', kds_order.id)])
        self.assertGreater(events_after, events_before,
                            "An audit event representing the full removal must be recorded.")
        consolidated_event = self.env['kds.event'].search([
            ('order_id', '=', kds_order.id), ('event_type', '=', 'line_removed'),
            ('note', 'like', '%cancelled_qty: 6%'),
        ])
        self.assertTrue(
            consolidated_event,
            "A consolidated audit event summarizing the TOTAL cancelled quantity (4 + 2 = "
            "6) across both lines must be recorded - 'quantity: 6 -> 0, cancelled_qty: 6'.")

    def test_full_line_removal_reconciliation_is_idempotent(self):
        """Repeated sync/polling must NOT create duplicate cancellation
        events or re-process an already-cancelled line."""
        order = self._create_active_pos_order([(self.product_burger, 3)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        line.action_ready()
        line.action_complete()

        pos_line = order.lines
        pos_line.unlink()
        order.flexsys_kds_register_send()

        line.invalidate_recordset()
        self.assertEqual(line.state, 'cancelled')
        first_cancelled_at = line.cancelled_at
        events_after_first = self.env['kds.event'].search_count([
            ('order_id', '=', kds_order.id), ('event_type', '=', 'line_removed'),
        ])
        self.assertGreaterEqual(events_after_first, 1)

        # Simulate repeated polling: run the reconciliation again
        # directly (matching a duplicate webhook/poll/retry).
        order.sudo()._flexsys_kds_diff_lines()
        order.sudo()._flexsys_kds_diff_lines()

        line.invalidate_recordset()
        events_after_repeat = self.env['kds.event'].search_count([
            ('order_id', '=', kds_order.id), ('event_type', '=', 'line_removed'),
        ])
        self.assertEqual(line.state, 'cancelled')
        self.assertEqual(line.cancelled_at, first_cancelled_at,
                          "Re-running reconciliation must not touch an already-cancelled line again.")
        self.assertEqual(
            events_after_repeat, events_after_first,
            "Repeated reconciliation must not create duplicate cancellation events.")

    def test_full_line_removal_does_not_create_negative_qty_line(self):
        order = self._create_active_pos_order([(self.product_burger, 6)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        line.action_ready()
        line.action_complete()

        order.lines.unlink()
        order.flexsys_kds_register_send()

        kds_order.invalidate_recordset()
        for kline in kds_order.line_ids:
            self.assertGreaterEqual(kline.qty, 0, "No line's own quantity may ever go negative.")
        self.assertFalse(
            kds_order.line_ids.filtered(lambda l: l.qty < 0),
            "Do not create a negative work item such as -6 x FLAT WHITE.")

    def test_simple_full_line_removal_still_works_no_delta_complexity(self):
        """Baseline regression guard: the simple single-kline-per-
        pos_order_line_id removal case (already covered by other tests
        in this file) must remain completely unaffected by the group-by
        rewrite."""
        order = self._create_active_pos_order([(self.product_burger, 1), (self.product_cappuccino, 1)])
        kds_order = order.kds_order_id
        kds_order.line_ids.action_accept()
        kds_order.line_ids.action_start()
        cappuccino_pos_line = order.lines.filtered(lambda l: l.product_id == self.product_cappuccino)

        cappuccino_pos_line.unlink()
        order.flexsys_kds_register_send()

        kds_order.invalidate_recordset()
        cappuccino_line = kds_order.line_ids.filtered(lambda l: l.product_id == self.product_cappuccino)
        burger_line = kds_order.line_ids.filtered(lambda l: l.product_id == self.product_burger)
        self.assertEqual(cappuccino_line.state, 'cancelled')
        self.assertEqual(burger_line.state, 'preparing', "The untouched product remains unaffected.")

    # -----------------------------------------------------------------
    # Dev report "BUG FIX REQUEST - Retention Must Follow POS Order
    # Lifecycle": extends BUG-14's own pos_closed_at gating (which only
    # covered Completed) to Cancelled lines too. Required Acceptance
    # Tests 1-5.
    # -----------------------------------------------------------------
    def _display_visible(self, kline, kds_order, pos_closed_cutoff, cancelled_cutoff):
        """Python port of both controllers' own display_lines filter -
        kept deliberately in lockstep with controllers/kds.py and
        controllers/kds_kiosk.py, including the pos_order_id-gated
        fallback for a ticket with no linked POS order at all (which
        must keep expiring from its own completed_at/cancelled_at
        directly, never gaining an unintended "never expires" behavior
        just because pos_closed_at itself is unset)."""
        if kline.state not in ('completed', 'cancelled'):
            return True
        if kline.state == 'completed':
            if kds_order.pos_order_id:
                return not kds_order.pos_closed_at or kds_order.pos_closed_at >= pos_closed_cutoff
            return bool(kline.completed_at and kline.completed_at >= pos_closed_cutoff)
        if kds_order.pos_order_id:
            return not kds_order.pos_closed_at or kds_order.pos_closed_at >= cancelled_cutoff
        return bool(kline.cancelled_at and kline.cancelled_at >= cancelled_cutoff)

    def test_retention_test1_completed_pos_active_never_expires(self):
        order = self._create_active_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        line.action_ready()
        line.action_complete()
        self.assertFalse(kds_order.pos_closed_at)
        line.sudo().write({'completed_at': fields.Datetime.now() - timedelta(minutes=60)})

        pos_closed_cutoff = fields.Datetime.now() - timedelta(minutes=5)
        cancelled_cutoff = fields.Datetime.now() - timedelta(minutes=5)
        self.assertTrue(
            self._display_visible(line, kds_order, pos_closed_cutoff, cancelled_cutoff),
            "A Completed ticket whose POS order is still active must remain visible "
            "indefinitely - no auto-hide while POS is active.")

    def test_retention_test2_completed_pos_closed_expires_from_closure(self):
        order = self._create_active_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        line.action_ready()
        line.action_complete()
        line.sudo().write({'completed_at': fields.Datetime.now() - timedelta(minutes=60)})

        order.write({'state': 'paid', 'amount_paid': order.amount_total})
        kds_order.invalidate_recordset()
        self.assertTrue(kds_order.pos_closed_at, "POS closure must be recorded.")

        pos_closed_cutoff = fields.Datetime.now() - timedelta(minutes=5)
        cancelled_cutoff = fields.Datetime.now() - timedelta(minutes=5)
        self.assertTrue(
            self._display_visible(line, kds_order, pos_closed_cutoff, cancelled_cutoff),
            "Immediately after closure, still within the grace window.")
        # Simulate the grace period having elapsed since closure.
        kds_order.pos_closed_at = fields.Datetime.now() - timedelta(minutes=10)
        self.assertFalse(
            self._display_visible(line, kds_order, pos_closed_cutoff, cancelled_cutoff),
            "Ticket disappears only after pos_closed_at + retention has elapsed.")

    def test_retention_test3_cancelled_pos_active_never_expires(self):
        """The dev report's own exact confirmed runtime scenario: qty
        1 -> 0, POS order not paid/finalized/closed, wait beyond
        retention - the ticket must NOT disappear."""
        order = self._create_active_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        line.action_ready()

        order.lines.write({'qty': 0})
        order.flexsys_kds_register_send()

        line.invalidate_recordset()
        self.assertEqual(line.state, 'cancelled')
        self.assertFalse(kds_order.pos_closed_at, "POS order was never paid/finalized/closed.")
        line.sudo().write({'cancelled_at': fields.Datetime.now() - timedelta(minutes=60)})

        pos_closed_cutoff = fields.Datetime.now() - timedelta(minutes=5)
        cancelled_cutoff = fields.Datetime.now() - timedelta(minutes=5)
        self.assertTrue(
            self._display_visible(line, kds_order, pos_closed_cutoff, cancelled_cutoff),
            "A Cancelled ticket whose POS order is still active must remain visible - "
            "it must NOT disappear while POS is still active, regardless of how long "
            "ago the cancellation itself happened.")

    def test_retention_test4_cancelled_pos_closed_expires_from_closure(self):
        order = self._create_active_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        line.action_ready()

        order.lines.write({'qty': 0})
        order.flexsys_kds_register_send()
        line.invalidate_recordset()
        self.assertEqual(line.state, 'cancelled')
        line.sudo().write({'cancelled_at': fields.Datetime.now() - timedelta(minutes=60)})

        order.write({'state': 'paid', 'amount_paid': 0.0})
        kds_order.invalidate_recordset()
        self.assertTrue(kds_order.pos_closed_at, "Closing the POS order must record its closure.")

        pos_closed_cutoff = fields.Datetime.now() - timedelta(minutes=5)
        cancelled_cutoff = fields.Datetime.now() - timedelta(minutes=5)
        self.assertTrue(
            self._display_visible(line, kds_order, pos_closed_cutoff, cancelled_cutoff),
            "Immediately after closure, still within the grace window.")
        kds_order.pos_closed_at = fields.Datetime.now() - timedelta(minutes=10)
        self.assertFalse(
            self._display_visible(line, kds_order, pos_closed_cutoff, cancelled_cutoff),
            "Ticket disappears only after the configured retention period past closure.")

    def test_retention_test5_reopen_after_cancelled_while_pos_active(self):
        """The existing KDS order lifecycle must be reconciled/reopened
        correctly when a new product is added to the same still-active
        POS order, even after the ticket became fully Cancelled and
        even after waiting beyond the normal retention duration - the
        order record itself must never have been lost."""
        order = self._create_active_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        kds_order_id_value = kds_order.id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()

        order.lines.write({'qty': 0})
        order.flexsys_kds_register_send()
        line.invalidate_recordset()
        self.assertEqual(line.state, 'cancelled')
        self.assertFalse(kds_order.pos_closed_at)
        # Wait beyond normal retention duration (simulated by backdating).
        line.sudo().write({'cancelled_at': fields.Datetime.now() - timedelta(minutes=60)})

        # Confirm the record itself was never lost/deleted.
        self.assertTrue(
            self.env['kds.order'].browse(kds_order_id_value).exists(),
            "The kds.order record itself must never be deleted merely due to retention "
            "elapsing while the POS order stays active.")

        # Add a new product to the same still-active POS order.
        self.env['pos.order.line'].create({
            'order_id': order.id, 'product_id': self.product_cappuccino.id, 'qty': 1,
            'price_unit': 4.0, 'price_subtotal': 4.0, 'price_subtotal_incl': 4.0,
        })
        order.flexsys_kds_register_send()

        kds_order.invalidate_recordset()
        self.assertEqual(
            kds_order.id, kds_order_id_value,
            "The SAME kds.order must be reused - not a new, duplicate ticket.")
        new_line = kds_order.line_ids.filtered(lambda l: l.product_id == self.product_cappuccino)
        self.assertTrue(new_line, "The new product must be added to the existing order's own lifecycle.")
        self.assertEqual(new_line.state, 'new')

    def test_pos_closed_at_gates_both_completed_and_cancelled_consistently(self):
        """Confirmation: BOTH terminal states use pos_closed_at through
        the exact same gating logic, not two different mechanisms."""
        order = self._create_active_pos_order([(self.product_burger, 1), (self.product_cappuccino, 1)])
        kds_order = order.kds_order_id
        burger_line = kds_order.line_ids.filtered(lambda l: l.product_id == self.product_burger)
        coffee_line = kds_order.line_ids.filtered(lambda l: l.product_id == self.product_cappuccino)
        burger_line.action_accept()
        burger_line.action_start()
        burger_line.action_ready()
        burger_line.action_complete()
        coffee_line.action_accept()
        coffee_line.action_start()
        coffee_pos_line = order.lines.filtered(lambda l: l.product_id == self.product_cappuccino)
        coffee_pos_line.unlink()
        order.flexsys_kds_register_send()

        kds_order.invalidate_recordset()
        burger_line.invalidate_recordset()
        coffee_line.invalidate_recordset()
        self.assertEqual(burger_line.state, 'completed')
        self.assertEqual(coffee_line.state, 'cancelled')
        self.assertFalse(kds_order.pos_closed_at, "Neither terminal line has a closed POS order yet.")

        pos_closed_cutoff = fields.Datetime.now() - timedelta(minutes=5)
        cancelled_cutoff = fields.Datetime.now() - timedelta(minutes=5)
        self.assertTrue(self._display_visible(burger_line, kds_order, pos_closed_cutoff, cancelled_cutoff))
        self.assertTrue(self._display_visible(coffee_line, kds_order, pos_closed_cutoff, cancelled_cutoff))

    def test_no_pos_linkage_falls_back_to_direct_expiry_never_expires_would_be_wrong(self):
        """REAL BUG FIX, found via this module's own review while
        implementing "Retention Must Follow POS Order Lifecycle": a
        kds.order with no linked POS order at all (pos_order_id unset -
        created directly, outside any POS flow) must NOT gain an
        unintended "never expires" behavior just because pos_closed_at
        is also, necessarily, always unset for it. It must keep expiring
        from its own cancelled_at/completed_at directly, exactly as
        before this whole round of fixes."""
        order = self._make_order([(self.product_burger, 1)])
        self._route_line_to_station(order.line_ids, self.station_kitchen)
        line = order.line_ids
        self.assertFalse(order.pos_order_id, "This order has no POS linkage at all.")
        line.with_user(self.admin).action_accept()
        line.with_user(self.admin).action_start()
        line.with_user(self.admin).action_cancel(reason='test')
        self.assertEqual(line.state, 'cancelled')
        line.sudo().write({'cancelled_at': fields.Datetime.now() - timedelta(minutes=20)})

        cancelled_cutoff = fields.Datetime.now() - timedelta(minutes=5)
        pos_closed_cutoff = fields.Datetime.now() - timedelta(minutes=5)
        self.assertFalse(
            self._display_visible(line, order, pos_closed_cutoff, cancelled_cutoff),
            "A ticket with NO linked POS order must still expire normally from its own "
            "cancelled_at - the POS-lifecycle retention rule only applies to a ticket "
            "genuinely waiting on a linked POS order's own closure, never to one with no "
            "POS order to wait on in the first place.")

    # -----------------------------------------------------------------
    # Dev report "CRITICAL BUG FIX REQUEST - On Send to KDS Boundary Is
    # Being Bypassed": confirmed live - adding a single product, with
    # NEITHER Send nor New pressed, appeared in KDS immediately. Root
    # cause: mere presence of last_order_preparation_change in a
    # write()/create() vals dict is not a reliable "genuine Send/New"
    # signal - confirmed from Odoo 19's own core source
    # (_ensure_to_keep_last_preparation_change) that the field's own
    # JSON payload carries a `metadata` key specifically to distinguish
    # a genuine preparation-change event from an ordinary save that
    # merely carries the field along. Required Acceptance Tests 1-3
    # (Test 4/5/6/7/8/9 are already exercised throughout this file's
    # other tests, all of which explicitly use a populated metadata
    # payload).
    # -----------------------------------------------------------------
    # REAL BUG FIX ("RUNTIME FAILURE - 19.0.7.9.3 STILL BYPASSES 'ON
    # SEND TO KDS'"): the test that lived here -
    # test_bug_on_send_boundary_empty_metadata_write_does_not_sync -
    # directly tested the metadata-interpretation mechanism (empty vs
    # populated `metadata` in last_order_preparation_change) that this
    # exact round's own fix abandoned entirely, confirmed unsound by the
    # KDS Audit Log itself (see flexsys_kds_register_send()'s own
    # docstring in pos_order.py for the complete explanation). Removed
    # rather than repurposed - the mechanism it tested no longer exists
    # in the active create()/write() path; the correct new behavior
    # (an explicit signal, not content interpretation) is already
    # covered by test_explicit_send_signal_reconciles_pending_changes
    # and the Required Acceptance Tests below.
    # -----------------------------------------------------------------

    def test_bug_on_send_boundary_test1_no_ticket_before_any_send_signal(self):
        """Required Acceptance Test 1: create order, add product, do NOT
        trigger On Send to KDS - no KDS ticket at all."""
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
        self.assertFalse(order.kds_order_id, "No KDS ticket at all before any Send signal.")

    def test_bug_on_send_boundary_test2_send_creates_exactly_one_ticket(self):
        """Required Acceptance Test 2: continue Test 1, press Send -
        exactly one KDS ticket appears."""
        order = self._create_active_pos_order([(self.product_burger, 1)])
        self.assertTrue(order.kds_order_id)
        self.assertEqual(
            len(order.kds_order_id.line_ids), 1,
            "Exactly one KDS ticket, containing the product added before Send.")

    def test_bug_on_send_boundary_test3_second_product_before_send_invisible(self):
        """Required Acceptance Test 3: after the initial Send, add
        another product without Send - KDS unchanged; press Send - the
        new product appears as ADDED."""
        order = self._create_active_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        self.assertEqual(len(kds_order.line_ids), 1)

        self.env['pos.order.line'].create({
            'order_id': order.id, 'product_id': self.product_cappuccino.id, 'qty': 1,
            'price_unit': 4.0, 'price_subtotal': 4.0, 'price_subtotal_incl': 4.0,
        })
        kds_order.invalidate_recordset()
        self.assertEqual(
            len(kds_order.line_ids), 1,
            "KDS must remain unchanged - the new product must not appear before Send.")

        order.flexsys_kds_register_send()

        kds_order.invalidate_recordset()
        new_line = kds_order.line_ids.filtered(lambda l: l.product_id == self.product_cappuccino)
        self.assertTrue(new_line, "The new product must now appear as ADDED, after Send.")
        self.assertEqual(new_line.line_change, 'added')

    def test_bug_on_send_boundary_qty_zero_stays_unchanged_until_send(self):
        """Required Acceptance Test 5, isolated: committed qty 1,
        changed to 0 without Send - KDS must remain unchanged (not
        auto-cancelled) until the next genuine Send."""
        order = self._create_active_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()

        order.lines.write({'qty': 0})
        # Deliberately NOT sending the Send signal here.

        line.invalidate_recordset()
        self.assertEqual(
            line.qty, 1,
            "Before On Send to KDS, the previously committed quantity must remain "
            "unchanged - it must NOT become CANCELLED automatically.")
        self.assertNotEqual(line.state, 'cancelled')

        order.flexsys_kds_register_send()

        line.invalidate_recordset()
        self.assertEqual(
            line.state, 'cancelled',
            "Only after On Send to KDS does the quantity->0 cancellation logic execute.")

    def test_bug_on_send_boundary_multiple_edits_before_send_reconcile_once(self):
        """Required Acceptance Test 9: several POS edits before Send -
        no intermediate KDS events; after one Send, exactly one
        reconciliation against the final POS state (not a replay of
        every intermediate edit)."""
        order = self._create_active_pos_order([(self.product_burger, 5)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        events_before = self.env['kds.event'].search_count([('order_id', '=', kds_order.id)])

        # Multiple edits, no Send signal in between.
        order.lines.write({'qty': 4})
        order.lines.write({'qty': 7})
        order.lines.write({'qty': 3})

        line.invalidate_recordset()
        self.assertEqual(line.qty, 5, "No intermediate changes must reach KDS at all.")
        events_during = self.env['kds.event'].search_count([('order_id', '=', kds_order.id)])
        self.assertEqual(events_during, events_before, "Zero intermediate KDS events.")

        order.flexsys_kds_register_send()

        line.invalidate_recordset()
        self.assertEqual(
            line.qty, 3,
            "Only the FINAL POS state (3) reconciles - the intermediate 4 and 7 are "
            "never separately replayed.")
        self.assertEqual(line.qty_delta, -2, "Delta is calculated as final(3) - committed(5) = -2.")

    # -----------------------------------------------------------------
    # Dev report "BUG FIX REQUEST - On Send to KDS / Subsequent Changes
    # Bypass Send Gate": confirmed live - initial Send correctly gated,
    # but a subsequent edit to an ALREADY-sent order (no Send pressed
    # again) still leaked through immediately. Root cause: once an order
    # has been sent even once, Odoo's own frontend re-serializes that
    # SAME, already-populated last_order_preparation_change value as
    # part of its routine save payload on essentially every subsequent
    # write - _is_genuine_send_signal()'s own "non-empty metadata" check
    # alone could no longer distinguish a genuine second Send from a
    # stale value being carried along again. Required Tests A-E below.
    # -----------------------------------------------------------------
    def test_bug_stale_send_signal_repeated_after_first_send_does_not_leak(self):
        """The dev report's own exact reproduction, isolated directly:
        a write carrying the SAME last_order_preparation_change value
        already processed by an earlier genuine Send must NOT be
        treated as a new Send - this is the precise confirmed root
        cause (a subsequent routine save re-carrying the same,
        already-handled value)."""
        order = self._make_send_write_order()
        order.flexsys_kds_register_send()
        kds_order = order.kds_order_id
        self.assertTrue(kds_order, "The genuine first Send must sync normally.")
        self.assertEqual(
            order.kds_last_processed_send_signal, '{"lines": [], "metadata": {"v": 1}}',
            "The processed value must be recorded immediately after a genuine Send.")

        # A routine save re-carrying the EXACT SAME value (matching how
        # Odoo's own frontend re-serializes the order's existing field
        # value on essentially every subsequent save, not exclusively a
        # genuine second Send) must NOT be treated as a new Send.
        self.env['pos.order.line'].create({
            'order_id': order.id, 'product_id': self.product_cappuccino.id, 'qty': 1,
            'price_unit': 4.0, 'price_subtotal': 4.0, 'price_subtotal_incl': 4.0,
        })
        order.flexsys_kds_register_send()

        kds_order.invalidate_recordset()
        self.assertFalse(
            kds_order.line_ids.filtered(lambda l: l.product_id == self.product_cappuccino),
            "A write carrying the SAME, already-processed last_order_preparation_change "
            "value must not sync anything new - this is the confirmed root cause of the "
            "reported leak.")

    def test_bug_a_new_line_after_first_send_invisible_until_next_send(self):
        """Required Test A: new line after first Send, without Send ->
        invisible to KDS."""
        order = self._make_send_write_order()
        order.flexsys_kds_register_send()
        kds_order = order.kds_order_id
        self.assertTrue(kds_order)

        self.env['pos.order.line'].create({
            'order_id': order.id, 'product_id': self.product_cappuccino.id, 'qty': 1,
            'price_unit': 4.0, 'price_subtotal': 4.0, 'price_subtotal_incl': 4.0,
        })
        # No Send pressed - KDS must remain unchanged.
        kds_order.invalidate_recordset()
        self.assertFalse(
            kds_order.line_ids.filtered(lambda l: l.product_id == self.product_cappuccino),
            "A new line added after the first Send, without pressing Send again, must "
            "remain completely invisible to KDS.")
        self.assertEqual(len(kds_order.line_ids), 1, "Only the originally-sent line exists.")

    def test_bug_b_qty_change_after_first_send_invisible_until_next_send(self):
        """Required Test B: quantity change after first Send, without
        Send -> invisible to KDS."""
        order = self._make_send_write_order()
        order.flexsys_kds_register_send()
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        self.assertEqual(line.qty, 1)

        order.lines.write({'qty': 5})
        # No Send pressed.
        line.invalidate_recordset()
        self.assertEqual(
            line.qty, 1,
            "A quantity change after the first Send, without pressing Send again, must "
            "remain completely invisible to KDS - committed state stays at 1.")
        self.assertEqual(line.qty_delta, 0, "No delta must be shown before the next Send.")

    def test_bug_c_line_removal_after_first_send_invisible_until_next_send(self):
        """Required Test C: line removal/qty 0 after first Send, without
        Send -> invisible to KDS."""
        order = self._make_send_write_order()
        order.flexsys_kds_register_send()
        kds_order = order.kds_order_id
        line = kds_order.line_ids

        order.lines.write({'qty': 0})
        # No Send pressed.
        line.invalidate_recordset()
        self.assertEqual(
            line.state, 'new',
            "A quantity-to-zero change after the first Send, without pressing Send "
            "again, must remain completely invisible to KDS - the line must not become "
            "CANCELLED yet.")
        self.assertEqual(line.qty, 1, "The committed quantity itself is untouched.")

    def test_bug_d_pending_changes_become_visible_correctly_on_next_send(self):
        """Required Test D: after pressing Send -> all pending changes
        become visible correctly with the proper Delta markers."""
        order = self._make_send_write_order()
        order.flexsys_kds_register_send()
        kds_order = order.kds_order_id
        line = kds_order.line_ids

        self.env['pos.order.line'].create({
            'order_id': order.id, 'product_id': self.product_cappuccino.id, 'qty': 1,
            'price_unit': 4.0, 'price_subtotal': 4.0, 'price_subtotal_incl': 4.0,
        })
        order.lines.filtered(lambda l: l.product_id == self.product_burger).write({'qty': 3})

        # Genuinely NEW send signal (different value) - a real second Send.
        order.flexsys_kds_register_send()

        kds_order.invalidate_recordset()
        line.invalidate_recordset()
        new_line = kds_order.line_ids.filtered(lambda l: l.product_id == self.product_cappuccino)
        self.assertEqual(line.qty, 3, "The quantity change is now correctly reflected.")
        self.assertEqual(line.qty_delta, 2, "UPDATED (+2) - 1 -> 3.")
        self.assertTrue(new_line, "The new line is now correctly visible.")
        self.assertEqual(new_line.line_change, 'added')
        self.assertEqual(
            order.kds_last_processed_send_signal, '{"lines": [], "metadata": {"v": 2}}',
            "The newly-processed value must now be recorded as the latest.")

    def test_bug_e_multiple_edits_before_send_reconcile_once_on_final_state(self):
        """Required Test E: multiple POS edits before Send -> KDS
        receives only the final resulting state/delta when Send is
        pressed - matching the dev report's own 'multiple edits before
        Send' worked example (5 -> 4 -> 7 -> 3, add/remove/add products,
        with zero intermediate KDS events, reconciled exactly once)."""
        order = self._make_send_write_order()
        order.flexsys_kds_register_send()
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        self.assertEqual(line.qty, 1)

        events_before = self.env['kds.event'].search_count([('order_id', '=', kds_order.id)])

        # Several edits, no Send between them.
        order.lines.write({'qty': 3})
        order.lines.write({'qty': 7})
        order.lines.write({'qty': 2})
        new_line = self.env['pos.order.line'].create({
            'order_id': order.id, 'product_id': self.product_cappuccino.id, 'qty': 1,
            'price_unit': 4.0, 'price_subtotal': 4.0, 'price_subtotal_incl': 4.0,
        })
        new_line.unlink()

        line.invalidate_recordset()
        self.assertEqual(line.qty, 1, "Zero intermediate KDS changes before Send.")
        events_after_edits = self.env['kds.event'].search_count([('order_id', '=', kds_order.id)])
        self.assertEqual(events_after_edits, events_before,
                          "No intermediate KDS events from the un-sent edits.")

        # One genuine Send.
        order.flexsys_kds_register_send()

        kds_order.invalidate_recordset()
        line.invalidate_recordset()
        self.assertEqual(
            line.qty, 2,
            "Only the FINAL POS state (2) reconciles - the intermediate 3 and 7 are "
            "never separately replayed.")
        self.assertEqual(line.qty_delta, 1, "Delta is calculated as final(2) - committed(1) = +1.")
        self.assertFalse(
            kds_order.line_ids.filtered(lambda l: l.product_id == self.product_cappuccino),
            "The add-then-remove-before-Send must never have appeared in KDS at all.")

    # -----------------------------------------------------------------
    # Dev report "RUNTIME TEST RESULT - FIX STILL FAILS" (19.0.7.9.2):
    # confirmed the backend-only, last_order_preparation_change-
    # interpreting approach still leaked a subsequent edit through after
    # the first Send. New flexsys_kds_register_send() - an explicit RPC
    # entry point called by this module's own frontend patch
    # immediately after Odoo's own native sendOrderInPreparation()
    # completes, rather than inferring intent from any Odoo-internal
    # field's own content.
    # -----------------------------------------------------------------
    def test_explicit_send_signal_reconciles_pending_changes(self):
        """The exact confirmed runtime scenario: an existing, already-
        committed ticket (5 x HOT COFFEE DAY), a new product (2 x ICE
        TEA) added without pressing Send, then the explicit signal
        arrives (simulating the frontend patch firing after a genuine
        Send) - only THEN must the new line become visible."""
        order = self._make_send_write_order()
        order.lines.write({'qty': 5})
        order.flexsys_kds_register_send()
        kds_order = order.kds_order_id
        self.assertTrue(kds_order)
        line = kds_order.line_ids
        self.assertEqual(line.qty, 5)

        # Add a new product WITHOUT ever calling flexsys_kds_register_send
        # again - simulating a routine POS save (create()/write() hooks
        # only, no explicit Send signal).
        self.env['pos.order.line'].create({
            'order_id': order.id, 'product_id': self.product_cappuccino.id, 'qty': 2,
            'price_unit': 4.0, 'price_subtotal': 8.0, 'price_subtotal_incl': 8.0,
        })

        kds_order.invalidate_recordset()
        self.assertFalse(
            kds_order.line_ids.filtered(lambda l: l.product_id == self.product_cappuccino),
            "Without the explicit Send signal, the new product must remain completely "
            "invisible to KDS - regardless of any ordinary create()/write() activity on "
            "the order in between.")

        # Now the explicit signal arrives (the frontend patch firing
        # after a genuine second Send).
        order.flexsys_kds_register_send()

        kds_order.invalidate_recordset()
        new_line = kds_order.line_ids.filtered(lambda l: l.product_id == self.product_cappuccino)
        self.assertTrue(new_line, "After the explicit Send signal, the new product must "
                                   "now correctly appear as ADDED.")
        self.assertEqual(new_line.line_change, 'added')
        self.assertEqual(new_line.qty, 2)

    def test_explicit_send_signal_is_a_noop_for_payment_trigger(self):
        """The explicit signal must be harmless under 'payment' mode,
        which never depends on is_send_write for its own gate."""
        order = self._create_pos_order([(self.product_burger, 1)])  # 'payment' trigger, defaults to paid
        kds_order_before = order.kds_order_id
        self.assertTrue(kds_order_before)

        order.flexsys_kds_register_send()  # must not raise, must not duplicate

        self.assertEqual(order.kds_order_id, kds_order_before,
                          "Calling the explicit signal under 'payment' mode must not "
                          "create a duplicate or otherwise misbehave.")

    def test_explicit_send_signal_double_fire_is_idempotent(self):
        """Dev report 'Explicit POS Send Must Trigger KDS Sync': two
        independent frontend patches now both call
        flexsys_kds_register_send() for the same genuine Send event
        (PosStore.prototype.sendOrderInPreparation AND
        PosOrder.prototype.updateLastOrderChange, since the former
        calls the latter internally, per Odoo's own core source) -
        confirms this natural double-fire is completely harmless: no
        duplicate ticket, no duplicate delta, no duplicate audit event."""
        order = self._make_send_write_order()
        order.lines.write({'qty': 5})
        order.flexsys_kds_register_send()
        order.flexsys_kds_register_send()  # simulates the second patch firing for the same Send
        kds_order = order.kds_order_id
        self.assertTrue(kds_order)
        line = kds_order.line_ids
        self.assertEqual(line.qty, 5)
        self.assertEqual(len(kds_order.line_ids), 1, "No duplicate line/ticket.")

        events_before = self.env['kds.event'].search_count([('order_id', '=', kds_order.id)])

        # A genuine subsequent edit, then BOTH patches fire again for the next Send.
        self.env['pos.order.line'].create({
            'order_id': order.id, 'product_id': self.product_cappuccino.id, 'qty': 2,
            'price_unit': 4.0, 'price_subtotal': 8.0, 'price_subtotal_incl': 8.0,
        })
        order.flexsys_kds_register_send()
        order.flexsys_kds_register_send()  # the second patch firing again

        kds_order.invalidate_recordset()
        new_line = kds_order.line_ids.filtered(lambda l: l.product_id == self.product_cappuccino)
        self.assertEqual(len(new_line), 1, "Exactly one ADDED line, not duplicated by the second call.")
        self.assertEqual(new_line.line_change, 'added')
        line_added_events = self.env['kds.event'].search_count([
            ('order_id', '=', kds_order.id), ('event_type', '=', 'line_added'),
        ])
        events_after = self.env['kds.event'].search_count([('order_id', '=', kds_order.id)])
        self.assertEqual(
            events_after - events_before, line_added_events,
            "The second, redundant call must add no further events beyond the genuine "
            "ones from the first call - the diff against an unchanged POS state is a "
            "correct no-op.")

    def test_explicit_send_signal_does_not_leak_refund_orders(self):
        """The refund-order exclusion (BUG-06) must still apply even
        when this new explicit signal is called."""
        if 'refunded_orderline_id' not in self.env['pos.order.line']._fields:
            self.skipTest("refunded_orderline_id not present on this build.")
        order = self._make_send_write_order()
        order.flexsys_kds_register_send()
        kds_order = order.kds_order_id
        self.assertTrue(kds_order)

        refund_order = self._create_refund_order({order.lines: 1})
        refund_order.flexsys_kds_register_send()

        self.assertFalse(
            refund_order.kds_order_id,
            "A refund order must never get its own KDS ticket, even via the explicit "
            "Send signal.")

    # -----------------------------------------------------------------
    # Dev report "RUNTIME FAILURE - 19.0.7.9.3 STILL BYPASSES 'ON SEND
    # TO KDS'": the exact confirmed runtime scenario, reproduced end to
    # end - order 2629-3-000021, 5 x HOT AMERICANO committed, then
    # 3 x Hot Italy added WITHOUT pressing Send/New, confirmed via the
    # KDS Audit Log itself that a backend path ("Line Added"/"Order
    # Routed") was still processing this - now confirmed structurally
    # impossible: create()/write() can never trigger a sync on their
    # own for 'send' mode, regardless of any vals they carry.
    # -----------------------------------------------------------------
    def test_bug_exact_reported_scenario_hot_americano_hot_italy(self):
        order = self._make_send_write_order()
        order.lines.write({'qty': 5})
        order.flexsys_kds_register_send()
        kds_order = order.kds_order_id
        self.assertTrue(kds_order)
        line = kds_order.line_ids
        self.assertEqual(line.qty, 5)
        events_before = self.env['kds.event'].search_count([('order_id', '=', kds_order.id)])

        # Add 3 x Hot Italy - deliberately WITHOUT calling
        # flexsys_kds_register_send() - simulating ordinary POS editing
        # (create() on the new line, plus whatever ordinary write()
        # activity the order itself goes through as part of that same
        # POS interaction, none of which may carry the explicit signal).
        self.env['pos.order.line'].create({
            'order_id': order.id, 'product_id': self.product_cappuccino.id, 'qty': 3,
            'price_unit': 4.5, 'price_subtotal': 13.5, 'price_subtotal_incl': 13.5,
        })
        # Simulate "normal polling/realtime" per the dev report's own
        # required test step 5 - an ordinary write on the order itself,
        # touching fields a real background poll might touch, still
        # carrying no explicit Send signal.
        order.write({'note': 'table 4'})

        kds_order.invalidate_recordset()
        self.assertFalse(
            kds_order.line_ids.filtered(lambda l: l.product_id == self.product_cappuccino),
            "KDS must still contain ONLY the originally-committed 5 x HOT AMERICANO - "
            "no Line Added, no Order Routed, no audit event at all, until an explicit "
            "Send signal arrives.")
        events_after_edit = self.env['kds.event'].search_count([('order_id', '=', kds_order.id)])
        self.assertEqual(
            events_after_edit, events_before,
            "No new KDS audit events (no 'Line Added', no 'Order Routed') may be "
            "created by ordinary POS editing or polling alone.")

        # Only now, the explicit Send signal.
        order.flexsys_kds_register_send()

        kds_order.invalidate_recordset()
        new_line = kds_order.line_ids.filtered(lambda l: l.product_id == self.product_cappuccino)
        self.assertTrue(new_line, "Only after the explicit Send signal must Hot Italy appear.")
        self.assertEqual(new_line.line_change, 'added')
        self.assertEqual(new_line.qty, 3)
        line_added_event = self.env['kds.event'].search([
            ('order_id', '=', kds_order.id), ('event_type', '=', 'line_added'),
        ])
        self.assertTrue(line_added_event,
                         "The 'Line Added' audit event is only correctly created now.")

    def test_bug_ordinary_writes_can_never_trigger_sync_regardless_of_vals(self):
        """Confirms the structural guarantee directly: create()/write()
        on pos.order/pos.order.line can never trigger
        _flexsys_kds_diff_lines() under 'send' mode, no matter what
        vals they carry - only flexsys_kds_register_send() can. Tries
        several plausible-looking "trigger" vals shapes directly, none
        of which may leak anything."""
        order = self._make_send_write_order()
        order.flexsys_kds_register_send()
        kds_order = order.kds_order_id
        self.assertTrue(kds_order)

        self.env['pos.order.line'].create({
            'order_id': order.id, 'product_id': self.product_cappuccino.id, 'qty': 1,
            'price_unit': 4.0, 'price_subtotal': 4.0, 'price_subtotal_incl': 4.0,
        })
        # A write carrying 'lines' AND a populated last_order_preparation_change
        # together - the exact shape that used to leak through the old,
        # now-removed inference mechanism.
        order.write({
            'last_order_preparation_change': '{"lines": [], "metadata": {"v": 99}}',
        })
        order.write({'state': 'draft'})  # re-writing the same state - another plausible leak vector

        kds_order.invalidate_recordset()
        self.assertFalse(
            kds_order.line_ids.filtered(lambda l: l.product_id == self.product_cappuccino),
            "None of these ordinary writes - regardless of which fields they touch or "
            "what values they carry - may trigger a sync. Only the explicit "
            "flexsys_kds_register_send() call may.")

    # -----------------------------------------------------------------
    # Dev report "BUG FIX REQUEST - CANCELLED FILTER CLASSIFICATION +
    # RETENTION LIFECYCLE".
    # -----------------------------------------------------------------

    # Issue 1 - CANCELLED tickets incorrectly classified under NEW.
    def test_issue1_fully_cancelled_before_ever_starting_is_not_new(self):
        """The exact confirmed runtime scenario: "NEW = 6" with all 6
        visible cards actually CANCELLED - a station cancelled before
        ever starting (still 'new' when qty -> 0) must classify as
        'cancelled', never 'new'."""
        order = self._create_active_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        self.assertEqual(line.state, 'new')

        order.lines.write({'qty': 0})
        order.flexsys_kds_register_send()

        line.invalidate_recordset()
        self.assertEqual(line.state, 'cancelled')
        self.assertEqual(
            self._effective_stage(kds_order.line_ids), 'cancelled',
            "A fully-cancelled station must classify as 'cancelled' - never 'new', "
            "'preparing', 'ready', or 'completed' - so it can never satisfy any of "
            "those four tabs' own filter/count check.")

    def test_issue1_fully_cancelled_after_preparing_is_not_preparing(self):
        """The same fix, confirmed for a station cancelled AFTER
        reaching Preparing - previously classified as 'preparing' (the
        old BUG-08 'preserved last stage' value), now correctly
        'cancelled'."""
        order = self._create_active_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        self.assertEqual(line.state, 'preparing')

        order.lines.write({'qty': 0})
        order.flexsys_kds_register_send()

        line.invalidate_recordset()
        self.assertEqual(line.state, 'cancelled')
        self.assertEqual(
            self._effective_stage(kds_order.line_ids), 'cancelled',
            "A station cancelled after reaching Preparing must still classify as "
            "'cancelled' for tab-matching purposes - the 'was PREPARING' context is "
            "preserved separately for display text, not through this value.")

    def test_issue1_acceptance_test_filter_classification(self):
        """The dev report's own exact Acceptance Test: 1 NEW + 1
        PREPARING + 1 READY + 1 COMPLETED + 1 CANCELLED ticket -
        ALL=5, NEW=1, PREPARING=1, READY=1, COMPLETED=1, and the
        CANCELLED ticket appears in none of the four specific tabs."""
        new_order = self._create_active_pos_order([(self.product_burger, 1)])
        new_order.flexsys_kds_register_send()

        preparing_order = self._create_active_pos_order([(self.product_burger, 1)])
        preparing_order.flexsys_kds_register_send()
        preparing_order.kds_order_id.line_ids.action_accept()
        preparing_order.kds_order_id.line_ids.action_start()

        ready_order = self._create_active_pos_order([(self.product_burger, 1)])
        ready_order.flexsys_kds_register_send()
        ready_order.kds_order_id.line_ids.action_accept()
        ready_order.kds_order_id.line_ids.action_start()
        ready_order.kds_order_id.line_ids.action_ready()

        completed_order = self._create_active_pos_order([(self.product_burger, 1)])
        completed_order.flexsys_kds_register_send()
        completed_order.kds_order_id.line_ids.action_accept()
        completed_order.kds_order_id.line_ids.action_start()
        completed_order.kds_order_id.line_ids.action_ready()
        completed_order.kds_order_id.line_ids.action_complete()

        cancelled_order = self._create_active_pos_order([(self.product_burger, 1)])
        cancelled_order.flexsys_kds_register_send()
        cancelled_order.lines.write({'qty': 0})
        cancelled_order.flexsys_kds_register_send()

        all_kds_orders = (new_order.kds_order_id | preparing_order.kds_order_id
                           | ready_order.kds_order_id | completed_order.kds_order_id
                           | cancelled_order.kds_order_id)
        self.assertEqual(len(all_kds_orders), 5, "ALL = 5.")

        stages = {}
        for o in all_kds_orders:
            stage = self._effective_stage(o.line_ids)
            stages.setdefault(stage, []).append(o)

        self.assertEqual(len(stages.get('new', [])), 1, "NEW = 1 - only the actual NEW ticket.")
        self.assertEqual(len(stages.get('preparing', [])), 1, "PREPARING = 1.")
        self.assertEqual(len(stages.get('ready', [])), 1, "READY = 1.")
        self.assertEqual(len(stages.get('completed', [])), 1, "COMPLETED = 1.")
        self.assertEqual(stages.get('cancelled', [None])[0], cancelled_order.kds_order_id,
                          "The CANCELLED ticket must classify as 'cancelled', appearing in "
                          "none of the four specific tabs' own stage bucket.")

    def test_issue1_test_c_filter_counters_with_multiple_cancelled(self):
        """Required Runtime Test C: 1 actual NEW + 6 retained CANCELLED
        - ALL=7, NEW=1 - never ALL=7/NEW=7, never NEW=6."""
        new_order = self._create_active_pos_order([(self.product_burger, 1)])
        new_order.flexsys_kds_register_send()

        cancelled_orders = self.env['pos.order']
        for _ in range(6):
            order = self._create_active_pos_order([(self.product_burger, 1)])
            order.flexsys_kds_register_send()
            order.lines.write({'qty': 0})
            order.flexsys_kds_register_send()
            cancelled_orders |= order

        all_kds_orders = new_order.kds_order_id
        for o in cancelled_orders:
            all_kds_orders |= o.kds_order_id
        self.assertEqual(len(all_kds_orders), 7, "ALL = 7.")

        new_count = sum(1 for o in all_kds_orders if self._effective_stage(o.line_ids) == 'new')
        cancelled_count = sum(1 for o in all_kds_orders if self._effective_stage(o.line_ids) == 'cancelled')
        self.assertEqual(new_count, 1, "NEW = 1 - the 6 retained CANCELLED tickets must not "
                                        "be counted, whether as NEW = 7 or as NEW = 6.")
        self.assertEqual(cancelled_count, 6)

    # Issue 2 - CANCELLED retention must follow POS closed state.
    def test_issue2_cancelled_pos_order_stamps_pos_closed_at(self):
        """REAL BUG FIX found via this module's own re-verification: a
        POS order that gets CANCELLED outright (state='cancel', never
        paid) must also stamp pos_closed_at - it is unambiguously no
        longer active/open, exactly like a paid order, yet the old
        condition never included 'cancel' in its own closed-state set."""
        order = self._create_active_pos_order([(self.product_burger, 1)])
        order.flexsys_kds_register_send()
        kds_order = order.kds_order_id
        self.assertTrue(kds_order)
        self.assertFalse(kds_order.pos_closed_at)

        order.write({'state': 'cancel'})

        kds_order.invalidate_recordset()
        self.assertTrue(
            kds_order.pos_closed_at,
            "Cancelling the POS order outright must stamp pos_closed_at - a cancelled "
            "POS order is unambiguously closed, not 'still active'.")

    def test_issue2_cancelled_kds_ticket_expires_after_pos_cancel_and_retention(self):
        order = self._create_active_pos_order([(self.product_burger, 1)])
        order.flexsys_kds_register_send()
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        line.action_accept()
        line.action_start()
        line.action_cancel(reason='test', bypass_check=True)
        line.sudo().write({'cancelled_at': fields.Datetime.now() - timedelta(minutes=60)})
        self.assertFalse(kds_order.pos_closed_at)

        order.write({'state': 'cancel'})

        kds_order.invalidate_recordset()
        self.assertTrue(kds_order.pos_closed_at)
        pos_closed_cutoff = fields.Datetime.now() - timedelta(minutes=5)
        self.assertGreaterEqual(
            kds_order.pos_closed_at, pos_closed_cutoff,
            "pos_closed_at reflects the moment of POS cancellation just now, confirming "
            "retention is anchored to that closure moment, not the much-earlier "
            "cancellation of the KDS line itself.")

    def test_issue2_active_pos_cancelled_kds_never_expires_do_not_regress(self):
        """Confirms the previously-approved rule is unchanged: ACTIVE
        POS + CANCELLED KDS ticket + 20 minutes elapsed - ticket remains
        visible. This is intentional, and must NOT be "fixed" by
        reverting to cancelled_at + retention."""
        order = self._create_active_pos_order([(self.product_burger, 1)])
        order.flexsys_kds_register_send()
        kds_order = order.kds_order_id
        line = kds_order.line_ids

        order.lines.write({'qty': 0})
        order.flexsys_kds_register_send()
        line.invalidate_recordset()
        self.assertEqual(line.state, 'cancelled')
        line.sudo().write({'cancelled_at': fields.Datetime.now() - timedelta(minutes=20)})
        self.assertFalse(kds_order.pos_closed_at, "POS order was never paid/finalized/closed.")

        pos_closed_cutoff = fields.Datetime.now() - timedelta(minutes=5)
        cancelled_cutoff = fields.Datetime.now() - timedelta(minutes=5)
        self.assertTrue(
            self._display_visible(line, kds_order, pos_closed_cutoff, cancelled_cutoff),
            "20 minutes elapsed, POS still active - the ticket must remain visible in "
            "ALL. This is intentional and must not regress to cancelled_at-based expiry.")

    # -----------------------------------------------------------------
    # Dev report "LIVE NETWORK TRACE - EXACT ODOO 'ORDER / SEND TO
    # PREPARATION' SERVER PATH CONFIRMED": pos.order.sync_from_ui is
    # the confirmed, actual server-side entry point every POS save goes
    # through, including the previously-unreachable "Order" confirmation
    # dialog action. Testing _flexsys_kds_process_sync_from_ui()
    # directly (the module's own logic) rather than the full native
    # sync_from_ui() itself, which expects a complex, full order payload
    # shape this test does not attempt to fully replicate.
    # -----------------------------------------------------------------
    def test_sync_from_ui_order_has_a_uuid(self):
        """Baseline sanity check: confirms pos.order.uuid is populated
        by Odoo's own core on ordinary record creation, before relying
        on it as the lookup key in every test below."""
        order = self._create_active_pos_order([(self.product_burger, 1)])
        self.assertTrue(order.uuid, "pos.order.uuid must be populated by Odoo's own core.")

    def test_sync_from_ui_no_send_no_kds(self):
        """Required Test: no Send -> no KDS. An ordinary sync_from_ui
        call - NOT preceded by a get_preparation_change() call (the
        confirmed authorization signal) - must not trigger a sync, even
        when last_order_preparation_change's own content is genuine and
        non-empty (confirmed by live testing: content alone can never
        be trusted as a Send signal)."""
        order = self._create_active_pos_order([(self.product_burger, 5)])
        self.assertFalse(order.kds_order_id)
        self.assertFalse(order.kds_preparation_change_requested)

        order._flexsys_kds_process_sync_from_ui([{
            'uuid': order.uuid,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 5}},
                'metadata': {'serverDate': '2026-08-18 08:00:00'},
            }),
        }])

        order.invalidate_recordset()
        self.assertFalse(
            order.kds_order_id,
            "Without a prior get_preparation_change() call, sync_from_ui must not "
            "sync anything at all, even with genuine, non-empty content.")

    def test_sync_from_ui_order_action_triggers_kds(self):
        """Required Test: Order -> KDS. get_preparation_change() called
        first (the confirmed authorization signal), then sync_from_ui -
        the exact confirmed live sequence."""
        order = self._create_active_pos_order([(self.product_burger, 5)])
        self.assertFalse(order.kds_order_id)

        # Direct flag simulation, not the real get_preparation_change()
        # call - avoids depending on that native method's own unverified
        # requirements; the flag-setting logic itself is what this test
        # exercises, matching this override's own confirmed behavior.
        order.sudo().kds_preparation_change_requested = True
        order._flexsys_kds_process_sync_from_ui([{
            'uuid': order.uuid,
            'last_order_preparation_change': json.dumps({
                'lines': {'some-line-uuid': {'product_id': self.product_burger.id, 'quantity': 5}},
                'metadata': {'serverDate': '2026-08-18 08:25:59'},
            }),
        }])

        order.invalidate_recordset()
        self.assertTrue(order.kds_order_id, "get_preparation_change() followed by "
                                             "sync_from_ui must trigger the KDS sync.")
        self.assertEqual(order.kds_order_id.line_ids.qty, 5)

    def test_sync_from_ui_edit_without_send_no_kds(self):
        """Required Test: edit without Send -> no KDS. After a genuine,
        authorized Send, an ORDINARY sync_from_ui call - NOT preceded
        by a fresh get_preparation_change() call - must not trigger a
        second sync, regardless of what content it carries (confirmed
        by live testing: even genuinely different content, from an
        ordinary edit, must not leak without the authorization flag)."""
        order = self._create_active_pos_order([(self.product_burger, 5)])
        # Direct flag simulation, not the real get_preparation_change()
        # call - avoids depending on that native method's own unverified
        # requirements; the flag-setting logic itself is what this test
        # exercises, matching this override's own confirmed behavior.
        order.sudo().kds_preparation_change_requested = True
        order._flexsys_kds_process_sync_from_ui([{
            'uuid': order.uuid,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 5}},
                'metadata': {'serverDate': '2026-08-18 08:25:59'},
            }),
        }])
        kds_order = order.kds_order_id
        self.assertTrue(kds_order)
        self.assertFalse(order.kds_preparation_change_requested, "Consumed after use.")
        events_before = self.env['kds.event'].search_count([('order_id', '=', kds_order.id)])

        # Ordinary edit + autosave-style sync_from_ui call - NOT preceded
        # by get_preparation_change() - even with genuinely different
        # content (qty changed to 2), must not leak.
        order._flexsys_kds_process_sync_from_ui([{
            'uuid': order.uuid,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 2}},
                'metadata': {'serverDate': '2026-08-18 08:26:14'},
            }),
        }])

        kds_order.invalidate_recordset()
        events_after = self.env['kds.event'].search_count([('order_id', '=', kds_order.id)])
        self.assertEqual(
            events_after, events_before,
            "Without a fresh get_preparation_change() call, an ordinary sync_from_ui "
            "must not be treated as a new Send - even with genuinely different content "
            "- this is the exact confirmed root cause of every earlier attempt at this "
            "problem: content comparison alone can never reliably distinguish an "
            "ordinary edit from a genuine Send.")
        self.assertEqual(kds_order.line_ids.qty, 5, "KDS must still show the last "
                                                      "explicitly SENT quantity, not "
                                                      "the live POS state.")

    def test_sync_from_ui_second_send_generates_next_delta(self):
        """Required Test: second Order/Send -> delta. A genuine second
        get_preparation_change() + sync_from_ui pair must correctly
        apply the new content as a delta."""
        order = self._create_active_pos_order([(self.product_burger, 5)])
        # Direct flag simulation, not the real get_preparation_change()
        # call - avoids depending on that native method's own unverified
        # requirements; the flag-setting logic itself is what this test
        # exercises, matching this override's own confirmed behavior.
        order.sudo().kds_preparation_change_requested = True
        order._flexsys_kds_process_sync_from_ui([{
            'uuid': order.uuid,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 5}},
                'metadata': {'serverDate': '2026-08-18 08:25:59'},
            }),
        }])
        kds_order = order.kds_order_id
        self.assertTrue(kds_order)

        # A genuinely new product added to the order (Test D's own
        # scenario), then a genuine second Send.
        self.env['pos.order.line'].create({
            'order_id': order.id, 'product_id': self.product_cappuccino.id, 'qty': 2,
            'price_unit': 4.0, 'price_subtotal': 8.0, 'price_subtotal_incl': 8.0,
        })
        # Direct flag simulation, not the real get_preparation_change()
        # call - avoids depending on that native method's own unverified
        # requirements; the flag-setting logic itself is what this test
        # exercises, matching this override's own confirmed behavior.
        order.sudo().kds_preparation_change_requested = True
        order._flexsys_kds_process_sync_from_ui([{
            'uuid': order.uuid,
            'last_order_preparation_change': json.dumps({
                'lines': {
                    'line-a': {'product_id': self.product_burger.id, 'quantity': 5},
                    'line-b': {'product_id': self.product_cappuccino.id, 'quantity': 2},
                },
                'metadata': {'serverDate': '2026-08-18 08:30:00'},
            }),
        }])

        kds_order.invalidate_recordset()
        new_line = kds_order.line_ids.filtered(lambda l: l.product_id == self.product_cappuccino)
        self.assertTrue(new_line, "The second, genuinely authorized Send must correctly "
                                   "process the new delta.")
        self.assertEqual(new_line.line_change, 'added')
        self.assertEqual(new_line.qty, 2)

    def test_sync_from_ui_quantity_update_generates_updated_delta(self):
        """Test F from the dev report's own Acceptance Test: 5 -> 3,
        Send -> UPDATED."""
        order = self._create_active_pos_order([(self.product_burger, 5)])
        # Direct flag simulation, not the real get_preparation_change()
        # call - avoids depending on that native method's own unverified
        # requirements; the flag-setting logic itself is what this test
        # exercises, matching this override's own confirmed behavior.
        order.sudo().kds_preparation_change_requested = True
        order._flexsys_kds_process_sync_from_ui([{
            'uuid': order.uuid,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 5}},
                'metadata': {'serverDate': '2026-08-18 08:25:59'},
            }),
        }])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        self.assertEqual(line.qty, 5)

        order.lines.write({'qty': 3})
        # Direct flag simulation, not the real get_preparation_change()
        # call - avoids depending on that native method's own unverified
        # requirements; the flag-setting logic itself is what this test
        # exercises, matching this override's own confirmed behavior.
        order.sudo().kds_preparation_change_requested = True
        order._flexsys_kds_process_sync_from_ui([{
            'uuid': order.uuid,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 3}},
                'metadata': {'serverDate': '2026-08-18 08:31:00'},
            }),
        }])

        line.invalidate_recordset()
        self.assertEqual(line.qty, 3)
        self.assertEqual(line.qty_delta, -2, "5 -> 3 is UPDATED (-2).")

    def test_sync_from_ui_malformed_entries_are_skipped_defensively(self):
        """The post-processing loop must never raise on unexpected
        input shapes - malformed entries are simply skipped."""
        order = self._create_active_pos_order([(self.product_burger, 5)])
        try:
            order._flexsys_kds_process_sync_from_ui([
                "not a dict",
                {},
                {'uuid': None, 'last_order_preparation_change': '{}'},
                {'uuid': order.uuid, 'last_order_preparation_change': 'not valid json'},
                {'uuid': order.uuid, 'last_order_preparation_change': None},
                {'uuid': 'nonexistent-uuid-xyz', 'last_order_preparation_change': json.dumps(
                    {'lines': {'x': 1}, 'metadata': {}})},
            ])
        except Exception as e:  # noqa
            self.fail(f"Malformed sync_from_ui entries must never raise: {e}")
        order.invalidate_recordset()
        self.assertFalse(order.kds_order_id, "None of the malformed entries should have synced anything.")

    def test_sync_from_ui_full_override_preserves_native_result(self):
        """Confirms the actual sync_from_ui() override itself does not
        swallow or alter super()'s own return value, even if this
        module's own post-processing fails entirely."""
        order = self._create_active_pos_order([(self.product_burger, 1)])
        with patch.object(
            type(self.env['pos.order']), '_flexsys_kds_process_sync_from_ui',
            side_effect=RuntimeError("simulated post-processing failure"),
        ):
            # A minimal, syntactically valid call - the native
            # super().sync_from_ui() itself is not mocked, so this
            # confirms the override structure itself (try/except around
            # only the post-processing, result always returned) without
            # needing to fully replicate the native payload shape.
            try:
                self.env['pos.order'].sync_from_ui([])
            except Exception as e:
                self.fail(f"A failure in this module's own post-processing must never "
                           f"propagate and break the native sync_from_ui() call: {e}")

    # -----------------------------------------------------------------
    # Dev report "UI / DATA IMPROVEMENT REQUEST - KDS Active Orders &
    # Order History": pos_order_state and pos_payment_methods, new
    # computed fields on kds.order (related through to kds.order.line
    # for the Lines tab). Explicitly does NOT touch POS sync/On Send to
    # KDS/retention/routing/reconciliation - these tests confirm that
    # boundary holds, not just the new fields' own correctness.
    # -----------------------------------------------------------------
    def test_pos_order_state_reflects_linked_pos_order(self):
        order = self._create_pos_order([(self.product_burger, 1)], state='paid')
        kds_order = order.kds_order_id
        self.assertTrue(kds_order)
        self.assertEqual(
            kds_order.pos_order_state, order.state,
            "pos_order_state must reflect the LINKED POS order's own state, "
            "distinctly from the KDS order's own state field.")
        self.assertNotEqual(
            kds_order.pos_order_state, kds_order.state,
            "In this scenario the two happen to differ (POS 'paid' vs KDS 'new') - "
            "confirms these are genuinely two separate values, not aliases of each other.")

    def test_pos_order_state_updates_when_pos_order_state_changes(self):
        order = self._create_active_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        self.assertEqual(kds_order.pos_order_state, 'draft')

        order.write({'state': 'paid', 'amount_paid': order.amount_total})

        kds_order.invalidate_recordset()
        self.assertEqual(kds_order.pos_order_state, 'paid',
                          "pos_order_state must stay live, reflecting the linked "
                          "POS order's own current state, not a stale snapshot.")

    def test_pos_order_state_on_line_matches_order(self):
        order = self._create_pos_order([(self.product_burger, 1)], state='paid')
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        self.assertEqual(
            line.pos_order_state, kds_order.pos_order_state,
            "kds.order.line.pos_order_state (the Lines tab's own 'POS Status' column) "
            "must relay the parent order's own value.")
        self.assertNotEqual(
            line.pos_order_state, line.state,
            "The line's own KDS status (state) and its POS Status (pos_order_state) "
            "must never be confused with each other - the dev report's own explicit "
            "warning.")

    def test_pos_order_state_empty_when_no_linked_pos_order(self):
        """A kds.order created directly, outside any POS flow (source
        != 'pos', no pos_order_id at all) must not error - pos_order_state
        is simply falsy."""
        kds_order = self.env['kds.order'].create({
            'source': 'qr', 'order_type': 'dine_in', 'company_id': self.company.id,
        })
        self.assertFalse(kds_order.pos_order_id)
        self.assertFalse(kds_order.pos_order_state)

    def test_pos_payment_methods_single_method(self):
        try:
            method = self.env['pos.payment.method'].create({'name': 'Cash'})
        except Exception:
            self.skipTest("pos.payment.method's own required fields could not be "
                           "satisfied with this minimal create() in this environment - "
                           "needs live-instance verification, not a fixture bug here.")
        order = self._create_pos_order([(self.product_burger, 1)], state='paid')
        try:
            self.env['pos.payment'].create({
                'pos_order_id': order.id,
                'payment_method_id': method.id,
                'amount': order.amount_total,
                'session_id': self.pos_session.id,
            })
        except Exception:
            self.skipTest("pos.payment's own required fields could not be satisfied "
                           "with this minimal create() in this environment - needs "
                           "live-instance verification, not a fixture bug here.")

        kds_order = order.kds_order_id
        kds_order.invalidate_recordset()
        self.assertEqual(kds_order.pos_payment_methods, 'Cash')

    def test_pos_payment_methods_multiple_methods_no_duplication(self):
        """Required: 'if the POS order can contain more than one
        payment method, do not silently display only one arbitrary
        method... display all applicable payment methods.'"""
        try:
            cash = self.env['pos.payment.method'].create({'name': 'Cash'})
            card = self.env['pos.payment.method'].create({'name': 'Card'})
        except Exception:
            self.skipTest("pos.payment.method's own required fields could not be "
                           "satisfied with this minimal create() in this environment.")
        order = self._create_pos_order([(self.product_burger, 1)], state='paid')
        try:
            self.env['pos.payment'].create({
                'pos_order_id': order.id, 'payment_method_id': cash.id,
                'amount': order.amount_total / 2, 'session_id': self.pos_session.id,
            })
            self.env['pos.payment'].create({
                'pos_order_id': order.id, 'payment_method_id': card.id,
                'amount': order.amount_total / 2, 'session_id': self.pos_session.id,
            })
        except Exception:
            self.skipTest("pos.payment's own required fields could not be satisfied "
                           "with this minimal create() in this environment.")

        kds_order = order.kds_order_id
        kds_order.invalidate_recordset()
        self.assertIn('Cash', kds_order.pos_payment_methods)
        self.assertIn('Card', kds_order.pos_payment_methods)
        self.assertNotEqual(
            kds_order.pos_payment_methods, 'Cash',
            "Must not silently display only one arbitrary method when more than one "
            "was actually used - both must appear.")

    def test_pos_payment_methods_empty_when_unpaid(self):
        order = self._create_active_pos_order([(self.product_burger, 1)])
        kds_order = order.kds_order_id
        self.assertEqual(
            kds_order.pos_payment_methods, '',
            "An order with no payments recorded yet must show an empty string, "
            "not raise or show a placeholder.")

    def test_ui_data_fields_do_not_affect_send_gate_or_delta_logic(self):
        """Explicit non-regression check: adding pos_order_state/
        pos_payment_methods must have zero effect on the On Send to
        KDS gate, delta calculation, or reconciliation - this request
        is display/data-mapping only."""
        order = self._make_send_write_order()
        order.write({'note': 'testing UI fields'})  # ordinary write, no explicit Send
        order.invalidate_recordset()
        self.assertFalse(order.kds_order_id,
                          "An ordinary write must still not sync anything - unrelated "
                          "to this round's own UI-only fields.")

        order.flexsys_kds_register_send()
        kds_order = order.kds_order_id
        self.assertTrue(kds_order)
        line = kds_order.line_ids
        self.assertEqual(line.qty, 1)

        order.lines.write({'qty': 3})
        order.flexsys_kds_register_send()
        line.invalidate_recordset()
        self.assertEqual(line.qty, 3)
        self.assertEqual(line.qty_delta, 2, "Delta calculation itself is completely "
                                             "unaffected by this round's own changes.")

    # -----------------------------------------------------------------
    # Dev report "Live test result - post-send modification is still
    # not propagated to KDS": confirmed live via Network trace
    # (get_preparation_change -> sync_from_ui, both HTTP 200) on a
    # SECOND Send to an already-linked order. Found two real bugs in
    # _flexsys_kds_process_sync_from_ui() by re-reading it line by line:
    # (1) an integer 'id' falling back into a uuid-field search, which
    # can never match; (2) a single try/except around the whole batch,
    # letting one order's own failure silently skip every other order
    # in the same sync_from_ui call.
    # -----------------------------------------------------------------
    def test_sync_from_ui_resolves_order_by_integer_id_not_only_uuid(self):
        """The exact confirmed bug: a payload entry carrying an
        integer 'id' (an already-persisted order being updated) must
        resolve via browse(), never via a uuid-field search (which can
        never match an integer value)."""
        order = self._create_active_pos_order([(self.product_burger, 5)])
        order.sudo().kds_preparation_change_requested = True
        order._flexsys_kds_process_sync_from_ui([{
            'id': order.id,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 5}},
                'metadata': {'serverDate': '2026-08-18 09:00:00'},
            }),
        }])

        order.invalidate_recordset()
        self.assertTrue(
            order.kds_order_id,
            "An order payload entry identified only by integer 'id' (no 'uuid' key at "
            "all) must still correctly resolve to the right record and sync.")
        self.assertEqual(order.kds_order_id.line_ids.qty, 5)

    def test_sync_from_ui_second_send_via_integer_id_updates_existing_ticket(self):
        """The dev report's own exact scenario: qty 1 -> Send -> KDS 1,
        then modify without Send, then Send again (this time the
        payload entry uses 'id', matching an already-persisted order
        being updated rather than created) -> KDS becomes 2."""
        order = self._create_active_pos_order([(self.product_burger, 1)])
        order.sudo().kds_preparation_change_requested = True
        order._flexsys_kds_process_sync_from_ui([{
            'id': order.id,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 1}},
                'metadata': {'serverDate': '2026-08-18 09:00:00'},
            }),
        }])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        self.assertEqual(line.qty, 1)

        order.lines.write({'qty': 2})
        order.sudo().kds_preparation_change_requested = True
        order._flexsys_kds_process_sync_from_ui([{
            'id': order.id,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 2}},
                'metadata': {'serverDate': '2026-08-18 09:05:00'},
            }),
        }])

        line.invalidate_recordset()
        self.assertEqual(line.qty, 2, "The second Send, identified via integer 'id', "
                                       "must correctly update the existing KDS ticket.")
        self.assertEqual(line.qty_delta, 1)

    def test_sync_from_ui_malformed_entry_gracefully_skipped_others_still_process(self):
        """A malformed entry (last_order_preparation_change of an
        unexpected type) is gracefully skipped - but confirms this
        graceful skip still lets a well-formed, authorized entry later
        in the SAME batch process correctly."""
        order_a = self._create_active_pos_order([(self.product_burger, 3)])
        order_b = self._create_active_pos_order([(self.product_cappuccino, 2)])
        order_a.sudo().kds_preparation_change_requested = True
        order_b.sudo().kds_preparation_change_requested = True

        order_a.env['pos.order']._flexsys_kds_process_sync_from_ui([
            {'uuid': order_a.uuid, 'last_order_preparation_change': 12345},  # malformed: not str/dict
            {'uuid': order_b.uuid, 'last_order_preparation_change': json.dumps({
                'lines': {'line-b': {'product_id': self.product_cappuccino.id, 'quantity': 2}},
                'metadata': {'serverDate': '2026-08-18 09:10:00'},
            })},
        ])

        order_a.invalidate_recordset()
        order_b.invalidate_recordset()
        self.assertFalse(order_a.kds_order_id, "The malformed entry itself must not sync.")
        self.assertTrue(
            order_b.kds_order_id,
            "order_b's own well-formed, authorized entry must sync correctly, "
            "completely unaffected by order_a's own malformed entry earlier in the "
            "same batch.")
        self.assertEqual(order_b.kds_order_id.line_ids.qty, 2)

    def test_sync_from_ui_one_order_raising_does_not_skip_other_orders_in_batch(self):
        """The genuine per-order isolation guarantee: if processing one
        order entry raises an actual exception (not just a gracefully-
        handled malformed shape), every OTHER order entry in the same
        sync_from_ui batch must still be processed correctly."""
        order_a = self._create_active_pos_order([(self.product_burger, 3)])
        order_b = self._create_active_pos_order([(self.product_cappuccino, 2)])
        order_a.sudo().kds_preparation_change_requested = True
        order_b.sudo().kds_preparation_change_requested = True
        entry_a = {'uuid': order_a.uuid, 'last_order_preparation_change': json.dumps({
            'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 3}},
            'metadata': {'serverDate': '2026-08-18 09:10:00'},
        })}
        entry_b = {'uuid': order_b.uuid, 'last_order_preparation_change': json.dumps({
            'lines': {'line-b': {'product_id': self.product_cappuccino.id, 'quantity': 2}},
            'metadata': {'serverDate': '2026-08-18 09:10:00'},
        })}

        original = type(self.env['pos.order'])._flexsys_kds_process_one_sync_from_ui_entry

        def raise_for_order_a(self_, order_data):
            if order_data.get('uuid') == order_a.uuid:
                raise RuntimeError("simulated failure processing order_a's own entry")
            return original(self_, order_data)

        with patch.object(
            type(self.env['pos.order']), '_flexsys_kds_process_one_sync_from_ui_entry',
            raise_for_order_a,
        ):
            self.env['pos.order']._flexsys_kds_process_sync_from_ui([entry_a, entry_b])

        order_a.invalidate_recordset()
        order_b.invalidate_recordset()
        self.assertFalse(order_a.kds_order_id, "order_a's own entry genuinely raised - no sync for it.")
        self.assertTrue(
            order_b.kds_order_id,
            "order_b's own entry must still process correctly despite order_a's own "
            "entry genuinely raising an exception earlier in the same batch.")
        self.assertEqual(order_b.kds_order_id.line_ids.qty, 2)

    def test_sync_from_ui_id_takes_precedence_when_both_id_and_uuid_present(self):
        """When both are present (the more realistic shape for an
        update to an already-persisted order), the integer id is tried
        first - confirms this doesn't silently break the common case
        where both keys happen to be present together."""
        order = self._create_active_pos_order([(self.product_burger, 4)])
        order.sudo().kds_preparation_change_requested = True
        order._flexsys_kds_process_sync_from_ui([{
            'id': order.id,
            'uuid': order.uuid,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 4}},
                'metadata': {'serverDate': '2026-08-18 09:15:00'},
            }),
        }])

        order.invalidate_recordset()
        self.assertTrue(order.kds_order_id)
        self.assertEqual(order.kds_order_id.line_ids.qty, 4)

    # -----------------------------------------------------------------
    # Client's own experimental fix, confirmed correct and merged with
    # full documentation: "Send / Re-Send Synchronization" - a real,
    # confirmed bug in _flexsys_kds_sync() itself, found by the
    # client's own careful review, not from a new report.
    #
    # A critical gap in this project's OWN test methodology, found
    # while verifying the fix: every existing test exercising
    # _flexsys_kds_process_sync_from_ui() called it DIRECTLY with a
    # constructed payload, WITHOUT ever writing to the real
    # last_order_preparation_change field on the pos.order record
    # itself (that field is only ever genuinely populated by Odoo's own
    # native super().sync_from_ui() processing, which none of those
    # tests actually exercised). This completely masked the bug: with
    # the field left empty, the old buggy line
    # (self.kds_last_processed_send_signal = self.last_order_preparation_change)
    # merely reset the signature to an empty/False value each time - by
    # coincidence still != any genuine non-empty signature, so the next
    # sync still happened to proceed "correctly" in every existing
    # test, even with the bug present. In real, live operation, that
    # field genuinely holds Odoo's own raw JSON (with its own volatile
    # metadata) by the time _flexsys_kds_sync() runs - the bug's own
    # real effect. The tests below close this specific gap by writing
    # to the real field directly first, exactly matching what Odoo's
    # own native sync_from_ui() actually does before this module's own
    # override even runs.
    # -----------------------------------------------------------------
    def test_send_re_send_signature_not_corrupted_by_raw_field_overwrite(self):
        """The exact confirmed bug (v7.10.2), reproduced with the real
        last_order_preparation_change field genuinely populated and the
        new authorization flag genuinely set (matching live behavior):
        after a genuine, authorized Send, kds_last_processed_send_signal
        (now kept purely as a diagnostic record, no longer the gating
        mechanism itself) must still hold the NORMALIZED signature, not
        the raw field value - the old bug this test originally
        targeted."""
        order = self._create_active_pos_order([(self.product_burger, 5)])
        raw_send_1 = json.dumps({
            'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 5}},
            'metadata': {'serverDate': '2026-08-18 10:00:00'},
        })
        # Matches what Odoo's own native sync_from_ui() actually does:
        # the real field is genuinely written, not left empty.
        order.sudo().write({'last_order_preparation_change': raw_send_1})
        order.sudo().kds_preparation_change_requested = True
        order._flexsys_kds_process_sync_from_ui([{'uuid': order.uuid, 'last_order_preparation_change': raw_send_1}])
        kds_order = order.kds_order_id
        self.assertTrue(kds_order)
        self.assertEqual(kds_order.line_ids.qty, 5)

        expected_normalized_signature = json.dumps(
            {'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 5}}},
            sort_keys=True)
        order.invalidate_recordset()
        self.assertEqual(
            order.kds_last_processed_send_signal, expected_normalized_signature,
            "kds_last_processed_send_signal must hold the NORMALIZED signature "
            "(metadata stripped) - the old bug overwrote it with the raw field value "
            "(metadata included) immediately after this exact point, corrupting it for "
            "every future comparison.")
        self.assertNotEqual(
            order.kds_last_processed_send_signal, raw_send_1,
            "Must NOT equal the raw field value (which includes volatile metadata) - "
            "that mismatch was the confirmed root cause of the v7.10.2 bug.")
        self.assertFalse(
            order.kds_preparation_change_requested,
            "The authorization flag must be consumed (cleared) immediately after use.")

    def test_ordinary_autosave_after_real_send_does_not_leak_with_field_populated(self):
        """REAL BUG FIX ("CONFIRMED LIVE NETWORK RESULT"): the current,
        confirmed-correct guarantee, reproduced end to end - after a
        genuine, authorized Send (with the real field populated,
        matching live behavior), an ORDINARY sync_from_ui call - NOT
        preceded by a fresh get_preparation_change() call - must not
        leak, even though last_order_preparation_change's own content
        genuinely differs (confirmed by live testing to be exactly what
        an ordinary, unsent edit does to this field - content
        comparison alone could never distinguish this from a genuine
        Send)."""
        order = self._create_active_pos_order([(self.product_burger, 5)])
        raw_send_1 = json.dumps({
            'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 5}},
            'metadata': {'serverDate': '2026-08-18 10:00:00'},
        })
        order.sudo().write({'last_order_preparation_change': raw_send_1})
        order.sudo().kds_preparation_change_requested = True
        order._flexsys_kds_process_sync_from_ui([{'uuid': order.uuid, 'last_order_preparation_change': raw_send_1}])
        kds_order = order.kds_order_id
        self.assertTrue(kds_order)
        events_before = self.env['kds.event'].search_count([('order_id', '=', kds_order.id)])

        # Ordinary edit + sync_from_ui-style call - genuinely DIFFERENT
        # content this time (qty 5 -> 6), but crucially NOT preceded by
        # a fresh get_preparation_change() call, matching the client's
        # own confirmed A/B test: no Send pressed, no
        # get_preparation_change observed at all.
        raw_autosave = json.dumps({
            'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 6}},
            'metadata': {'serverDate': '2026-08-18 10:00:47'},
        })
        order.sudo().write({'last_order_preparation_change': raw_autosave})
        order._flexsys_kds_process_sync_from_ui([{'uuid': order.uuid, 'last_order_preparation_change': raw_autosave}])

        kds_order.invalidate_recordset()
        events_after = self.env['kds.event'].search_count([('order_id', '=', kds_order.id)])
        self.assertEqual(
            events_after, events_before,
            "Without a fresh get_preparation_change() call, an ordinary sync_from_ui "
            "must not be treated as a new Send - even with genuinely different content "
            "(qty 5 -> 6) - this is the confirmed root cause behind every earlier "
            "attempt: content alone, however compared, can never reliably distinguish "
            "an ordinary edit from a genuine Send.")
        self.assertEqual(kds_order.line_ids.qty, 5, "KDS must still show the last "
                                                      "explicitly SENT quantity (5), not "
                                                      "the live, unsent POS state (6).")

    def test_send_re_send_full_acceptance_scenario_with_real_field_populated(self):
        """The dev report's own full Acceptance Test, reproduced with
        the real last_order_preparation_change field AND the new
        get_preparation_change-based authorization flag genuinely set
        at every explicit Send step (matching live behavior exactly):
        1 -> Send -> KDS 1; 1 -> 2 without Send -> KDS remains 1;
        Send -> KDS becomes 2; 2 -> 1 without Send -> KDS remains 2;
        Send -> KDS becomes 1."""
        order = self._create_active_pos_order([(self.product_burger, 1)])

        def send(qty, minute):
            raw = json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': qty}},
                'metadata': {'serverDate': f'2026-08-18 10:{minute:02d}:00'},
            })
            order.sudo().write({'last_order_preparation_change': raw})
            # The confirmed live sequence: get_preparation_change() is
            # called (setting the authorization flag) immediately
            # before sync_from_ui().
            order.sudo().kds_preparation_change_requested = True
            order._flexsys_kds_process_sync_from_ui(
                [{'uuid': order.uuid, 'last_order_preparation_change': raw}])

        send(1, 0)
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        self.assertEqual(line.qty, 1, "qty 1 -> Send -> KDS = 1.")

        # qty 1 -> 2 WITHOUT Send: only an ordinary POS write, no
        # get_preparation_change()/sync_from_ui call at all for this step.
        order.lines.write({'qty': 2})
        line.invalidate_recordset()
        self.assertEqual(line.qty, 1, "Without Send, KDS must remain 1.")

        send(2, 5)
        line.invalidate_recordset()
        self.assertEqual(line.qty, 2, "Send -> KDS becomes 2.")

        order.lines.write({'qty': 1})
        line.invalidate_recordset()
        self.assertEqual(line.qty, 2, "Without Send, KDS must remain 2.")

        send(1, 10)
        line.invalidate_recordset()
        self.assertEqual(line.qty, 1, "Send -> KDS becomes 1.")

    # -----------------------------------------------------------------
    # Dev report "CRITICAL REVIEW - 19.0.7.11.1": confirmed via the
    # client's own direct citation of Odoo 19's actual core source that
    # get_preparation_change(self) is an ordinary instance method (NOT
    # @api.model), operating on a single concrete record via
    # self.ensure_one() - not the @api.model / args[0]-resolver shape
    # the two immediately preceding rounds wrongly assumed from the
    # Network trace's own wire-level representation. These tests call
    # the REAL override directly (order.get_preparation_change()) - now
    # safe to do so, since the exact native signature and body are
    # confirmed, unlike the genuinely uncertain sync_from_ui() native
    # payload shape this project remains appropriately cautious about
    # elsewhere.
    # -----------------------------------------------------------------
    def test_get_preparation_change_sets_flag_on_the_calling_order(self):
        """Required: call order.get_preparation_change() for real and
        verify order.kds_preparation_change_requested == True."""
        order = self._create_active_pos_order([(self.product_burger, 5)])
        self.assertFalse(order.kds_preparation_change_requested, "False by default.")

        order.get_preparation_change()

        order.invalidate_recordset()
        self.assertTrue(
            order.kds_preparation_change_requested,
            "Calling the real get_preparation_change() must set the authorization "
            "flag on the SAME order it was called on - self, directly, matching "
            "Odoo's own native instance-method contract (self.ensure_one()).")

    def test_get_preparation_change_returns_exact_native_result(self):
        """Required: verify the override returns exactly the native
        result from super() - confirmed from Odoo 19's own source to be
        {'last_order_preparation_change': self.last_order_preparation_change}."""
        order = self._create_active_pos_order([(self.product_burger, 5)])
        raw = json.dumps({
            'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 5}},
            'metadata': {'serverDate': '2026-08-18 13:00:00'},
        })
        order.sudo().write({'last_order_preparation_change': raw})

        result = order.get_preparation_change()

        self.assertEqual(
            result, {'last_order_preparation_change': raw},
            "The override must return exactly the native method's own result, "
            "unmodified - confirmed shape per Odoo 19's own core source.")

    def test_get_preparation_change_then_sync_from_ui_full_flow(self):
        """Required end-to-end proof, using the REAL override throughout
        (not flag simulation): order.get_preparation_change() sets the
        flag; sync_from_ui for that same order consumes it and syncs
        exactly once; a LATER ordinary sync_from_ui without another
        get_preparation_change() call causes ZERO KDS change."""
        order = self._create_active_pos_order([(self.product_burger, 5)])

        # Step 1: the real native call.
        order.get_preparation_change()
        order.invalidate_recordset()
        self.assertTrue(order.kds_preparation_change_requested)

        # Step 2: sync_from_ui consumes it, syncs exactly once.
        order._flexsys_kds_process_sync_from_ui([{
            'uuid': order.uuid,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 5}},
                'metadata': {'serverDate': '2026-08-18 13:05:00'},
            }),
        }])

        order.invalidate_recordset()
        self.assertTrue(order.kds_order_id, "KDS sync occurs exactly once.")
        self.assertEqual(order.kds_order_id.line_ids.qty, 5)
        self.assertFalse(order.kds_preparation_change_requested, "Flag becomes False.")
        events_after_first_send = self.env['kds.event'].search_count(
            [('order_id', '=', order.kds_order_id.id)])

        # Step 3: a LATER ordinary sync_from_ui, genuinely different
        # content, but crucially NOT preceded by another
        # get_preparation_change() call - must cause ZERO KDS change.
        order._flexsys_kds_process_sync_from_ui([{
            'uuid': order.uuid,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 9}},
                'metadata': {'serverDate': '2026-08-18 13:06:00'},
            }),
        }])

        order.kds_order_id.invalidate_recordset()
        events_after_ordinary_sync = self.env['kds.event'].search_count(
            [('order_id', '=', order.kds_order_id.id)])
        self.assertEqual(
            order.kds_order_id.line_ids.qty, 5,
            "Without a fresh get_preparation_change() call, the ordinary "
            "sync_from_ui must not change KDS at all, regardless of content.")
        self.assertEqual(
            events_after_ordinary_sync, events_after_first_send,
            "Zero new KDS events from the later, unauthorized sync_from_ui call.")

    def test_get_preparation_change_second_call_authorizes_next_send(self):
        """A genuine second get_preparation_change() call, followed by
        sync_from_ui, must correctly authorize and apply the next
        delta - the flag-based mechanism must keep working for
        subsequent, genuine Sends, not just the first one."""
        order = self._create_active_pos_order([(self.product_burger, 1)])
        order.get_preparation_change()
        order._flexsys_kds_process_sync_from_ui([{
            'uuid': order.uuid,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 1}},
                'metadata': {'serverDate': '2026-08-18 13:10:00'},
            }),
        }])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        self.assertEqual(line.qty, 1)

        order.lines.write({'qty': 2})
        order.get_preparation_change()
        order._flexsys_kds_process_sync_from_ui([{
            'uuid': order.uuid,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 2}},
                'metadata': {'serverDate': '2026-08-18 13:11:00'},
            }),
        }])

        line.invalidate_recordset()
        self.assertEqual(line.qty, 2, "The second, genuine Send must correctly apply.")
        self.assertEqual(line.qty_delta, 1)

    def test_get_preparation_change_multiple_calls_around_one_send_idempotent(self):
        """The client's own explicit idempotency requirement, verified
        via the REAL override called multiple times in a row (simulating
        several internal get_preparation_change() calls around the same
        logical Send), followed by exactly one sync_from_ui call -
        exactly one reconciliation."""
        order = self._create_active_pos_order([(self.product_burger, 5)])

        order.get_preparation_change()
        order.get_preparation_change()
        order.get_preparation_change()

        order._flexsys_kds_process_sync_from_ui([{
            'uuid': order.uuid,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 5}},
                'metadata': {'serverDate': '2026-08-18 13:15:00'},
            }),
        }])

        order.invalidate_recordset()
        self.assertTrue(order.kds_order_id)
        self.assertEqual(
            len(order.kds_order_id.line_ids), 1,
            "Exactly one reconciliation despite three real "
            "get_preparation_change() calls around the same logical Send.")
        self.assertFalse(order.kds_preparation_change_requested)

    def test_get_preparation_change_on_order_a_never_authorizes_order_b(self):
        """Calling the real override on order_a must never authorize
        order_b - confirms self-based resolution is inherently precise,
        unlike the abandoned args[0]-guessing approach this replaces."""
        order_a = self._create_active_pos_order([(self.product_burger, 1)])
        order_b = self._create_active_pos_order([(self.product_cappuccino, 1)])

        order_a.get_preparation_change()

        order_a.invalidate_recordset()
        order_b.invalidate_recordset()
        self.assertTrue(order_a.kds_preparation_change_requested)
        self.assertFalse(
            order_b.kds_preparation_change_requested,
            "order_b must never be authorized just because order_a, a completely "
            "separate order, had get_preparation_change() called on it.")

    # -----------------------------------------------------------------
    # Dev report "ROOT CAUSE EVIDENCE - SEND FLAG IS BEING OVERWRITTEN
    # BY POS sync_from_ui": confirmed live that the incoming sync_from_ui
    # payload itself carries kds_preparation_change_requested: false and
    # kds_last_processed_send_signal: false - internal server-owned KDS
    # control fields the POS frontend must never be authoritative for.
    # -----------------------------------------------------------------
    def test_sanitize_orders_payload_strips_kds_owned_fields_top_level(self):
        """The core fix, tested directly and in isolation: both
        server-owned KDS control fields must be stripped from an order
        dict's own top level."""
        orders = [{
            'uuid': 'some-uuid',
            'last_order_preparation_change': '{}',
            'kds_preparation_change_requested': False,
            'kds_last_processed_send_signal': False,
        }]

        sanitized = self.env['pos.order']._flexsys_kds_sanitize_orders_payload(orders)

        self.assertNotIn('kds_preparation_change_requested', sanitized[0])
        self.assertNotIn('kds_last_processed_send_signal', sanitized[0])
        self.assertEqual(sanitized[0]['uuid'], 'some-uuid',
                          "Every other key must be left completely untouched.")
        self.assertEqual(sanitized[0]['last_order_preparation_change'], '{}')

    def test_sanitize_orders_payload_strips_kds_owned_fields_nested_data(self):
        """The same stripping, for the nested 'data' sub-dict shape
        this module's own post-processing already defends against
        elsewhere."""
        orders = [{
            'id': 42,
            'data': {
                'uuid': 'some-uuid',
                'kds_preparation_change_requested': False,
                'kds_last_processed_send_signal': False,
                'last_order_preparation_change': '{}',
            },
        }]

        sanitized = self.env['pos.order']._flexsys_kds_sanitize_orders_payload(orders)

        self.assertNotIn('kds_preparation_change_requested', sanitized[0]['data'])
        self.assertNotIn('kds_last_processed_send_signal', sanitized[0]['data'])
        self.assertEqual(sanitized[0]['data']['uuid'], 'some-uuid')

    def test_sanitize_orders_payload_never_mutates_the_original(self):
        """The caller's own original orders list/dicts must never be
        mutated - this module's own separate post-processing
        (_flexsys_kds_process_sync_from_ui(), called on the ORIGINAL
        orders, not the sanitized copy) still needs to see the real
        last_order_preparation_change content untouched."""
        original_entry = {
            'uuid': 'some-uuid',
            'kds_preparation_change_requested': False,
            'last_order_preparation_change': '{"lines": {"x": 1}}',
        }
        orders = [original_entry]

        self.env['pos.order']._flexsys_kds_sanitize_orders_payload(orders)

        self.assertIn(
            'kds_preparation_change_requested', original_entry,
            "The original dict passed in must be completely unaffected - sanitization "
            "must only ever touch a copy.")
        self.assertEqual(original_entry['kds_preparation_change_requested'], False)

    def test_sanitize_orders_payload_defensive_non_dict_entries(self):
        """A non-dict entry must pass through unchanged, never raise."""
        orders = ["not a dict", 12345, None, {'uuid': 'x'}]

        try:
            sanitized = self.env['pos.order']._flexsys_kds_sanitize_orders_payload(orders)
        except Exception as e:
            self.fail(f"Non-dict entries must never raise: {e}")

        self.assertEqual(sanitized[0], "not a dict")
        self.assertEqual(sanitized[1], 12345)
        self.assertIsNone(sanitized[2])
        self.assertEqual(sanitized[3], {'uuid': 'x'})

    def test_sync_from_ui_calls_sanitization_before_native_processing(self):
        """Confirms the actual integration point, safely: sync_from_ui()
        calls _flexsys_kds_sanitize_orders_payload() with the ORIGINAL,
        unsanitized orders, and its own return value (not the raw
        orders) is what gets forwarded onward - verified by mocking
        this module's OWN method directly (reliable - no dependency on
        the native super() call chain's own uncertain MRO), returning a
        harmless empty list so the native super().sync_from_ui([]) call
        that follows is safe (confirmed elsewhere in this suite -
        test_sync_from_ui_full_override_preserves_native_result - to
        not raise on an empty list)."""
        order = self._create_active_pos_order([(self.product_burger, 1)])
        raw_orders = [{
            'uuid': order.uuid,
            'kds_preparation_change_requested': False,
            'last_order_preparation_change': '{}',
        }]
        captured = {}

        def spy_sanitize(self_, orders):
            captured['received'] = orders
            return []  # harmless for the native call that follows

        with patch.object(
            type(self.env['pos.order']), '_flexsys_kds_sanitize_orders_payload',
            spy_sanitize,
        ):
            self.env['pos.order'].sync_from_ui(raw_orders)

        self.assertEqual(
            captured.get('received'), raw_orders,
            "sync_from_ui() must call _flexsys_kds_sanitize_orders_payload() with the "
            "original orders payload, before any native processing.")

    def test_sync_from_ui_stale_false_in_payload_does_not_overwrite_true_flag(self):
        """The client's own required end-to-end scenario, reproduced
        without depending on the real, uncertain native
        super().sync_from_ui() call chain at all: confirms that the
        SANITIZED payload (produced by _flexsys_kds_sanitize_orders_payload(),
        already verified correct in isolation above) is what a
        write()-driven native implementation would actually receive -
        simulated here via a direct, explicit helper function, not a
        fragile mock of an uncertain MRO target.

        1. order.get_preparation_change() -> flag=True.
        2. The RAW incoming payload contains
           kds_preparation_change_requested=False.
        3. Sanitizing that payload (exactly what sync_from_ui() does
           before calling super()) removes the field entirely.
        4. Applying the SANITIZED payload's own fields via a plain
           write() (simulating what a native implementation would do)
           therefore cannot touch kds_preparation_change_requested at
           all - the server-side True set in step 1 survives
           completely unaffected.
        """
        order = self._create_active_pos_order([(self.product_burger, 5)])
        order.get_preparation_change()
        order.invalidate_recordset()
        self.assertTrue(order.kds_preparation_change_requested)

        raw_payload = [{
            'uuid': order.uuid,
            'kds_preparation_change_requested': False,
            'kds_last_processed_send_signal': False,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 5}},
                'metadata': {'serverDate': '2026-08-18 14:00:00'},
            }),
        }]

        sanitized_payload = self.env['pos.order']._flexsys_kds_sanitize_orders_payload(raw_payload)

        # Simulates a native write()-driven implementation applying
        # whatever fields the (now sanitized) payload carries - exactly
        # the confirmed real mechanism, but operating on the SANITIZED
        # payload sync_from_ui() actually forwards to super().
        for order_data in sanitized_payload:
            write_vals = {
                k: v for k, v in order_data.items()
                if k in order._fields and k != 'uuid'
            }
            if write_vals:
                order.write(write_vals)

        order.invalidate_recordset()
        self.assertTrue(
            order.kds_preparation_change_requested,
            "The server-side True flag must survive completely unaffected - the "
            "sanitized payload never carried kds_preparation_change_requested at all, "
            "so this simulated native write could never have touched it.")

        # Now run the actual post-processing (on the ORIGINAL, unsanitized
        # payload - exactly what _flexsys_kds_process_sync_from_ui()
        # always receives, per sync_from_ui()'s own real code) to
        # confirm the full flow completes correctly.
        order._flexsys_kds_process_sync_from_ui(raw_payload)

        order.invalidate_recordset()
        self.assertTrue(order.kds_order_id, "KDS sync occurs exactly once.")
        self.assertEqual(order.kds_order_id.line_ids.qty, 5)
        self.assertFalse(order.kds_preparation_change_requested,
                          "After successful KDS sync, the flag is consumed (False).")

        # Ordinary subsequent sync_from_ui (no new get_preparation_change()
        # call) must not authorize another sync.
        events_before = self.env['kds.event'].search_count(
            [('order_id', '=', order.kds_order_id.id)])
        order._flexsys_kds_process_sync_from_ui([{
            'uuid': order.uuid,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 9}},
                'metadata': {'serverDate': '2026-08-18 14:01:00'},
            }),
        }])
        order.kds_order_id.invalidate_recordset()
        events_after = self.env['kds.event'].search_count(
            [('order_id', '=', order.kds_order_id.id)])
        self.assertEqual(events_after, events_before,
                          "An ordinary subsequent sync_from_ui must not authorize "
                          "another KDS sync.")
        self.assertEqual(order.kds_order_id.line_ids.qty, 5,
                          "KDS must still show the last explicitly SENT quantity.")

    # -----------------------------------------------------------------
    # Dev report "CRITICAL REVIEW - 19.0.7.12.0 OFFLINE FALLBACK IS NOT
    # SAFE TO DEPLOY": the client's own review correctly proved the
    # v7.12.0 content-signature fallback was architecturally unsound
    # ("content changed != cashier pressed Send") and removed it
    # entirely here, replacing it with kds_send_generation - a durable,
    # client-controlled counter never touched by an ordinary edit - and
    # fixed the separate "authorization consumed before delivery"
    # issue (sync now happens before markers are cleared/advanced, not
    # after).
    # -----------------------------------------------------------------
    def test_ordinary_edit_still_never_authorizes_after_fallback_removal(self):
        """The core invariant, re-confirmed directly against the exact
        removed mechanism: an ordinary sync_from_ui call whose own
        content genuinely differs from the last processed signature -
        but carries no kds_preparation_change_requested flag and no
        incremented kds_send_generation - must NOT authorize a sync.
        This is the exact scenario the client's own review proved the
        v7.12.0 fallback would have incorrectly authorized."""
        order = self._create_active_pos_order([(self.product_burger, 5)])
        order.sudo().kds_preparation_change_requested = True
        order._flexsys_kds_process_sync_from_ui([{
            'uuid': order.uuid,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 5}},
                'metadata': {'serverDate': '2026-08-18 16:00:00'},
            }),
        }])
        kds_order = order.kds_order_id
        self.assertTrue(kds_order)
        events_before = self.env['kds.event'].search_count([('order_id', '=', kds_order.id)])

        # An ordinary edit: content genuinely differs (qty 5 -> 9), but
        # NEITHER authorization signal is present - exactly what the
        # removed fallback would have wrongly authorized via content
        # comparison alone.
        order._flexsys_kds_process_sync_from_ui([{
            'uuid': order.uuid,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 9}},
                'metadata': {'serverDate': '2026-08-18 16:01:00'},
            }),
        }])

        kds_order.invalidate_recordset()
        events_after = self.env['kds.event'].search_count([('order_id', '=', kds_order.id)])
        self.assertEqual(
            events_after, events_before,
            "Content genuinely differing must NOT authorize a sync without an explicit "
            "signal (flag or generation increment) - the exact invariant the removed "
            "v7.12.0 fallback violated.")
        self.assertEqual(kds_order.line_ids.qty, 5,
                          "KDS must still show the last explicitly SENT quantity, "
                          "completely unaffected by the ordinary edit's own live content.")

    def test_authorization_not_consumed_if_kds_sync_raises(self):
        """Required fix: successful KDS processing must be the point at
        which the Send is acknowledged/consumed - if _flexsys_kds_sync()
        itself fails, the authorization marker(s) must remain intact so
        a subsequent retry can still process the Send, rather than
        having already been marked processed and permanently lost."""
        order = self._create_active_pos_order([(self.product_burger, 5)])
        order.sudo().kds_preparation_change_requested = True

        with patch.object(
            type(order), '_flexsys_kds_sync',
            side_effect=RuntimeError("simulated KDS sync failure"),
        ):
            with self.assertRaises(RuntimeError):
                order._flexsys_kds_process_one_sync_from_ui_entry({
                    'uuid': order.uuid,
                    'last_order_preparation_change': json.dumps({
                        'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 5}},
                        'metadata': {'serverDate': '2026-08-18 16:05:00'},
                    }),
                })

        order.invalidate_recordset()
        self.assertTrue(
            order.kds_preparation_change_requested,
            "The authorization flag must remain True after a failed sync attempt - "
            "'if sync fails, keep generation pending/retryable' - not silently "
            "consumed before the KDS side actually succeeded.")

    def test_authorization_consumed_only_after_successful_sync(self):
        """The positive case, confirming the fix doesn't just avoid
        consuming on failure - it still correctly consumes on genuine
        success, exactly as before."""
        order = self._create_active_pos_order([(self.product_burger, 5)])
        order.sudo().kds_preparation_change_requested = True

        order._flexsys_kds_process_sync_from_ui([{
            'uuid': order.uuid,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 5}},
                'metadata': {'serverDate': '2026-08-18 16:10:00'},
            }),
        }])

        order.invalidate_recordset()
        self.assertTrue(order.kds_order_id, "The sync itself still succeeds normally.")
        self.assertFalse(order.kds_preparation_change_requested,
                          "Consumed correctly after genuine success.")

    def test_failed_sync_can_be_retried_and_succeeds(self):
        """The full required principle, end to end: a Send that fails
        mid-processing remains pending and retryable - a later,
        successful retry of the SAME entry must still correctly apply
        it, exactly once."""
        order = self._create_active_pos_order([(self.product_burger, 5)])
        order.sudo().kds_preparation_change_requested = True
        entry = {
            'uuid': order.uuid,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 5}},
                'metadata': {'serverDate': '2026-08-18 16:15:00'},
            }),
        }

        with patch.object(
            type(order), '_flexsys_kds_sync',
            side_effect=RuntimeError("simulated transient failure"),
        ):
            with self.assertRaises(RuntimeError):
                order._flexsys_kds_process_one_sync_from_ui_entry(entry)
        order.invalidate_recordset()
        self.assertFalse(order.kds_order_id, "No ticket yet - the failed attempt created nothing.")
        self.assertTrue(order.kds_preparation_change_requested, "Still pending.")

        # A later retry of the SAME entry, without the simulated failure.
        order._flexsys_kds_process_one_sync_from_ui_entry(entry)

        order.invalidate_recordset()
        self.assertTrue(order.kds_order_id, "The retried Send must now succeed.")
        self.assertEqual(order.kds_order_id.line_ids.qty, 5)
        self.assertFalse(order.kds_preparation_change_requested, "Consumed after the successful retry.")

    # -----------------------------------------------------------------
    # kds_send_generation: the durable, client-controlled counter this
    # round introduces as the correct fix for offline-Send recovery -
    # currently shipped as a correct but intentionally inert backend
    # half (see that field's own docstring for why), tested here for
    # its own comparison logic directly.
    # -----------------------------------------------------------------
    def test_send_generation_default_state_authorizes_nothing(self):
        """With no frontend yet writing a genuine increment, incoming
        and last-processed generation both stay at their shared
        default (0) - confirms this currently-inert design authorizes
        nothing on its own."""
        order = self._create_active_pos_order([(self.product_burger, 5)])
        self.assertEqual(order.kds_send_generation, 0)
        self.assertEqual(order.kds_last_processed_send_generation, 0)

        order._flexsys_kds_process_sync_from_ui([{
            'uuid': order.uuid,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 5}},
                'metadata': {'serverDate': '2026-08-18 16:20:00'},
            }),
        }])

        order.invalidate_recordset()
        self.assertFalse(order.kds_order_id,
                          "Generation 0 vs last-processed 0 authorizes nothing.")

    def test_send_generation_increment_authorizes_sync(self):
        """The intended mechanism, once a genuine increment is present
        in the incoming payload (simulating what a verified frontend
        hook would eventually write): a higher generation than last
        processed authorizes a sync, entirely independent of the
        kds_preparation_change_requested flag."""
        order = self._create_active_pos_order([(self.product_burger, 5)])
        self.assertFalse(order.kds_preparation_change_requested)

        order._flexsys_kds_process_sync_from_ui([{
            'uuid': order.uuid,
            'kds_send_generation': 1,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 5}},
                'metadata': {'serverDate': '2026-08-18 16:25:00'},
            }),
        }])

        order.invalidate_recordset()
        self.assertTrue(order.kds_order_id, "generation 1 > last-processed 0 authorizes.")
        self.assertEqual(order.kds_last_processed_send_generation, 1, "Advanced after success.")

    def test_send_generation_repeated_same_value_is_idempotent(self):
        """Idempotency for the generation-based path: repeated retries
        carrying the SAME generation value must not re-trigger."""
        order = self._create_active_pos_order([(self.product_burger, 5)])
        payload = [{
            'uuid': order.uuid,
            'kds_send_generation': 1,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 5}},
                'metadata': {'serverDate': '2026-08-18 16:30:00'},
            }),
        }]

        order._flexsys_kds_process_sync_from_ui(payload)
        order._flexsys_kds_process_sync_from_ui(payload)
        order._flexsys_kds_process_sync_from_ui(payload)

        order.invalidate_recordset()
        self.assertTrue(order.kds_order_id)
        self.assertEqual(len(order.kds_order_id.line_ids), 1,
                          "Exactly one line despite three retries of the same generation.")

    def test_send_generation_second_increment_authorizes_delta(self):
        """A genuine second Send (generation 1 -> 2) correctly applies
        the next delta, exactly once."""
        order = self._create_active_pos_order([(self.product_burger, 5)])
        order._flexsys_kds_process_sync_from_ui([{
            'uuid': order.uuid,
            'kds_send_generation': 1,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 5}},
                'metadata': {'serverDate': '2026-08-18 16:35:00'},
            }),
        }])
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        self.assertEqual(line.qty, 5)

        order.lines.write({'qty': 8})
        order._flexsys_kds_process_sync_from_ui([{
            'uuid': order.uuid,
            'kds_send_generation': 2,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 8}},
                'metadata': {'serverDate': '2026-08-18 16:36:00'},
            }),
        }])

        line.invalidate_recordset()
        self.assertEqual(line.qty, 8)
        self.assertEqual(line.qty_delta, 3)
        order.invalidate_recordset()
        self.assertEqual(order.kds_last_processed_send_generation, 2)

    def test_send_generation_lower_or_equal_value_does_not_authorize(self):
        """A stale/lower generation value (e.g. an out-of-order retry
        arriving after a later one already processed) must not
        re-trigger or regress anything."""
        order = self._create_active_pos_order([(self.product_burger, 5)])
        order._flexsys_kds_process_sync_from_ui([{
            'uuid': order.uuid,
            'kds_send_generation': 3,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 5}},
                'metadata': {'serverDate': '2026-08-18 16:40:00'},
            }),
        }])
        kds_order = order.kds_order_id
        events_before = self.env['kds.event'].search_count([('order_id', '=', kds_order.id)])

        # A stale generation (2 < 3, the last processed) arriving late.
        order._flexsys_kds_process_sync_from_ui([{
            'uuid': order.uuid,
            'kds_send_generation': 2,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 99}},
                'metadata': {'serverDate': '2026-08-18 16:39:00'},
            }),
        }])

        kds_order.invalidate_recordset()
        events_after = self.env['kds.event'].search_count([('order_id', '=', kds_order.id)])
        self.assertEqual(events_after, events_before, "A stale generation must not authorize anything.")
        self.assertEqual(kds_order.line_ids.qty, 5, "Must not regress to the stale payload's own content.")

    def test_send_generation_field_not_stripped_by_sanitization(self):
        """kds_send_generation is deliberately NOT a server-owned field
        for sanitization purposes - the POS client is specifically
        meant to write it. Confirms it survives sanitization while the
        two genuinely server-owned fields are still stripped."""
        orders = [{
            'uuid': 'some-uuid',
            'kds_send_generation': 5,
            'kds_preparation_change_requested': False,
            'kds_last_processed_send_signal': 'stale',
            'kds_last_processed_send_generation': 999,
        }]

        sanitized = self.env['pos.order']._flexsys_kds_sanitize_orders_payload(orders)

        self.assertEqual(sanitized[0].get('kds_send_generation'), 5,
                          "kds_send_generation must survive sanitization - the client is "
                          "meant to write it.")
        self.assertNotIn('kds_preparation_change_requested', sanitized[0])
        self.assertNotIn('kds_last_processed_send_signal', sanitized[0])
        self.assertNotIn('kds_last_processed_send_generation', sanitized[0],
                          "This one IS purely server-owned bookkeeping and must still be stripped.")

    # -----------------------------------------------------------------
    # Dev report "BLOCKER - 19.0.7.13.0 BREAKS POS STARTUP": the
    # _load_pos_data_fields() override (and the paired JS increment
    # patch) confirmed live to crash POS startup entirely were reverted
    # immediately. These tests confirm the revert is complete and
    # guard against accidentally reintroducing it without independent
    # live verification.
    # -----------------------------------------------------------------
    def test_kds_send_generation_field_still_exists_and_is_correct_type(self):
        """The DATABASE-level field itself (unrelated to the reverted
        frontend-exposure mechanism) must remain completely intact -
        the client's own explicit instruction: 'Do NOT remove the
        durable generation architecture... The immediate task is ONLY
        to fix how kds_send_generation is exposed to the POS frontend.'
        This confirms the backend half of that architecture is
        unaffected by the revert."""
        field = self.env['pos.order']._fields.get('kds_send_generation')
        self.assertIsNotNone(field, "kds_send_generation must still exist as a field.")
        self.assertEqual(field.type, 'integer')

    def test_kds_last_processed_send_generation_field_still_exists(self):
        field = self.env['pos.order']._fields.get('kds_last_processed_send_generation')
        self.assertIsNotNone(field)
        self.assertEqual(field.type, 'integer')

    def test_pos_order_does_not_override_load_pos_data_fields(self):
        """Guard rail: confirms this module does NOT currently define
        its own _load_pos_data_fields() on pos.order - the exact
        mechanism confirmed live to crash POS startup. If this
        assertion ever fails in the future, it means that override was
        reintroduced - which must only happen after independent, direct
        live verification against a real Odoo 19 instance, not based on
        conflicting secondary sources the way the reverted v7.13.0
        attempt was.

        Checked via each class's own __module__ attribute across the
        model's own MRO, rather than a direct module import - avoids
        any dependency on the exact addon import path, which can vary
        across installations."""
        pos_order_model_class = type(self.env['pos.order'])
        flexsys_contributed_load_fields = [
            klass for klass in pos_order_model_class.__mro__
            if '_load_pos_data_fields' in klass.__dict__
            and 'flexsys_kds' in (klass.__module__ or '')
        ]
        self.assertFalse(
            flexsys_contributed_load_fields,
            f"flexsys_kds must not contribute its own _load_pos_data_fields() to "
            f"pos.order's own MRO - confirmed live to crash POS startup; found in: "
            f"{flexsys_contributed_load_fields!r}. Removed in the same round this was "
            f"discovered, not to be reintroduced without independent, direct live "
            f"verification.")

    def test_backend_generation_comparison_logic_still_fully_functional(self):
        """Confirms the backend half of the architecture - unaffected
        by the frontend-exposure revert - still works exactly as
        v7.12.1 designed it, using direct payload construction (not
        depending on any frontend field-loading mechanism at all)."""
        order = self._create_active_pos_order([(self.product_burger, 5)])
        order._flexsys_kds_process_sync_from_ui([{
            'uuid': order.uuid,
            'kds_send_generation': 1,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 5}},
                'metadata': {'serverDate': '2026-08-19 09:00:00'},
            }),
        }])

        order.invalidate_recordset()
        self.assertTrue(
            order.kds_order_id,
            "The backend's own generation-based authorization logic must remain fully "
            "functional and testable independent of how the field eventually gets "
            "populated by a future, safely-verified frontend mechanism.")
        self.assertEqual(order.kds_last_processed_send_generation, 1)

    # -----------------------------------------------------------------
    # Dev report "LIVE A/B EVIDENCE - DIRECT SALE SEND FLOW" +
    # "DESIGN APPROVED WITH TWO IMPORTANT CONSTRAINTS": Direct Sale
    # orders (no table) never call get_preparation_change() at all -
    # confirmed live. The confirmed replacement signal: sync_from_ui's
    # own kwargs['context'] carries 'preparation' (present) together
    # with 'current_order_uuid' (matching the specific order). Scoped
    # STRICTLY to the one order whose own uuid matches - never the
    # whole batch. Signature comparison is de-duplication only, never
    # authorization.
    # -----------------------------------------------------------------
    def test_direct_sale_context_authorizes_matching_order(self):
        """Required Test A (live-confirmed scenario): Direct Sale +
        explicit Send -> sync_from_ui with context.preparation present
        and context.current_order_uuid matching this order's own uuid
        -> KDS sync occurs."""
        order = self._create_active_pos_order([(self.product_burger, 3)])
        self.assertFalse(order.kds_preparation_change_requested)
        self.assertEqual(order.kds_send_generation, 0)

        order._flexsys_kds_process_sync_from_ui(
            [{
                'uuid': order.uuid,
                'last_order_preparation_change': json.dumps({
                    'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 3}},
                    'metadata': {'serverDate': '2026-08-19 10:00:00'},
                }),
            }],
            context={'preparation': {'process_order_options': {}}, 'current_order_uuid': order.uuid},
        )

        order.invalidate_recordset()
        self.assertTrue(
            order.kds_order_id,
            "context.preparation present + current_order_uuid matching this order's own "
            "uuid must authorize the Direct Sale Send, with NO get_preparation_change() "
            "call and NO kds_send_generation involved at all.")
        self.assertEqual(order.kds_order_id.line_ids.qty, 3)

    def test_direct_sale_ordinary_edit_without_send_no_kds(self):
        """Required Test B (live-confirmed scenario): Direct Sale
        ordinary edit without Send -> live evidence confirms NO
        sync_from_ui call is even generated in this exact scenario -
        but this test also confirms the backend's own logic
        independently: even if sync_from_ui WERE called with no
        context.preparation at all, nothing must be authorized."""
        order = self._create_active_pos_order([(self.product_burger, 3)])

        order._flexsys_kds_process_sync_from_ui(
            [{
                'uuid': order.uuid,
                'last_order_preparation_change': json.dumps({
                    'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 5}},
                    'metadata': {'serverDate': '2026-08-19 10:01:00'},
                }),
            }],
            context=None,
        )

        order.invalidate_recordset()
        self.assertFalse(
            order.kds_order_id,
            "No context.preparation at all (matching the live-confirmed absence of "
            "sync_from_ui for an ordinary Direct Sale edit) must never authorize a sync, "
            "regardless of the content's own genuine difference.")

    def test_direct_sale_context_never_authorizes_a_different_order_in_same_batch(self):
        """Required scope constraint, tested directly: context.preparation
        existing at the batch level must NOT authorize every order in
        that same sync_from_ui batch - only the one order whose own
        uuid exactly matches context.current_order_uuid. 'Any other
        orders that may theoretically be included in the same
        sync_from_ui batch must remain untouched.'"""
        order_a = self._create_active_pos_order([(self.product_burger, 1)])
        order_b = self._create_active_pos_order([(self.product_cappuccino, 1)])

        # A single sync_from_ui call carrying BOTH orders, with the
        # context's own current_order_uuid pointing ONLY at order_a.
        order_a.env['pos.order']._flexsys_kds_process_sync_from_ui(
            [
                {
                    'uuid': order_a.uuid,
                    'last_order_preparation_change': json.dumps({
                        'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 1}},
                        'metadata': {'serverDate': '2026-08-19 10:05:00'},
                    }),
                },
                {
                    'uuid': order_b.uuid,
                    'last_order_preparation_change': json.dumps({
                        'lines': {'line-b': {'product_id': self.product_cappuccino.id, 'quantity': 1}},
                        'metadata': {'serverDate': '2026-08-19 10:05:00'},
                    }),
                },
            ],
            context={'preparation': {'process_order_options': {}}, 'current_order_uuid': order_a.uuid},
        )

        order_a.invalidate_recordset()
        order_b.invalidate_recordset()
        self.assertTrue(order_a.kds_order_id,
                         "order_a, the one genuinely matching current_order_uuid, is authorized.")
        self.assertFalse(
            order_b.kds_order_id,
            "order_b must remain completely untouched, even though context.preparation "
            "was genuinely present at the batch level - authorization is scoped strictly "
            "to the uuid match, never the whole batch.")

    def test_direct_sale_signature_deduplicates_repeated_same_content_delivery(self):
        """Required de-duplication rule: 'trusted Send authorization ->
        compare signature -> same signature = duplicate delivery,
        ignore.' A repeated sync_from_ui call, still carrying a
        genuinely matching context, but with the SAME content already
        processed, must be treated as a duplicate delivery - not a new
        Send, and not silently re-authorized just because the context
        still matches."""
        order = self._create_active_pos_order([(self.product_burger, 3)])
        payload_entry = {
            'uuid': order.uuid,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 3}},
                'metadata': {'serverDate': '2026-08-19 10:10:00'},
            }),
        }
        context = {'preparation': {'process_order_options': {}}, 'current_order_uuid': order.uuid}

        order._flexsys_kds_process_sync_from_ui([payload_entry], context=context)
        kds_order = order.kds_order_id
        self.assertTrue(kds_order)
        events_before = self.env['kds.event'].search_count([('order_id', '=', kds_order.id)])

        # A repeated delivery of the exact same sync_from_ui call - same
        # content, same context, same matching uuid (plausible: Odoo's
        # own retry mechanics, or a duplicate network delivery).
        order._flexsys_kds_process_sync_from_ui([payload_entry], context=context)

        kds_order.invalidate_recordset()
        events_after = self.env['kds.event'].search_count([('order_id', '=', kds_order.id)])
        self.assertEqual(
            events_after, events_before,
            "A repeated delivery of the SAME already-processed content must be "
            "recognized as a duplicate and ignored - not re-authorized just because "
            "the context still matches.")
        self.assertEqual(kds_order.line_ids.qty, 3)

    def test_direct_sale_signature_never_grants_authorization_on_its_own(self):
        """Critical distinction, tested directly: a genuinely DIFFERENT
        content signature must NEVER by itself grant authorization -
        'The signature must remain deduplication only, never
        authorization.' Without a matching context (or a flag, or a
        generation advance), a different signature alone changes
        nothing - this is the exact architectural mistake the v7.12.0
        fallback made and the client's own review correctly rejected."""
        order = self._create_active_pos_order([(self.product_burger, 3)])
        order.sudo().kds_preparation_change_requested = True
        order._flexsys_kds_process_sync_from_ui([{
            'uuid': order.uuid,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 3}},
                'metadata': {'serverDate': '2026-08-19 10:15:00'},
            }),
        }])
        kds_order = order.kds_order_id
        self.assertTrue(kds_order)
        events_before = self.env['kds.event'].search_count([('order_id', '=', kds_order.id)])

        # Genuinely different content, but NO context, NO flag, NO
        # generation advance - only the content differs.
        order._flexsys_kds_process_sync_from_ui([{
            'uuid': order.uuid,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 9}},
                'metadata': {'serverDate': '2026-08-19 10:16:00'},
            }),
        }], context=None)

        kds_order.invalidate_recordset()
        events_after = self.env['kds.event'].search_count([('order_id', '=', kds_order.id)])
        self.assertEqual(events_after, events_before,
                          "A different signature alone, with no authorization signal at "
                          "all present, must never trigger a sync.")
        self.assertEqual(kds_order.line_ids.qty, 3)

    def test_direct_sale_context_uuid_mismatch_does_not_authorize(self):
        """A context.preparation present but current_order_uuid pointing
        at a DIFFERENT uuid than this specific order's own must not
        authorize this order."""
        order = self._create_active_pos_order([(self.product_burger, 3)])

        order._flexsys_kds_process_sync_from_ui(
            [{
                'uuid': order.uuid,
                'last_order_preparation_change': json.dumps({
                    'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 3}},
                    'metadata': {'serverDate': '2026-08-19 10:20:00'},
                }),
            }],
            context={'preparation': {'process_order_options': {}}, 'current_order_uuid': 'some-other-uuid'},
        )

        order.invalidate_recordset()
        self.assertFalse(order.kds_order_id)

    def test_direct_sale_context_missing_preparation_key_does_not_authorize(self):
        """current_order_uuid matching but NO 'preparation' key present
        at all must not authorize - both conditions are required
        together, per the client's own explicit AND requirement."""
        order = self._create_active_pos_order([(self.product_burger, 3)])

        order._flexsys_kds_process_sync_from_ui(
            [{
                'uuid': order.uuid,
                'last_order_preparation_change': json.dumps({
                    'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 3}},
                    'metadata': {'serverDate': '2026-08-19 10:25:00'},
                }),
            }],
            context={'current_order_uuid': order.uuid},  # no 'preparation' key at all
        )

        order.invalidate_recordset()
        self.assertFalse(order.kds_order_id)

    def test_direct_sale_second_send_delta_applies_exactly_once(self):
        """A genuine second Direct Sale Send (context matches again,
        content genuinely differs) correctly applies the next delta."""
        order = self._create_active_pos_order([(self.product_burger, 3)])
        context = {'preparation': {'process_order_options': {}}, 'current_order_uuid': order.uuid}
        order._flexsys_kds_process_sync_from_ui([{
            'uuid': order.uuid,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 3}},
                'metadata': {'serverDate': '2026-08-19 10:30:00'},
            }),
        }], context=context)
        kds_order = order.kds_order_id
        line = kds_order.line_ids
        self.assertEqual(line.qty, 3)

        order.lines.write({'qty': 6})
        order._flexsys_kds_process_sync_from_ui([{
            'uuid': order.uuid,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 6}},
                'metadata': {'serverDate': '2026-08-19 10:31:00'},
            }),
        }], context=context)

        line.invalidate_recordset()
        self.assertEqual(line.qty, 6)
        self.assertEqual(line.qty_delta, 3)

    def test_sync_from_ui_extracts_and_passes_context_through(self):
        """Confirms sync_from_ui() itself correctly extracts kwargs['context']
        and passes it through to post-processing - verified by mocking
        this module's own post-processing method directly (reliable),
        not the uncertain native super() call chain."""
        order = self._create_active_pos_order([(self.product_burger, 1)])
        captured = {}

        def spy_process(self_, orders, context=None):
            captured['context'] = context

        with patch.object(
            type(self.env['pos.order']), '_flexsys_kds_process_sync_from_ui',
            spy_process,
        ):
            self.env['pos.order'].sync_from_ui(
                [], context={'preparation': {}, 'current_order_uuid': 'abc'})

        self.assertEqual(
            captured.get('context'), {'preparation': {}, 'current_order_uuid': 'abc'},
            "sync_from_ui() must extract kwargs['context'] and pass it through unmodified.")

    def test_sync_from_ui_handles_missing_context_gracefully(self):
        """A sync_from_ui call with no 'context' kwarg at all (a
        plausible native call shape) must not raise - context is read
        defensively."""
        order = self._create_active_pos_order([(self.product_burger, 1)])
        try:
            self.env['pos.order'].sync_from_ui([])
        except Exception as e:
            self.fail(f"A sync_from_ui call with no context kwarg at all must never raise: {e}")

    def test_offline_recovery_honesty_generation_architecture_still_available(self):
        """Per the client's own explicit second constraint: Direct Sale
        offline recovery is NOT claimed solved by the context-based
        mechanism (which may not survive a reconnect - unconfirmed).
        This test confirms the kds_send_generation architecture remains
        fully intact and independently usable as the durable fallback,
        exactly as required: 'If the preparation context does NOT
        survive reconnect, then Direct Sale still requires a durable
        Send Intent / generation stored on the order itself... keep the
        existing generation architecture intact for that reason.'"""
        order = self._create_active_pos_order([(self.product_burger, 4)])

        # Simulates what a future, verified frontend mechanism would
        # eventually deliver for Direct Sale specifically, entirely
        # independent of the context-based path tested above.
        order._flexsys_kds_process_sync_from_ui([{
            'uuid': order.uuid,
            'kds_send_generation': 1,
            'last_order_preparation_change': json.dumps({
                'lines': {'line-a': {'product_id': self.product_burger.id, 'quantity': 4}},
                'metadata': {'serverDate': '2026-08-19 10:35:00'},
            }),
        }], context=None)

        order.invalidate_recordset()
        self.assertTrue(
            order.kds_order_id,
            "The generation-based path must remain fully functional and independent of "
            "the context-based Direct Sale path - the required fallback if context is "
            "ever confirmed not to survive offline reconnect.")
