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
        for order in orders:
            order._flexsys_kds_sync()
        return orders

    def write(self, vals):
        res = super().write(vals)
        if 'state' in vals or 'lines' in vals:
            for order in self:
                order = order.sudo()
                if vals.get('state') == 'cancel':
                    order._flexsys_kds_cancel()
                else:
                    order._flexsys_kds_sync()
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

    def _flexsys_kds_sync(self):
        self.ensure_one()
        self = self.sudo()
        # CRITICAL FIX (BUG-06, see _flexsys_kds_is_refund_order()'s own
        # docstring): checked first, before the send-trigger gate below
        # - a refund order must never reach _flexsys_kds_create()/
        # _flexsys_kds_diff_lines() under any trigger configuration.
        if self._flexsys_kds_is_refund_order():
            return
        # AUDIT FIX ("POS -> KDS Send Trigger", HIGH): gate now reads
        # config_id.kds_send_trigger (pos_config.py) instead of a fixed
        # `state in ('paid', 'done', 'invoiced')` check - see that
        # field's own help text for exactly what each option means and
        # the honest caveat on 'validation' vs 'submit'. Falls back to
        # the original 'payment' behavior if the field is somehow unset,
        # so this can never become MORE permissive than before by
        # accident.
        trigger = self.config_id.kds_send_trigger or 'payment'
        if trigger == 'payment':
            ready = self.state in ('paid', 'done', 'invoiced')
        else:
            # 'validation' / 'submit': a real, non-cancelled order with
            # actual lines is considered ready to reach the kitchen,
            # independent of payment status - satisfies "Dine-In orders
            # should be able to reach Kitchen before payment when
            # configured".
            ready = self.state != 'cancel' and bool(self.lines)
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
                if changed and kline.state == 'completed':
                    if line.qty <= 0:
                        # Edge case: qty reduced to zero on an ALREADY-
                        # completed line - unlike the active-line case
                        # above (which cancels), there is no new
                        # preparation work to create a delta line FOR (a
                        # 0-qty delta line would need preparing nothing,
                        # which makes no operational sense) - just note
                        # it and leave the original completed history
                        # exactly as it was, matching "the original
                        # completed work remains historically auditable."
                        self.env['kds.event'].log(
                            kds_order, event_type='order_updated', station=kline.station_id,
                            note=_("%s reduced to zero after original line was already completed "
                                   "- no new preparation delta created, completed history preserved")
                            % kline.product_name)
                        continue
                    self.env['kds.event'].log(
                        kds_order, event_type='order_updated', station=kline.station_id,
                        note=_("%(product)s modified after original line was already completed "
                               "(qty %(old_qty)s -> %(new_qty)s) - added as a new line instead of "
                               "rewriting completed history")
                        % {'product': kline.product_name, 'old_qty': kline.qty, 'new_qty': line.qty})
                    new_delta_line = self.env['kds.order.line'].create({
                        'order_id': kds_order.id,
                        'pos_order_line_id': line.id,
                        'product_id': line.product_id.id,
                        'qty': line.qty,
                        'note': _pos_note(line),
                        'variant_info': _pos_line_variant_info(line),
                        'line_change': 'updated',
                    })
                    touched_stations |= kline.station_id | new_delta_line.station_id
                    self.env['kds.event'].log(
                        kds_order, event_type='order_updated', station=new_delta_line.station_id,
                        note=_("New preparation revision for %(product)s after completed original "
                               "(qty %(qty)s)") % {'product': new_delta_line.product_name, 'qty': line.qty})
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
                    kline.write({
                        'qty': line.qty,
                        'note': _pos_note(line),
                        'variant_info': _pos_line_variant_info(line),
                        'line_change': 'updated',
                    })
                    if kline.state == 'ready':
                        kline._system_reset_for_delta_sync('new')
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
