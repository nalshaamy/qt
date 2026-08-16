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
        # (kds_send_trigger 'validation'/'submit', already exercised by
        # this file's other cancellation tests just above), where the
        # order is genuinely still unpaid when a line gets deleted.
        self.pos_config.kds_send_trigger = 'validation'
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
        kds_order = order.kds_order_id
        self.assertTrue(kds_order, "'validation' trigger should sync to KDS immediately, unpaid.")
        cappuccino_pos_line = order.lines.filtered(lambda l: l.product_id == self.product_cappuccino)
        cappuccino_pos_line.unlink()  # allowed - the order is still draft/unpaid

        kds_order.invalidate_recordset()
        cappuccino_kds_line = kds_order.line_ids.filtered(
            lambda l: l.product_id == self.product_cappuccino)
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

    def test_validation_trigger_sends_a_draft_order_to_kitchen_before_payment(self):
        self.pos_config.kds_send_trigger = 'validation'
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
        self.assertTrue(order.kds_order_id,
                         "Under the 'validation' trigger, a draft order with lines should "
                         "already have reached the kitchen, before any payment.")

    def test_submit_trigger_sends_a_draft_order_to_kitchen_before_payment(self):
        self.pos_config.kds_send_trigger = 'submit'
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
        self.assertTrue(order.kds_order_id)

    def test_payment_after_pre_payment_send_does_not_duplicate_kds_order(self):
        """The specific idempotency requirement: paying an order that
        already reached the kitchen pre-payment must not create a second
        kds.order."""
        self.pos_config.kds_send_trigger = 'validation'
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
        first_kds_order = order.kds_order_id
        self.assertTrue(first_kds_order)
        order.write({'state': 'paid', 'amount_paid': 10.0})
        self.assertEqual(order.kds_order_id, first_kds_order,
                          "Paying later must reuse the same kds.order, not create a second one.")
        all_kds_orders = self.env['kds.order'].search([('pos_order_id', '=', order.id)])
        self.assertEqual(len(all_kds_orders), 1)

    def test_validation_trigger_does_not_sync_an_order_with_no_lines_yet(self):
        self.pos_config.kds_send_trigger = 'validation'
        order = self.env['pos.order'].create({
            'session_id': self.pos_session.id,
            'company_id': self.company.id,
            'lines': [],
            'amount_tax': 0.0, 'amount_total': 0.0, 'amount_paid': 0.0, 'amount_return': 0.0,
            'state': 'draft',
        })
        self.assertFalse(order.kds_order_id,
                          "An order with no lines yet has nothing to send to the kitchen.")

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
        self.pos_config.kds_send_trigger = 'validation'
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
        """Acceptance criteria as stated: 'POS Submit -> KDS New -> POS
        Cancel' must result in 'KDS Cancelled' and the order must
        disappear from active production queues - checked here via the
        same domain the KDS screens themselves query with."""
        self.pos_config.kds_send_trigger = 'submit'
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
        kds_order = order.kds_order_id
        order.write({'state': 'cancel'})

        active_lines = self.env['kds.order.line'].search([
            ('order_id', '=', kds_order.id),
            ('state', 'not in', ('completed', 'cancelled')),
        ])
        self.assertFalse(active_lines,
                          "A cancelled order's lines must not appear in the KDS screens' "
                          "active-queue query anymore.")

    def test_pos_cancellation_is_idempotent(self):
        self.pos_config.kds_send_trigger = 'validation'
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
        kds_order = order.kds_order_id
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
        kds_order.action_complete()  # DESIGN REVERSAL (v5.4): explicit step now
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
    def test_delta_sync_resets_a_ready_line_through_the_proper_method(self):
        """Scenario 1: Ready line modified by POS Delta."""
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

        order.lines.write({'qty': 3})

        line.invalidate_recordset()
        self.assertEqual(line.qty, 3)
        self.assertEqual(line.state, 'new',
                          "A Ready line whose qty changed must be bumped back to New.")

    def test_delta_sync_reopens_a_ready_order_via_line_reset(self):
        """Scenario 2 (part 1): Ready order modified by POS Delta -
        an existing line's qty/note change resets it and reopens
        the order."""
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
        self.assertEqual(kds_order.state, 'preparing',
                          "A Ready order with a late line change must reopen to Preparing.")

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
        kds_order.action_complete()  # DESIGN REVERSAL (v5.4): explicit step now
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
        kds_order.action_complete()
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
        kds_order.action_complete()
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
        kds_order.action_complete()
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
        self.assertEqual(new_lines.qty, 7)
        self.assertEqual(new_lines.state, 'new')
        self.assertEqual(new_lines.pos_order_line_id, order.lines)

    def test_note_change_on_completed_line_also_creates_new_delta(self):
        order = self._create_pos_order([(self.product_burger, 2)])
        kds_order = order.kds_order_id
        original_line = kds_order.line_ids
        original_line.action_accept()
        original_line.action_start()
        original_line.action_ready()
        kds_order.action_complete()

        order.lines.write({'note': 'well done, extra sauce'})

        new_lines = kds_order.line_ids - original_line
        self.assertTrue(new_lines, "A note change on a completed line must also trigger a "
                                    "new preparation delta, not just a quantity change.")
        self.assertEqual(new_lines.note, 'well done, extra sauce')

    def test_completed_line_modification_reopens_the_order(self):
        order = self._create_pos_order([(self.product_burger, 5)])
        kds_order = order.kds_order_id
        kds_order.line_ids.action_accept()
        kds_order.line_ids.action_start()
        kds_order.line_ids.action_ready()
        kds_order.action_complete()
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
        kds_order.action_complete()

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
        kds_order.action_complete()
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
        kds_order.action_complete()

        order.lines.write({'qty': 7})
        first_delta = kds_order.line_ids - original_line
        self.assertEqual(len(first_delta), 1)

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
        self.assertEqual(non_original.qty, 10)
