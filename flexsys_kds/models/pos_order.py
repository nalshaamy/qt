# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


def _pos_note(record, default=''):
    """Read a POS order/line 'note' field defensively.

    Confirmed by a real runtime error in production: this Odoo 19 build
    does not have a 'note' field on pos.order at all
    ("'pos.order' object has no attribute 'note'"), which crashed the
    entire payment flow (not just FlexSys KDS) since this ran as part of
    order confirmation. Applied to pos.order.line reads too, defensively,
    in case that field has also been renamed/removed here and I just
    haven't hit the error for it yet - better a blank note than another
    crash blocking checkout.
    """
    return getattr(record, 'note', default) or default


def _pos_line_variant_info(line):
    """Best-effort description of a line's selected variant/attributes
    (size, flavor, add-ons chosen at sale time), kept separate from the
    free-text customer note so the KDS card can style/label them
    differently.

    product_id.display_name usually already includes the variant's
    attribute values in parentheses (e.g. "Iced Latte (Large, Oat
    Milk)") for a true product.product variant - that's the reliable
    part. Attribute/combo selections made at the *order line* level
    (Odoo's "optional products" / custom attribute value flows) have
    used different field names across versions, so those are checked
    defensively via `_fields` rather than assumed.
    """
    product = line.product_id
    parts = []
    if product.display_name and product.name and product.display_name != product.name:
        variant_part = product.display_name.replace(product.name, '', 1).strip(' ()')
        if variant_part:
            parts.append(variant_part)
    for field_name in ('attribute_value_ids', 'custom_attribute_value_ids'):
        if field_name in line._fields:
            values = getattr(line, field_name)
            if values:
                label_field = 'display_name' if 'display_name' in values._fields else 'name'
                parts.append(', '.join(values.mapped(label_field)))
    return ' / '.join(p for p in parts if p)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    kds_order_id = fields.Many2one('kds.order', string='FlexSys KDS Order', copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        for order, vals in zip(orders, vals_list):
            # CHANGE REQUEST FIX ("On Send to KDS"): a brand-new order
            # can itself already carry last_order_preparation_change in
            # its own initial creation vals (e.g. an order created and
            # immediately Sent in the same frontend round-trip) - checked
            # here too, not just in write(), so that scenario is
            # correctly recognized as a genuine Send trigger from the
            # very first sync attempt.
            order._flexsys_kds_sync(is_send_write='last_order_preparation_change' in vals)
        return orders

    def write(self, vals):
        res = super().write(vals)
        # REAL BUG FIX, confirmed live: this gate used to check only
        # 'state' or 'lines' - but the native Send/New signal
        # (last_order_preparation_change) can arrive in a write() call
        # on its own, with neither 'state' nor 'lines' also present in
        # that same vals dict (e.g. Preparation Display's own "Send"
        # action writing only the preparation-change field). That write
        # never entered this block at all, so is_send_write was never
        # even computed and _flexsys_kds_sync() was never called - "On
        # Send to KDS" mode silently never synced anything, since the
        # one write that was SUPPOSED to trigger it didn't reach the
        # trigger check in the first place. Added explicitly to the
        # gate condition itself, not just used inside it.
        if 'state' in vals or 'lines' in vals or 'last_order_preparation_change' in vals:
            # CHANGE REQUEST FIX ("On Send to KDS"), confirmed live -
            # see _flexsys_kds_sync()'s own docstring for the full
            # explanation of why last_order_preparation_change is the
            # signal used here.
            is_send_write = 'last_order_preparation_change' in vals
            for order in self:
                order = order.sudo()
                if vals.get('state') == 'cancel':
                    order._flexsys_kds_cancel()
                else:
                    order._flexsys_kds_sync(is_send_write=is_send_write)
        return res

    def _flexsys_kds_cancel(self):
        """AUDIT FIX / NEW REQUIREMENT ("POS Cancellation Propagation",
        IMPORTANT): supporting pre-payment Send Triggers (kds_send_trigger
        on pos.config) introduced a real lifecycle gap - a POS order that
        already reached the kitchen and then gets cancelled used to leave
        its kds.order silently active forever, a ghost ticket still
        sitting in the production queue with nothing to signal what
        happened. Idempotent by construction: kds.order.action_cancel()
        checks the order isn't already in a terminal state before doing
        anything (via _wf_transition's own transition-matrix validation,
        backed up by the explicit early-return here), so calling this
        more than once on an already-cancelled/already-completed order is
        always a safe no-op - no duplicate events, no exception.

        Deliberately does NOT retroactively cancel an order that's
        already fully Completed by the time the POS side is cancelled
        (e.g. a very late POS-side correction after the food was already
        served) - preserves that production history rather than
        rewriting it, matching the same "completed work is never
        silently undone" principle used elsewhere (product-change
        reroute, action_cancel's own line-level filtering).
        """
        self.ensure_one()
        self = self.sudo()
        kds_order = self.kds_order_id
        if not kds_order or kds_order.state in ('cancelled', 'completed'):
            return
        kds_order.action_cancel(bypass_check=True)

    # ---------------------------------------------------------------
    # Point 3: this used to be create-once ("if kds_order_id: return").
    # It is now a real sync entry point: first call creates the KDS
    # order+lines, every later call (line added/changed/removed after
    # the ticket was already sent to the kitchen) runs a delta diff that
    # emits ADDED / UPDATED / REMOVED instead of resending the order.
    #
    # Real bug fixed here: this used to run as whichever user happened to
    # be ringing up the sale (the cashier), which meant the FlexSys KDS
    # station-assignment record rule (kds.access.mixin /
    # rule_kds_order_line_station) blocked order creation entirely for
    # any cashier not personally assigned to a kitchen station - which is
    # every cashier, since assigning cashiers to kitchen stations makes
    # no sense. This is automated system integration triggered by a POS
    # sale, not an interactive station worker's own action, so it now
    # runs as sudo() - deliberately bypassing both ir.model.access and
    # ir.rule for this call chain, the same way any other Odoo
    # integration hook (e.g. a stock move triggered by confirming a sale
    # order) runs with elevated rights rather than under the confirming
    # user's own permissions.
    # ---------------------------------------------------------------
    def _flexsys_kds_is_refund_order(self):
        """CRITICAL FIX (dev request "Runtime Regression Fix Package",
        BUG-06 - "the highest-risk issue discovered in this testing
        round"): a financial refund/return must NEVER create or affect a
        kitchen preparation ticket. Confirmed live: refunding 1 x Club
        Sandwich on an already-Completed order created a brand new KDS
        ticket showing "-1 x Club Sandwich" with an active START button
        - a refund was silently treated as a fresh order to prepare.

        Detected here, at the authoritative ingestion point
        (_flexsys_kds_sync() below), not hidden in the frontend - a
        refund order excluded here never enters _flexsys_kds_create()/
        _flexsys_kds_diff_lines() at all, so it can never touch SLA,
        station workload, printing, analytics, counters, realtime
        events, or audit interpretation, matching the request's own
        explicit list of what must not be affected.

        Two independent, defensively-written signals, since this
        project has repeatedly confirmed (see hooks.py's own docstring
        for the history) that exact field names on core Odoo models are
        not something to hardcode a single assumption about in this
        specific build:

        1. `refunded_orderline_id` on pos.order.line - the standard
           Odoo field marking a line as refunding an original line, if
           present on this build. Checked for existence first, never
           assumed.
        2. Fallback: every actual product line (types this module cares
           about - see _flexsys_kds_create_lines' own filter) has a
           negative quantity. A refund order's lines are negative by
           construction; a genuine new sale's are not - this holds
           regardless of what any refund-tracking field happens to be
           named on a given build, so it still catches a refund order
           correctly even if signal 1 doesn't apply.

        A single line with a positive/zero quantity found among actual
        product lines is enough to conclude "this is a normal order",
        even if some other line happens to be negative for an unrelated
        reason (a discount line, a rounding line) - deliberately
        conservative, since wrongly treating a genuine order as a
        refund (silently dropping real kitchen work) is a worse failure
        than the reverse.
        """
        self.ensure_one()
        product_lines = self.lines.filtered(
            lambda l: l.product_id.type in ('consu', 'product', 'service'))
        if not product_lines:
            return False
        if 'refunded_orderline_id' in product_lines._fields:
            if any(product_lines.mapped('refunded_orderline_id')):
                return True
        return all(l.qty < 0 for l in product_lines)

    def _flexsys_kds_reconcile_refund(self):
        """REAL BUG FIX ("Paid Order Refund Is Not Synchronized Back to
        the Original KDS Ticket", CRITICAL/HIGH), confirmed live: a
        partial refund (1 of 2) and a subsequent full refund (the
        remaining 1) on an already-PREPARING KDS ticket left it
        completely unchanged - still showing the full original quantity,
        still PREPARING, still offering READY, even once the entire paid
        quantity had been refunded. "This is incorrect and operationally
        dangerous."

        Required concept, implemented exactly as specified: for each
        refunded original line, `effective_kitchen_qty = original_qty -
        cumulative_refunded_qty` - cumulative and idempotent by
        construction, since it's recomputed fresh from ALL refund lines
        against that original line every time this runs (search, not a
        running counter), so processing the same or an overlapping set
        of refunds twice, or in any order, converges on the same correct
        answer rather than double-subtracting.

        Never creates a new KDS ticket or a negative production line -
        this method only ever reduces or cancels an EXISTING
        kds.order.line, matching the same authoritative-backend
        principle BUG-06 already established for excluding a refund
        order from ingestion in the first place.

        Correlation relies on `refunded_orderline_id` (checked for
        existence first, same defensive posture as
        _flexsys_kds_is_refund_order() above, for the same reason - see
        that method's own docstring) - without it, there is no reliable
        way to identify which original line a given refund line
        corresponds to, so that specific line is silently skipped rather
        than guessed at (matching this method's own "wrongly affecting a
        genuine order is worse than doing nothing" philosophy).

        Stage-specific behavior, exactly as specified:
        - effective_qty <= 0 (fully refunded): cancels the ORIGINAL
          kds.order.line through the real action_cancel() if it's still
          active (New/Preparing/Ready) - full audit trail, the same
          CANCELLED display treatment and retention every other
          cancellation in this module already has. A line already
          Completed is never force-cancelled (action_cancel() itself
          would raise for a Completed line anyway) - logged as a
          terminal, informational event only, per "If operational
          visibility is desired, use a terminal informational state/
          event only - never production work."
        - effective_qty > 0 but reduced, line still active (New/
          Preparing/Ready): quantity reduced in place, current STATE is
          never touched - "do not reopen unnecessary production" for a
          Ready line, and a Preparing line correctly stays Preparing.
          qty_delta accumulates the same way a normal POS quantity
          decrease already does (BUG-09's own established mechanism),
          so the reduction shows as "UPDATED (-1)" on both screens.
        - effective_qty > 0, line already Completed: never mutated -
          "the original completed work remains historically completed"
          (the same principle BUG-02B/BUG-10 already established) - a
          partial refund after completion is recorded as an
          informational event only, never a new production delta (a
          refund is a reduction, never new work to prepare).
        """
        for line in self.lines.filtered(
                lambda l: l.product_id.type in ('consu', 'product', 'service')):
            if 'refunded_orderline_id' not in line._fields:
                continue
            original_pos_line = line.refunded_orderline_id
            if not original_pos_line:
                continue
            kline = self.env['kds.order.line'].search([
                ('pos_order_line_id', '=', original_pos_line.id),
                ('state', '!=', 'cancelled'),
            ], limit=1, order='id desc')
            if not kline:
                continue
            all_refund_lines = self.env['pos.order.line'].search([
                ('refunded_orderline_id', '=', original_pos_line.id),
            ])
            cumulative_refunded = sum(abs(l.qty) for l in all_refund_lines)
            effective_qty = original_pos_line.qty - cumulative_refunded
            kds_order = kline.order_id

            if effective_qty <= 0:
                if kline.state == 'completed':
                    self.env['kds.event'].log(
                        kds_order, event_type='order_updated', station=kline.station_id,
                        note=_("%(product)s fully refunded after original line was already "
                               "completed - informational only, no production change")
                        % {'product': kline.product_name})
                else:
                    kline.action_cancel(
                        reason=_('Fully refunded in POS (refund order %s)') % (self.pos_reference or self.name),
                        bypass_check=True)
            elif effective_qty < kline.qty:
                if kline.state == 'completed':
                    self.env['kds.event'].log(
                        kds_order, event_type='order_updated', station=kline.station_id,
                        note=_("%(product)s partially refunded after original line was already "
                               "completed (qty %(old_qty)s -> %(new_qty)s) - informational only, "
                               "no production change")
                        % {'product': kline.product_name, 'old_qty': kline.qty, 'new_qty': effective_qty})
                else:
                    # REAL BUG FIX ("BUG-11 [fourth report] - Sequential
                    # qty_delta baseline is still wrong at runtime"):
                    # baseline is explicitly last_kds_sent_qty, not
                    # kline.qty - see that field's own docstring
                    # (kds_order_line.py) for the full explanation.
                    qty_decrease = effective_qty - kline.last_kds_sent_qty
                    old_qty = kline.qty
                    kline.write({
                        'qty': effective_qty,
                        'line_change': 'updated',
                        'qty_delta': qty_decrease,
                        'last_kds_sent_qty': effective_qty,
                    })
                    self.env['kds.event'].log(
                        kds_order, event_type='order_updated', station=kline.station_id,
                        note=_("%(product)s reduced by refund (qty %(old_qty)s -> "
                               "%(new_qty)s, refund order %(ref)s)")
                        % {'product': kline.product_name, 'old_qty': old_qty,
                           'new_qty': effective_qty, 'ref': self.pos_reference or self.name})
                    from .kds_notify import notify_station
                    notify_station(self.env, kline.station_id)
            # effective_qty >= kline.qty: nothing to reconcile (e.g. this
            # specific refund line/order was already fully accounted for
            # by an earlier pass - idempotent no-op).

    def _flexsys_kds_sync(self, is_send_write=False):
        self.ensure_one()
        self = self.sudo()
        # CRITICAL FIX (BUG-06, see _flexsys_kds_is_refund_order()'s own
        # docstring): checked first, before the send-trigger gate below
        # - a refund order must never reach _flexsys_kds_create()/
        # _flexsys_kds_diff_lines() under any trigger configuration.
        #
        # BUG-11 FIX ("Paid Order Refund Is Not Synchronized Back to the
        # Original KDS Ticket"), confirmed live: BUG-06 correctly stopped
        # a refund from creating its OWN new ticket, but stopped there -
        # the ORIGINAL ticket was never told anything had changed, so it
        # kept showing the full, un-refunded quantity indefinitely (a
        # fully-refunded order still showed "PREPARING" with an active
        # READY button - "operationally dangerous," per the report's own
        # words). _flexsys_kds_reconcile_refund() below closes that gap:
        # correlates the refund back to the ORIGINAL kds.order.line and
        # reduces/cancels it accordingly - never creating a second ticket
        # of its own, exactly the same "identify at the authoritative
        # ingestion point" principle BUG-06 already established.
        if self._flexsys_kds_is_refund_order():
            self._flexsys_kds_reconcile_refund()
            return
        # CHANGE REQUEST FIX ("POS Send-to-KDS Settings - Simplify and
        # Correct Triggers"), confirmed live: 'validation'/'submit' used
        # to trigger sync on ANY write touching 'lines'/'state' - which
        # is every edit at all (add/remove a product, change a qty,
        # simply re-saving the order) - "Adding products... Removing
        # products... Changing quantities... must NOT automatically
        # synchronize the order with KDS. The synchronization boundary
        # must be the cashier's explicit action: Send or New."
        #
        # 'send' mode now requires is_send_write=True - set by write()/
        # create() above only when the vals being saved include
        # last_order_preparation_change, Odoo's own core pos.order field
        # (addons/point_of_sale/models/pos_order.py, "Last printed state
        # of the order") that the native Preparation Display's own
        # "Send" action updates - not a new custom button, using the
        # existing/native Odoo POS workflow exactly as required. Every
        # OTHER write (add/remove/qty/attribute changes, simply viewing
        # or re-saving the order) leaves this False, so it correctly
        # accumulates with zero KDS sync until the next genuine Send.
        #
        # Honest caveat, stated plainly rather than guessed past: this
        # field is confirmed, from Odoo 19's own core source, to be
        # updated by the Preparation-Display-enabled "Send" action
        # (Scenario 1). Whether the "New" action also updates this same
        # field when Preparation Display is *disabled* (Scenario 2) has
        # not been confirmed against a live instance - this is the one
        # part of this change that still needs that verification (see
        # RELEASE_STATUS.md). If it turns out "New" doesn't update this
        # field on a given build, orders under that specific
        # configuration would never sync under 'send' mode - a fail-
        # closed gap (nothing reaches the kitchen) rather than fail-open
        # (syncing too early), which is the safer direction for this
        # kind of uncertainty.
        trigger = self.config_id.kds_send_trigger or 'payment'
        if trigger == 'payment':
            ready = self.state in ('paid', 'done', 'invoiced')
        else:
            ready = is_send_write and self.state != 'cancel' and bool(self.lines)
        if not ready:
            return
        if not self.kds_order_id:
            self._flexsys_kds_create()
        else:
            self._flexsys_kds_diff_lines()

    def _flexsys_kds_create(self):
        self.ensure_one()
        order_type = 'take_away' if getattr(self, 'takeaway', False) else 'dine_in'
        kds_order = self.env['kds.order'].create({
            'pos_order_id': self.id,
            'pos_config_id': self.config_id.id,
            'company_id': self.company_id.id,
            'source': 'pos',
            'order_type': order_type,
            'customer_name': self.partner_id.name or self.pos_reference or '',
            'note': _pos_note(self),
        })
        self.kds_order_id = kds_order.id
        self._flexsys_kds_create_lines(self.lines)
        self._flexsys_kds_auto_print(kds_order)
        # REALTIME VALIDATION FIX (dev request, "Realtime Runtime
        # Validation" - "New order" was explicitly listed as one of the
        # scenarios to verify propagates without a manual refresh): this
        # method - the very first time a POS order gets sent to KDS -
        # never notified anyone. Every *later* change to an order (POS
        # Delta sync, workflow transitions, cancellation, reopen) already
        # does, via the shared _wf_transition path or an explicit call
        # at each site (see kds_order.py, kds_order_line.py,
        # kds_expeditor_task.py) - this was the one real gap: the single
        # most common, most important event (a brand new order arriving)
        # was relying entirely on the polling fallback to ever show up,
        # never actually pushed instantly. A brand-new order's lines
        # already have their station_id set by the routing engine inside
        # _flexsys_kds_create_lines (called just above), so this reads
        # that back rather than needing its own separate routing lookup.
        from .kds_notify import notify_stations
        notify_stations(self.env, kds_order.line_ids.mapped('station_id'))

    def _flexsys_kds_create_lines(self, pos_lines):
        line_vals = []
        for line in pos_lines:
            if line.product_id.type not in ('consu', 'product', 'service'):
                continue
            line_vals.append({
                'order_id': self.kds_order_id.id,
                'pos_order_line_id': line.id,
                'product_id': line.product_id.id,
                'qty': line.qty,
                'note': _pos_note(line),
                'variant_info': _pos_line_variant_info(line),
            })
        if line_vals:
            self.env['kds.order.line'].create(line_vals)

    def _flexsys_kds_diff_lines(self):
        """Delta-sync: compare current POS order lines against the
        kds.order.line records already routed to stations, and apply the
        minimal set of changes rather than recreating the ticket.

        - A POS line with no matching kds.order.line yet -> new kds line,
          line_change='added', routed fresh (may go to a station that
          hasn't seen this order at all yet).
        - A POS line whose product changed vs. its kds.order.line -> full
          re-route, not an in-place field update: the new product may
          belong to an entirely different station (e.g. Cappuccino/Coffee
          -> Chicken Burger/Kitchen), so this cancels the old line at its
          old station (or, if that line was already Completed/served,
          leaves that history alone and adds the new product as a fresh
          line instead) and creates a brand-new kds.order.line for the new
          product, which re-runs the routing engine from scratch. Both the
          old and new station get notified, and the new line's own
          auto-print rules apply normally the next time it's printed -
          there is no old print job to "convert", since kds.print.job
          records are an immutable log of what was actually sent to a
          printer, not something to retroactively edit.
        - A POS line whose qty/note changed (but not product) -> update in
          place, line_change='updated'. If it had already been marked
          Ready it is bumped back to New so the station notices.
        - A kds.order.line whose POS line is gone -> cancelled with
          line_change='removed', via the same action_cancel used for a
          manual cancel (so the same audit trail / SLA bookkeeping apply),
          but with bypass_check=True since this is a system-driven sync,
          not an interactive user action.
        """
        self.ensure_one()
        kds_order = self.kds_order_id
        # REAL BUG FIX ("POS Send-to-KDS Settings... redesign the
        # removal sync so it cannot leak early"), confirmed live: any
        # line flagged pending_removal by pos_order_line.py's own
        # unlink() (its POS line was deleted, but nothing about that was
        # made visible yet - see that method's own detailed comment, and
        # kds_order_line.py's pending_removal field docstring, for the
        # full explanation) is processed here, right at the START of
        # this method - the one place that only ever runs at the
        # correct sync boundary for whichever trigger mode is configured
        # (this method is never called except from _flexsys_kds_sync(),
        # which already gated on 'payment' state or the genuine Send/New
        # signal before ever reaching here). Applies the exact same
        # state-aware cancellation the old unlink()-time logic used to
        # apply immediately: a still-active line goes through the real,
        # audited action_cancel(); an already-Completed line uses
        # _system_cancel_after_completion() instead (see that method's
        # own docstring - action_cancel() itself explicitly refuses to
        # cancel a Completed line, correctly, for a real user-facing
        # cancel action, but a POS-driven removal after completion is a
        # different, system-driven scenario where marking it Cancelled
        # is the correct, intended outcome).
        pending_removed = kds_order.line_ids.filtered('pending_removal')
        for kline in pending_removed:
            if kline.state == 'completed':
                kline._system_cancel_after_completion(
                    reason=_('Removed from POS order (was already completed)'))
            elif kline.state != 'cancelled':
                kline.action_cancel(reason=_('Removed from POS order after send'), bypass_check=True)
            else:
                kline.write({'pending_removal': False})
        # Only match against currently-active kds lines: a pos_order_line_id
        # can end up pointing at more than one kds.order.line over time (a
        # product-change reroute cancels the old one and creates a new one
        # sharing the same pos_order_line_id) - the cancelled one is closed
        # history, not something later diffs should match against.
        existing = {}
        for l in kds_order.line_ids:
            if l.pos_order_line_id and l.state != 'cancelled':
                existing[l.pos_order_line_id.id] = l
        current_ids = set()
        new_line_vals = []
        touched_stations = self.env['kds.station']

        for line in self.lines:
            if line.product_id.type not in ('consu', 'product', 'service'):
                continue
            current_ids.add(line.id)
            kline = existing.get(line.id)
            if kline:
                if kline.product_id != line.product_id:
                    touched_stations |= self._flexsys_kds_reroute_line(kds_order, kline, line)
                    continue
                # REAL BUG FIX, confirmed at runtime (dev request
                # "Runtime Regression Fix Package", BUG-04, Case A):
                # a POS line whose qty was set to 0 used to fall through
                # to the generic "changed" branch below exactly like any
                # other qty adjustment, writing qty=0 and
                # line_change='updated' - the kitchen would see
                # "0 x Pasta Bolognese - UPDATED", not a clear signal
                # that the item was effectively removed. Operationally,
                # qty=0 on a previously-submitted item IS a removal - a
                # kitchen operator does not need to distinguish "the
                # customer no longer wants any of this" from "the line
                # was deleted outright" (handled separately, below the
                # main per-line loop, via the exact same action_cancel()
                # call this now shares). Routed through the same
                # authoritative cancellation path as every other
                # cancellation in this module - full audit trail
                # (previous state, timestamp, user, reason), the same
                # CANCELLED display treatment on both KDS screens, the
                # same grace-period retention - not a special-cased
                # silent removal.
                if line.qty <= 0 and kline.state not in ('completed', 'cancelled'):
                    kline.action_cancel(
                        reason=_('Quantity reduced to zero in POS'), bypass_check=True)
                    touched_stations |= kline.station_id
                    continue
                changed = (kline.qty != line.qty) or (kline.note != _pos_note(line)) \
                    or (kline.variant_info != _pos_line_variant_info(line))
                # REAL BUG FIX, confirmed at runtime (dev request
                # "Remaining Fixes After v19.0.7.0.0 Review", item 2):
                # this used to require kline.state not in ('completed',
                # 'cancelled') for ANY modification to be processed at
                # all - meaning a qty/note/variant change on an already-
                # Completed line was silently ignored entirely, not just
                # left un-reset like a Ready line. Scenario A (a brand
                # new product added after Completed) already worked
                # correctly via create()'s own
                # _system_reopen_if_production_incomplete() call;
                # Scenario B (an EXISTING completed line modified) had no
                # equivalent path at all. Fixed using the exact same
                # established pattern _flexsys_kds_reroute_line() already
                # uses for a product change on a completed line just
                # below - the original completed kline is never mutated
                # (preserves "previous completion, previous timestamps"
                # exactly as required), a brand-new kds.order.line is
                # created carrying the SAME pos_order_line_id (so it
                # correctly takes over as what future diffs match against
                # - the `existing` dict at the top of this method already
                # keys on pos_order_line_id, last-write-wins, same as the
                # reroute case relies on), and
                # _system_reopen_if_production_incomplete() (called via
                # the new line's own create()) reopens the order to
                # 'preparing' - "the reopened preparation represents new
                # work, while the original completed work remains
                # historically auditable."
                # REAL BUG FIX, confirmed at runtime (dev report "BUG-10 -
                # READY order incorrectly resets to NEW after POS
                # quantity increase"): a Ready line whose qty/note/
                # variant changed used to get bumped fully back to 'new'
                # via _system_reset_for_delta_sync() below - destroying
                # the fact that the PREVIOUS quantity had already been
                # prepared. "1 prepared + UPDATED (+1)" incorrectly
                # became "2 new" - the whole line, previously-prepared
                # portion included, looked like it needed a fresh
                # production cycle from scratch, with an active START
                # button, even though only the +1 increase genuinely did.
                #
                # Fixed using the EXACT same established pattern already
                # used for a Completed line's own equivalent case just
                # below (kline.state == 'completed') - unified into one
                # shared branch, since the underlying requirement is
                # identical for both: "the previous prepared/ready
                # quantity stays preserved as completed/ready production
                # history... only the new delta needs a new production
                # cycle... must not lose or reset previous production
                # history." The original Ready line is never mutated -
                # keeps its own state, qty, ready_time, exactly as
                # before - and a brand-new delta line is created instead,
                # carrying the SAME pos_order_line_id so it correctly
                # takes over as what future diffs match against.
                #
                # REAL BUG FIX (found while fixing this, checking the
                # already-existing Completed-line branch below for the
                # same underlying issue - "make sure old tests are still
                # LOGICALLY correct, not just passing"): that branch's
                # own delta line used to carry qty=line.qty (the FULL NEW
                # POS total, e.g. 7 for a 5->7 change), not qty=2 (just
                # the increase) - silently double-counting the 5 already-
                # completed units against the new delta's own full 7,
                # exactly the "2 new" mistake this same dev report is
                # pointing at, just for Completed instead of Ready. Fixed
                # for both at once, consistently, below.
                if changed and kline.state in ('ready', 'completed'):
                    # REAL BUG FIX ("BUG-11 [fourth report] - Sequential
                    # qty_delta baseline is still wrong at runtime"):
                    # baseline is explicitly last_kds_sent_qty here too,
                    # for full consistency with the generic update branch
                    # further below - see that field's own docstring
                    # (kds_order_line.py) for the complete explanation.
                    qty_increment = line.qty - kline.last_kds_sent_qty
                    if qty_increment <= 0 and kline.qty != line.qty:
                        # REAL BUG FIX ("Change Request After BUG-11",
                        # item 2: "Quantity Decrease Delta - Display
                        # Negative Difference"), confirmed live: this
                        # used to ALWAYS just log-and-skip a decrease on
                        # a Ready/Completed line, for BOTH states alike -
                        # correct for Completed ("the original completed
                        # work remains historically completed", never
                        # rewritten), but wrong for Ready: a genuine POS
                        # quantity decrease on a Ready line never
                        # actually reduced the line's own displayed
                        # quantity at all, and no delta/UPDATED(-N)
                        # showed - "quantity decreases currently display
                        # only: UPDATED" (no negative delta), because the
                        # line was left completely untouched rather than
                        # having its own qty reduced the way an active
                        # line's decrease already correctly does.
                        #
                        # Fixed by splitting the two states: Completed
                        # keeps the original informational-only, never-
                        # mutate-history behavior; Ready now reduces the
                        # qty in place - matching "do not reopen
                        # unnecessary production" (no delta line, no
                        # state change, no reset to New - just the
                        # quantity itself moving down) while still
                        # correctly showing UPDATED (-N) via the same
                        # qty_delta mechanism BUG-09 already established
                        # for every other quantity change.
                        if kline.state == 'completed':
                            self.env['kds.event'].log(
                                kds_order, event_type='order_updated', station=kline.station_id,
                                note=_("%(product)s reduced after original line was already "
                                       "completed (qty %(old_qty)s -> %(new_qty)s) - no new "
                                       "preparation delta created, completed history preserved")
                                % {'product': kline.product_name,
                                   'old_qty': kline.qty, 'new_qty': line.qty})
                        else:
                            old_qty = kline.qty
                            kline.write({
                                'qty': line.qty,
                                'note': _pos_note(line),
                                'variant_info': _pos_line_variant_info(line),
                                'line_change': 'updated',
                                # REAL BUG FIX ("BUG-11 [third report,
                                # then confirmed still reproducing in a
                                # fourth report] - Sequential Quantity
                                # Delta Uses Wrong Baseline"): see the
                                # generic update branch further below,
                                # and last_kds_sent_qty's own docstring
                                # (kds_order_line.py), for the complete
                                # explanation - qty_increment here is
                                # already this sync's own fresh delta
                                # against the explicit baseline field,
                                # never accumulated on top of a prior
                                # one, and that same baseline field is
                                # updated in this exact same write.
                                'qty_delta': qty_increment,
                                'last_kds_sent_qty': line.qty,
                            })
                            touched_stations |= kline.station_id
                            self.env['kds.event'].log(
                                kds_order, event_type='order_updated', station=kline.station_id,
                                note=_("%(product)s reduced after original line was already "
                                       "ready (qty %(old_qty)s -> %(new_qty)s) - quantity "
                                       "reduced in place, no production reopened")
                                % {'product': kline.product_name,
                                   'old_qty': old_qty, 'new_qty': line.qty})
                            from .kds_notify import notify_station
                            notify_station(self.env, kline.station_id)
                        continue
                    # Quantity genuinely increased: the delta line
                    # represents ONLY the increase (qty_increment), not
                    # the new full total - "1 prepared + 1 needed" stays
                    # visible as two separate, honest quantities, never
                    # silently inflating to "2 new". A note/variant-only
                    # change with qty unchanged (qty_increment == 0, but
                    # `changed` is still True) has no sensible partial-
                    # delta concept - the customer wants the *entire*
                    # already-prepared/ready batch reconfigured to the
                    # new spec, not just some of it, so the delta line
                    # carries the full current quantity in that specific
                    # sub-case only.
                    delta_qty = qty_increment if qty_increment > 0 else line.qty
                    self.env['kds.event'].log(
                        kds_order, event_type='order_updated', station=kline.station_id,
                        note=_("%(product)s modified after original line was already "
                               "%(state)s (qty %(old_qty)s -> %(new_qty)s) - added as a new "
                               "delta line instead of rewriting existing production history")
                        % {'product': kline.product_name, 'state': kline.state,
                           'old_qty': kline.qty, 'new_qty': line.qty})
                    new_delta_line = self.env['kds.order.line'].create({
                        'order_id': kds_order.id,
                        'pos_order_line_id': line.id,
                        'product_id': line.product_id.id,
                        'qty': delta_qty,
                        'note': _pos_note(line),
                        'variant_info': _pos_line_variant_info(line),
                        'line_change': 'updated',
                    })
                    touched_stations |= kline.station_id | new_delta_line.station_id
                    self.env['kds.event'].log(
                        kds_order, event_type='order_updated', station=new_delta_line.station_id,
                        note=_("New preparation revision for %(product)s after %(state)s "
                               "original (delta qty %(qty)s)")
                        % {'product': new_delta_line.product_name, 'state': kline.state,
                           'qty': delta_qty})
                elif changed and kline.state != 'cancelled':
                    # AUDIT FIX ("POS Delta Sync Still Bypasses The
                    # Central Workflow", HIGH/FINAL BLOCKER): the plain
                    # data fields below (qty/note/variant/line_change)
                    # are legitimate direct writes - they're not in
                    # KDS_LINE_PROTECTED_FIELDS and never were the
                    # problem. Only the STATE reset (a Ready line bumped
                    # back to New) is workflow-significant - that part
                    # now goes through _system_reset_for_delta_sync()
                    # instead of being bundled into this same raw write.
                    #
                    # REAL BUG FIX ("BUG-11 [third report, reusing the
                    # same client-side label as two earlier, different
                    # issues] - Sequential Quantity Delta Uses Wrong
                    # Baseline"), confirmed live: this used to accumulate
                    # qty_delta on top of whatever it already was
                    # (kline.qty_delta + this sync's own increment) -
                    # BUG-09's own original reasoning was that the
                    # kitchen should see the total change "since the
                    # previously ACKNOWLEDGED quantity", assuming that
                    # meant summing every unacknowledged sync's own delta
                    # together. That reasoning was wrong, and this report
                    # gives the precise counter-example: 2 -> 1
                    # (correctly UPDATED (-1)), then - with no
                    # acknowledgement in between - 1 -> 3 accumulated to
                    # UPDATED (+1) (-1 + 2), when the kitchen needed to
                    # see UPDATED (+2) - the change relative to the 1
                    # they were already shown, not some blend with a
                    # decrease that sync had already fully superseded.
                    # "Delta must always be calculated against the last
                    # successfully sent KDS quantity" - which is exactly
                    # what kline.qty already *is*, right before this
                    # write updates it again - qty_increment below (=
                    # effective_qty - kline.qty, i.e. new value minus the
                    # line's own current value) is already precisely
                    # that delta on its own, with no addition needed.
                    # Repeated changes before any acknowledgement now
                    # each independently show only their own most recent
                    # move (2->1 shows -1; then 1->3 shows +2; then 3->2
                    # would show -1) rather than an ever-growing blended
                    # total - matching this report's own worked example
                    # exactly, including its final "3 -> 2 = UPDATED
                    # (-1)" step.
                    #
                    # REAL BUG FIX (found while fixing "BUG-10 - READY
                    # order incorrectly resets to NEW after POS quantity
                    # increase", checking this branch for the same class
                    # of mistake per "make sure old tests are still
                    # LOGICALLY correct, not just passing"): kline
                    # reaching this branch might itself BE a delta line
                    # created by the new ready/completed branch above (on
                    # an EARLIER sync) - the `existing` dict at the top of
                    # this method keys purely on pos_order_line_id, so a
                    # delta line correctly takes over as what THIS sync
                    # matches against too, exactly as intended. But
                    # writing `line.qty` (the POS line's own full current
                    # total) directly into a delta line's own qty would
                    # silently lose the distinction the first sync
                    # deliberately created - e.g. 5 completed + delta of
                    # 2 (total POS qty 7), then POS changes to 10: without
                    # this fix, the delta line's own qty would jump to 10
                    # (the full new total) while the original completed
                    # line still separately shows 5 - implying 15 total
                    # when the real total is 10. Any historical (Ready/
                    # Completed) sibling line for the SAME pos_order_line_id
                    # is subtracted out first, so this line's own qty
                    # always represents only ITS OWN remaining share of
                    # the current total, matching the exact same "delta,
                    # not full total" principle applied above.
                    historical_siblings = kds_order.line_ids.filtered(
                        lambda l, pid=line.id, kid=kline.id: l.pos_order_line_id.id == pid
                        and l.id != kid and l.state in ('ready', 'completed'))
                    effective_qty = line.qty - sum(historical_siblings.mapped('qty'))
                    # REAL BUG FIX ("BUG-11 [fourth report] - Sequential
                    # qty_delta baseline is still wrong at runtime"),
                    # confirmed STILL reproducing live even after the
                    # v7.7.3 fix that stopped accumulating qty_delta -
                    # this is the exact branch handling the report's own
                    # reproduction scenario (a 'preparing' line, the
                    # single most common case). v7.7.3's own fix used
                    # kline.qty itself as the implicit baseline
                    # (mathematically equivalent to what's required, in
                    # theory) - but the dev report explicitly asked to
                    # "verify which field/value is actually being used
                    # as the authoritative 'last sent quantity'" rather
                    # than trust that equivalence blindly. Switched to
                    # the explicit, dedicated last_kds_sent_qty field
                    # (kds_order_line.py - see its own docstring for the
                    # full contract) instead of kline.qty, and that same
                    # field is updated to the new value in this exact
                    # same write() call, immediately after being read -
                    # eliminating any possibility of a stale read
                    # between computing this sync's own delta and
                    # recording what the next sync's own baseline should
                    # be. Required acceptance sequence from the dev
                    # report's own worked example, now correct: 2->1 =
                    # -1, then 1->3 = +2 (not +1), then 3->2 = -1.
                    qty_increment = effective_qty - kline.last_kds_sent_qty
                    kline.write({
                        'qty': effective_qty,
                        'note': _pos_note(line),
                        'variant_info': _pos_line_variant_info(line),
                        'line_change': 'updated',
                        'qty_delta': qty_increment,
                        'last_kds_sent_qty': effective_qty,
                    })
                    touched_stations |= kline.station_id
                    self.env['kds.event'].log(
                        kds_order, event_type='order_updated', station=kline.station_id,
                        note=_("%s updated (qty/notes changed after send)") % line.product_id.display_name)
            else:
                new_line_vals.append({
                    'order_id': kds_order.id,
                    'pos_order_line_id': line.id,
                    'product_id': line.product_id.id,
                    'qty': line.qty,
                    'note': _pos_note(line),
                    'variant_info': _pos_line_variant_info(line),
                    'line_change': 'added',
                })

        if new_line_vals:
            new_lines = self.env['kds.order.line'].create(new_line_vals)
            touched_stations |= new_lines.mapped('station_id')
            for kline in new_lines:
                self.env['kds.event'].log(
                    kds_order, event_type='line_added', station=kline.station_id,
                    note=_("%s added after order was sent") % kline.product_name)

        for pos_line_id, kline in existing.items():
            if pos_line_id not in current_ids and kline.state not in ('cancelled', 'completed'):
                kline.action_cancel(reason=_('Removed from POS order after send'), bypass_check=True)
                touched_stations |= kline.station_id
            # REAL BUG FIX ("Change Request After BUG-11", item 1),
            # confirmed live: a POS line deleted after its KDS line had
            # already reached 'completed' used to fall through this
            # entire block untouched (action_cancel() above is only
            # reachable for a NOT-yet-completed line) - the deleted
            # product stayed displayed as if normally completed forever.
            # Routed through the dedicated _system_cancel_after_completion()
            # instead - see that method's own docstring in
            # kds_order_line.py for the full explanation of why this
            # needs a separate path from the normal action_cancel().
            elif pos_line_id not in current_ids and kline.state == 'completed':
                kline._system_cancel_after_completion(
                    reason=_('Removed from POS order after the order was already completed'))
                touched_stations |= kline.station_id

        # AUDIT FIX ("POS Delta Sync Still Bypasses The Central
        # Workflow", HIGH/FINAL BLOCKER): replaces the previous raw
        # `kds_order.write({'state': 'preparing'})`. Called
        # unconditionally - _system_reopen_if_production_incomplete()'s
        # own internal check is a cheap no-op unless the order is
        # actually sitting at Ready/Completed with production no longer
        # fully ready, so no need to replicate that condition here too.
        kds_order._system_reopen_if_production_incomplete(
            reason=_('POS order %s modified after send') % (self.pos_reference or self.name))

        from .kds_notify import notify_stations
        notify_stations(self.env, touched_stations)

    def _flexsys_kds_reroute_line(self, kds_order, kline, pos_line):
        """Handle a POS line whose product_id changed after the ticket was
        already routed: this is not a field update, it's potentially a
        move to a completely different station, so it goes through
        cancel-old + create-new (which re-runs the routing engine) rather
        than mutating kline.product_id in place. Returns the set of
        stations that need a realtime refresh (old + new)."""
        old_station = kline.station_id
        if kline.state == 'completed':
            # Already served under the old product - don't rewrite served
            # history, just log the swap and add the new product as a
            # fresh line so the correct (possibly different) station sees
            # it as a new item to prepare.
            self.env['kds.event'].log(
                kds_order, event_type='order_updated', station=old_station,
                note=_("Product changed after original line was already completed "
                       "(%(old)s -> %(new)s) - added as a new line instead of rewriting history")
                % {'old': kline.product_name, 'new': pos_line.product_id.display_name})
        else:
            kline.action_cancel(
                reason=_('Product changed on POS line (re-routing)'), bypass_check=True)

        new_line = self.env['kds.order.line'].create({
            'order_id': kds_order.id,
            'pos_order_line_id': pos_line.id,
            'product_id': pos_line.product_id.id,
            'qty': pos_line.qty,
            'note': _pos_note(pos_line),
            'variant_info': _pos_line_variant_info(pos_line),
            'line_change': 'updated',
        })
        self.env['kds.event'].log(
            kds_order, event_type='order_updated', station=new_line.station_id,
            note=_("Product changed on line: now routed %(product)s -> %(station)s")
            % {'product': new_line.product_name,
               'station': new_line.station_id.name if new_line.station_id else _('UNROUTED')})
        return old_station | new_line.station_id

    def _flexsys_kds_auto_print(self, kds_order):
        for station in kds_order.station_ids:
            if not station.auto_print:
                continue
            # AUDIT FIX ("Auto Print Without a Valid Printer", MEDIUM):
            # this used to build printer_id from
            # `station.printer_ids.filtered('is_default')[:1] or
            # station.printer_ids[:1]` and pass it straight into create()
            # without checking whether either search actually found
            # anything - a station with Auto Print enabled but zero
            # printers configured got `printer_id: False` (an empty
            # recordset's .id), silently creating a permanently
            # unexecutable pending job that would sit in the queue
            # forever with no alert to anyone. Now explicitly checks
            # first and logs a clear configuration-error audit event
            # instead of creating the broken job.
            printer = station.printer_ids.filtered('is_default')[:1] or station.printer_ids[:1]
            if not printer:
                self.env['kds.event'].log(
                    kds_order, event_type='override', station=station,
                    note=_("CONFIGURATION ERROR: Auto Print is enabled for station "
                           "'%s' but it has no printer configured - no print job "
                           "was created. Add a printer to this station or disable "
                           "Auto Print.") % station.name
                )
                continue
            self.env['kds.print.job'].create({
                'order_id': kds_order.id,
                'station_id': station.id,
                'printer_id': printer.id,
                'job_type': 'auto',
                'scope': 'station_items',
            })
