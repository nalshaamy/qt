/** @odoo-module **/

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { patch } from "@web/core/utils/patch";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";

/*
 * Port of static/src/overrides/components/payment_screen/payment_screen.js.
 *
 * The payload assembly is carried over verbatim, because Bonat's
 * /odoo_partner/order contract depends on its exact shape. The order-creation
 * transport call changed:
 *
 *   orm.call("pos.session", "pos_order_creation_request") -> pos.bonatApi.orderCreated()
 *
 * BON-2568: redemption (orm.call("pos.session", "pos_reward_redeem") ->
 * pos.bonatApi.redeem()) no longer happens here. It moved to
 * promo_code_button.js, at the moment a code/voucher is confirmed in the "Use
 * Bonat Coupon" popup — the instant the reward lands on the order, not at
 * order closure. By the time validateOrder() runs, any applied Bonat
 * code/voucher has already been redeemed server-side; there is no
 * redeem-then-validate step left to halt on here.
 *
 * BON-1836 — voucher payment-line enforcement (ADR 0002, docs/adr/0002-odoo19-voucher-payment-parity.md).
 *
 * Mirrors odoo17's checkout-time-only _syncBonatVoucherPaymentLine /
 * _getBonatVoucherMethod pattern (odoo 17/.../payment_screen.js, post BON-1677/
 * BON-1800), adapted to this build's own APIs and platform constraint: no
 * server-side pos.payment.method record can be created here, so the merchant
 * manually creates one under Point of Sale > Payment Methods and links it via
 * the x_bonat_voucher_payment_method_id manual field (bonat_store.js caches its
 * id on pos.bonat.voucherPaymentMethodId at startup). odoo17 also has a
 * server-computed bonat_voucher_hidden_payment_method_ids Many2many (would
 * require Python — cannot exist here); this build only ever has the single
 * resolved method to hide, so _getBonatVoucherMethod() is compared directly at
 * each call site instead of carrying a same-purpose hidden-ids wrapper
 * (Challenge X1 on PR #81 round 1).
 *
 * Enforcement is opt-in and MUST fail open: unless a voucher payment method is
 * configured AND actually linked to this POS config's payment_method_ids,
 * _getBonatVoucherMethod() resolves undefined and every method below is a
 * no-op — a redeemed voucher stays banner-only, exactly as documented in the
 * settings help text and CHANGELOG. Odoo 17/self-hosted 19.0 can guarantee the
 * method always exists (seeded on install, auto-linked on every pos.config
 * create/write, backfilled by migration) so "unresolved" is a genuine anomaly
 * there; this build can do none of the three, so unresolved is the default for
 * every merchant until they opt in by hand. Never let an unresolved method
 * block Validate (Challenge F1 on PR #81 round 1) — that would turn every
 * un-configured voucher order into a dead checkout on the one build that
 * carries live production footprint (BON-1683).
 *
 * API differences from odoo17/18's old-API pattern, all confirmed live against
 * production-odoo19's core (`point_of_sale/static/src/app/...`), which the
 * README documents as the same modern API this Online build targets:
 *   order.get_paymentlines()      -> order.payment_ids
 *   order.add_paymentline(method) -> order.addPaymentline(method) -> {status, data}
 *   order.remove_paymentline(l)   -> order.removePaymentline(l)
 *   order.get_due()               -> order.remainingDue (getter, rounding-aware)
 *   line.set_amount(n)/get_amount()-> line.setAmount(n)/getAmount()
 *   line.payment_method            -> line.payment_method_id
 *   this.pos.get_order()          -> this.pos.getOrder()
 * Core's own single-configured-method auto-add lives inside onMounted() itself
 * (`if (payment_methods_from_config.length == 1 && paymentLines.length == 0)
 * this.addNewPaymentLine(...)`) — the paymentLines.length == 0 guard means
 * Odoo 19 behaves like odoo18 here, not odoo17 (odoo17 has no such guard), so
 * once the voucher sync attaches its line first, a sole configured method
 * never auto-adds on this major either (not a money defect, just a behavioral
 * note — Challenge F2 on PR #81 round 1). onMounted() is registered via
 * `onMounted(this.onMounted)` in setup() — so, exactly like BON-1677's E1 fix,
 * the sync must run inside an overridden onMounted() and be awaited BEFORE
 * calling super.onMounted(), not from a second separately-registered onMounted
 * callback, or core's auto-add can claim the full remaining due on a
 * single-method config before the voucher sync gets a turn. The await is
 * wrapped in try/finally (Challenge F2 on PR #81 round 1, matching PR #82's
 * fix to the same shape on odoo17/18): a rejection inside the sync must never
 * skip core's own onMounted logic (the auto-add above, plus an orphan-payment
 * purge loop) on every payment-screen mount, voucher or not.
 *
 * remainingDue is NOT a linear function of amountPaid: it clamps to 0 once
 * the order is fully/over-paid and applies currency rounding
 * (pos_order_accounting.js on the pod). _syncBonatVoucherPaymentLine zeroes an
 * existing voucher line before re-reading remainingDue for exactly this
 * reason — an analytic "add the old amount back" is not a valid inverse of
 * that clamp and overshoots the cap on an over-tender (Challenge N1 on PR #81
 * round 2). A manual delete of the voucher line does NOT unblock Validate
 * (Challenge N2 on PR #81 round 2, correcting round 1's F4 fix) — the voucher
 * is already redeemed server-side, so validating with no line covering it
 * would charge the customer in full for it a second time (BON-971); the
 * sticky flag only suppresses automatic re-add, never the money guard.
 */
patch(PaymentScreen.prototype, {
    setup() {
        super.setup(...arguments);
        // Computed once here, not per call: this.pos.config cannot change during
        // a Payment screen's lifetime, and this Set would otherwise be rebuilt on
        // every numpad keystroke (updateSelectedPaymentline is wired to
        // triggerAtInput) — classic 19's Challenge X2.
        this._bonatVoucherHiddenIds = this._computeBonatVoucherHiddenMethodIds();
        // Filter every hidden Bonat voucher method out of the clickable payment
        // button list — the whole hidden set (classic parity: a stale duplicate
        // still linked to this config stays hidden even when the selection field
        // is unset or points elsewhere), not just the resolved method;
        // _syncBonatVoucherPaymentLine adds the resolved one programmatically at
        // checkout time. payment_methods_from_config is a plain instance
        // property assigned once in core's setup(), not a getter, so filtering
        // it here is enough — every later read (including core's own onMounted
        // single-method auto-add) sees the filtered list.
        const filtered = this.payment_methods_from_config.filter(
            (pm) => !this._bonatVoucherHiddenIds.has(pm.id)
        );
        // Never filter down to zero buttons (classic 19's Challenge F6): a
        // config whose only linked payment method is the (hidden) Bonat voucher
        // would otherwise leave the list empty, and core's
        // updateSelectedPaymentline does
        // `addPaymentline(this.payment_methods_from_config[0])` whenever every
        // payment line is paid — including the vacuous zero-lines case — so
        // `addPaymentline(undefined)` crashes. Showing the voucher button in
        // that one degenerate misconfiguration is safer than a hard crash with
        // zero payment buttons on screen.
        this.payment_methods_from_config = filtered.length
            ? filtered
            : this.payment_methods_from_config;
    },

    _computeBonatVoucherHiddenMethodIds() {
        // Online counterpart of classic 19's server-computed
        // pos.config.bonat_voucher_hidden_payment_method_ids: the
        // merchant-selected method plus any other Bonat-voucher-shaped record
        // still linked to this config (the seeded record from
        // data/pos_bonat_payment.xml left from before the selection field was
        // populated, or a stale duplicate — BON-930). An importable module
        // cannot ship a computed field, so the same set is derived here,
        // client-side, from this config's own payment_method_ids records:
        // name-match against the selected method's name when one resolves, else
        // against the seeded record's name — the same candidate resolution
        // classic's _bonat_voucher_candidate_payment_methods() performs
        // server-side. Used only to hide/lock; never to decide which line a
        // redeemed voucher attaches to (that path is _getBonatVoucherMethod
        // only).
        const hidden = new Set();
        const configMethods = this.pos.config.payment_method_ids || [];
        const selected = this._getBonatVoucherMethod();
        if (selected) {
            hidden.add(selected.id);
        }
        const seedName = (selected && selected.name) || "Bonat_Voucher";
        for (const pm of configMethods) {
            if (pm.name === seedName) {
                hidden.add(pm.id);
            }
        }
        return hidden;
    },

    async onMounted() {
        try {
            await this._syncBonatVoucherPaymentLine();
        } finally {
            super.onMounted();
        }
    },

    _getBonatVoucherMethod() {
        const methodId = this.pos.bonat?.voucherPaymentMethodId;
        if (!methodId) {
            return undefined;
        }
        // Resolved from this config's own linked methods, not the company-wide
        // list — matches loadBonatVoucherPaymentMethod()'s own linkage check.
        return (this.pos.config.payment_method_ids || []).find((pm) => pm.id === methodId);
    },

    _orderHasUnresolvedBonatVoucher(order) {
        // Checked at the money moment (validateOrder), before anything else in
        // this override runs. Unlike before BON-2568, the voucher IS already
        // redeemed server-side by the time this guard fires: promo_code_button.js
        // now calls bonatApi.redeem() itself, at the moment the Voucher code is
        // confirmed in the popup, well before the order ever reaches this
        // screen. A block here means the payment line covering an
        // already-consumed voucher is missing or incomplete — fixing the
        // payment-method configuration (or reloading, for the manual-delete
        // case) and re-validating recovers the payment, not the redemption.
        //
        // Refund orders are exempt (classic BON-1835 Challenge F5, ported for
        // behavior parity): remainingDue is negative there, so a synced voucher
        // line would permanently clamp to $0 and this guard would block
        // Validate with no way for the cashier to free up room. Bonat vouchers
        // are a sale-time redemption mechanic; this build doesn't attempt to
        // enforce them on a refund order at all. Scan time already declines
        // vouchers on refund orders (promo_code_button.js), so this exemption
        // is the backstop, not the primary defense.
        if (order.isRefund) {
            return false;
        }
        // With no voucher method configured (or one that isn't actually
        // usable), there is no payment line to check for. Scan time already
        // declines voucher codes in that state (promo_code_button.js, classic
        // Challenge B2 parity), so this branch is reachable only when the
        // configuration was torn down mid-order — nothing to enforce then.
        const voucherMethod = this._getBonatVoucherMethod();
        if (!voucherMethod) {
            return false;
        }
        // A manual delete of the voucher line (sticky flag, set in
        // deletePaymentLine below) does NOT unblock Validate (Challenge N2 on
        // PR #81 round 2, correcting round 1's F4 fix): letting checkout
        // proceed with no line covering a recorded voucher would charge the
        // customer in full for it a second time — the voucher was already
        // redeemed server-side when the code was confirmed in the popup
        // (BON-2568), not at Validate (BON-971) — this build must not diverge
        // from odoo17/18/self-hosted-19.0 on that. The sticky flag's only job
        // is suppressing automatic re-add in _syncBonatVoucherPaymentLine; it
        // was never an exit from this guard. Falls through to the same "no
        // line" branch below, and validateOrder gives it its own, honest
        // dialog copy.
        const method = order.get_bonat_voucher_method ? order.get_bonat_voucher_method() : "";
        if (method !== "Voucher") {
            return false;
        }
        const amount = order.get_bonat_voucher_amount ? order.get_bonat_voucher_amount() : 0;
        if (!(amount > 0)) {
            return false;
        }

        const paymentlines = order.payment_ids || [];
        const voucherLine = paymentlines.find(
            (p) => p.payment_method_id && p.payment_method_id.id === voucherMethod.id
        );
        if (!voucherLine) {
            return true;
        }
        const lineAmount = voucherLine.getAmount ? voucherLine.getAmount() : 0;
        return !(lineAmount > 0);
    },

    async _syncBonatVoucherPaymentLine() {
        const order = this.pos.getOrder();
        if (!order) {
            return;
        }

        // Refund orders are exempt (classic 19's BON-1835 Challenge F5, ported
        // for behavior parity) — see the matching guard and comment in
        // _orderHasUnresolvedBonatVoucher above for why.
        if (order.isRefund) {
            return;
        }

        // Sticky: once the cashier explicitly deletes the voucher line via its
        // own delete button, it stays removed for the rest of this order —
        // re-adding it on the next unrelated payment-line event would silently
        // undo that and defeat _orderHasUnresolvedBonatVoucher's guard below.
        if (order._bonatVoucherManuallyRemoved) {
            return;
        }

        const method = this._getBonatVoucherMethod();
        if (!method) {
            return;
        }

        const paymentlines = order.payment_ids || [];
        const matching = paymentlines.filter(
            (p) => p.payment_method_id && p.payment_method_id.id === method.id
        );
        const existingLine = matching[0];
        // Defensive: collapse any duplicate voucher lines down to the one about
        // to be synced.
        for (const dup of matching.slice(1)) {
            order.removePaymentline(dup);
        }

        const hasVoucher = !!(
            order.get_bonat_voucher_method && order.get_bonat_voucher_method() === "Voucher"
        );
        const voucherAmount =
            hasVoucher && order.get_bonat_voucher_amount ? order.get_bonat_voucher_amount() : 0;

        if (!hasVoucher || voucherAmount <= 0) {
            if (existingLine) {
                order.removePaymentline(existingLine);
            }
            return;
        }

        // Never trust a non-finite remainingDue: falling back to voucherAmount
        // would resurrect the exact full-amount double-tender BON-1672/BON-1677
        // exist to avoid porting. Checked BEFORE any mutation, via typeof +
        // Number.isFinite (not a coercion check — Number(null)/Number("") are
        // both 0 and would silently cap the voucher to zero instead of aborting).
        //
        // remainingDue is NOT a linear function of amountPaid — it clamps to 0
        // once the order is fully/over-paid and applies currency rounding
        // (pos_order_accounting.js) — so "rawRemainingDue + existingLine's own
        // amount" is not a valid way to compute "due as if the voucher line
        // contributed nothing" (Challenge N1 on PR #81 round 2: that identity
        // overshoots the cap on an over-tender, leaving the voucher line too
        // high and re-opening the exact double-tender this ticket exists to
        // fix). Zero the existing line first so the SECOND read of
        // remainingDue reflects reality through the same clamp/rounding the
        // getter itself applies, with a finite check on both reads.
        const preZeroDue = order.remainingDue;
        if (typeof preZeroDue !== "number" || !Number.isFinite(preZeroDue)) {
            return;
        }
        if (existingLine && existingLine.setAmount) {
            existingLine.setAmount(0);
        }
        const remainingDue = order.remainingDue;
        if (typeof remainingDue !== "number" || !Number.isFinite(remainingDue)) {
            return;
        }
        // remainingDue can go negative on an ordinary cash-with-change
        // over-tender; a payment line amount is never negative.
        const cappedAmount = Math.max(0, Math.min(voucherAmount, remainingDue));
        // Final check on the value that actually reaches setAmount (Challenge
        // N3 on PR #81 round 2), not just its inputs — Math.max/Math.min
        // propagate a NaN input straight through.
        if (typeof cappedAmount !== "number" || !Number.isFinite(cappedAmount)) {
            return;
        }

        if (existingLine) {
            // Never remove an existing voucher line just because another line
            // grew to squeeze it toward zero — the voucher is already redeemed
            // server-side. Leave it in place (possibly at 0) and let
            // _orderHasUnresolvedBonatVoucher block Validate until the cashier
            // frees up room for it. A manual delete does NOT reach this branch
            // again (removePaymentline took the line out and the sticky flag
            // short-circuits this whole method above) and does NOT unblock
            // Validate either — see the dedicated dialog branch in
            // validateOrder (Challenge N2 on PR #81 round 2).
            if (existingLine.setAmount) {
                existingLine.setAmount(cappedAmount);
            }
            return;
        }

        if (cappedAmount <= 0) {
            return;
        }

        const result = order.addPaymentline(method);
        if (result.status && result.data) {
            result.data.setAmount(cappedAmount);
            // order.addPaymentline() selects the line it just created,
            // including this programmatic one. Left selected, the cashier's
            // next numpad keystroke is silently swallowed by
            // updateSelectedPaymentline's hidden-line guard with no visual cue
            // (classic 19's Challenge F7) — move selection to a real,
            // tenderable line.
            this._deselectHiddenPaymentLine(order);
        }
    },

    _deselectHiddenPaymentLine(order) {
        const selected = order.getSelectedPaymentline ? order.getSelectedPaymentline() : undefined;
        if (!selected || !selected.payment_method_id) {
            return;
        }
        if (!this._bonatVoucherHiddenIds.has(selected.payment_method_id.id)) {
            return;
        }
        const nextLine = (order.payment_ids || []).find(
            (p) => p.payment_method_id && !this._bonatVoucherHiddenIds.has(p.payment_method_id.id)
        );
        order.selectPaymentline(nextLine || undefined);
    },

    // The voucher line's amount is server-derived and capped by
    // _syncBonatVoucherPaymentLine; the numpad has no concept of that cap, so
    // without this guard a cashier could select the line and type any amount.
    // Removal via the line's own delete button still works — that goes through
    // deletePaymentLine directly and never reaches this method.
    updateSelectedPaymentline(amount = false) {
        const line = this.selectedPaymentLine;
        if (
            line &&
            line.payment_method_id &&
            this._bonatVoucherHiddenIds.has(line.payment_method_id.id)
        ) {
            this.numberBuffer.reset();
            return;
        }
        const result = super.updateSelectedPaymentline(...arguments);
        // Another line's amount just changed: recompute the voucher cap against
        // the new remaining due. Not awaited (this method isn't async) — caught
        // instead, so a throw inside the sync (e.g. assertEditable()) surfaces
        // as a logged error rather than an unhandled rejection (Review B2 on
        // PR #81 round 1; same shape onMounted() already guards against).
        this._syncBonatVoucherPaymentLine().catch((error) => {
            console.error("[bonat] voucher payment-line sync failed:", error);
        });
        return result;
    },

    // Re-sync whenever another payment line is added, so a cashier's own tender
    // never lands without the voucher line seeing it.
    async addNewPaymentLine(paymentMethod) {
        const result = await super.addNewPaymentLine(paymentMethod);
        // Caught, not awaited into the return value: a sync failure here must
        // not make addNewPaymentLine itself reject and lose the payment line
        // core just added (Review B2 on PR #81 round 1).
        this._syncBonatVoucherPaymentLine().catch((error) => {
            console.error("[bonat] voucher payment-line sync failed:", error);
        });
        return result;
    },

    // Re-sync on removal too, EXCEPT when the removed line is the voucher line
    // itself — mark the order so it stays removed instead of being silently
    // re-added by the very next unrelated payment-line event.
    deletePaymentLine(uuid) {
        const line = this.paymentLines.find((l) => l.uuid === uuid);
        const isBonatVoucherLine = !!(
            line &&
            line.payment_method_id &&
            this._bonatVoucherHiddenIds.has(line.payment_method_id.id)
        );
        super.deletePaymentLine(uuid);
        if (isBonatVoucherLine) {
            const order = this.pos.getOrder();
            if (order) {
                order._bonatVoucherManuallyRemoved = true;
            }
        } else {
            // Caught for the same reason as the other two call sites (Review
            // B2 on PR #81 round 1) — a throw here must not become an
            // unhandled rejection after the line has already been deleted.
            this._syncBonatVoucherPaymentLine().catch((error) => {
                console.error("[bonat] voucher payment-line sync failed:", error);
            });
        }
    },

    async validateOrder(isForceValidate) {
        const order = this.pos.getOrder();
        // Refuse Validate while a Bonat code entry is still in flight on this
        // order (Review B1 on this ticket): applyType1Discount() briefly
        // leaves an earlier, already-redeemed code's discount line coexisting
        // with the new line while the new code's own redeem() round-trip is
        // pending (see promo_code_button.js's applyType1Discount for why that
        // window exists and can't be closed without re-opening the silent-
        // burn risk it replaced). order._bonatCodeInFlight is already set for
        // that whole window (promo_code_button.js's fetch_bonat_code) — this
        // is the only other place in the module that needs to read it, so a
        // Validate landing inside the window is blocked here instead of the
        // window being eliminated at the source.
        if (order._bonatCodeInFlight) {
            this.dialog.add(AlertDialog, {
                title: _t("Bonat Code Entry In Progress"),
                body: _t(
                    "A Bonat code is still being applied to this order. Please wait for it to finish before validating."
                ),
            });
            return;
        }
        if (this._orderHasUnresolvedBonatVoucher(order)) {
            // Three distinct causes reach this guard, each with its own honest
            // copy and recovery instruction (Challenge N2 on PR #81 round 2 —
            // correcting round 1's F4 fix, which let a manual delete validate
            // at full price instead of fixing the misleading copy):
            //   1. The cashier manually deleted the voucher line. Sticky —
            //      _syncBonatVoucherPaymentLine will not re-add it — and the
            //      line cannot be re-added from this screen either (the method
            //      is hidden from the manual payment list by design). The only
            //      real recovery is reloading the POS: order state (lines,
            //      applied code, merchant identity) survives a reload via
            //      IndexedDB, but the in-memory-only sticky flag does not, so
            //      a reload lets the sync re-attach the line. Verified live
            //      per this build's own README trial results.
            //   2. No line at all, and not a manual delete — a genuine
            //      timing/config edge case (e.g. sync has not run yet).
            //   3. A line exists but is squeezed to 0 by another payment line
            //      — cashier-resolvable in one tap, no reload needed.
            // Block Validate in all three rather than charge the customer a
            // second time for an already-redeemed voucher.
            const voucherMethod = this._getBonatVoucherMethod();
            const paymentlines = order.payment_ids || [];
            const voucherLine = voucherMethod
                ? paymentlines.find(
                      (p) => p.payment_method_id && p.payment_method_id.id === voucherMethod.id
                  )
                : undefined;
            const methodName = (voucherMethod && voucherMethod.name) || _t("Bonat Voucher");
            let title;
            let body;
            // Copy diverges from classic 19 here (post BON-2568): on this build
            // the voucher is already redeemed server-side by the time this guard
            // can ever fire — promo_code_button.js calls bonatApi.redeem() at
            // popup-confirm time, well before Validate. Every branch below states
            // the same actionable fact the cashier needs: the voucher's value is
            // already consumed and cannot be recovered, so clearing it to get
            // through checkout destroys it — not merely "won't be charged again"
            // (Challenge F3 on this ticket: that phrasing reads as a reassurance,
            // not a warning, and the previous copy's "not been charged" claim was
            // itself always wrong for a build where redemption ran at Validate).
            const redeemedNotice = _t(
                "This voucher's value was already consumed with Bonat when the code was confirmed — it cannot be recovered, so clearing it from this order does not refund it."
            );
            if (order._bonatVoucherManuallyRemoved) {
                title = _t("Voucher payment removed");
                body = _t(
                    "This order has a Bonat voucher applied, but its %s payment line was deleted and cannot be re-added from this screen. Reload the POS to restore it — the order itself is recovered automatically — or ask a manager for help. %s",
                    methodName,
                    redeemedNotice
                );
            } else if (voucherLine) {
                title = _t("Voucher payment incomplete");
                body = _t(
                    "This order has a Bonat voucher applied, but the %s payment line is currently at 0. Free up amount on another payment line so it can cover the voucher, then Validate again. %s",
                    methodName,
                    redeemedNotice
                );
            } else {
                title = _t("Voucher payment method unavailable");
                body = _t(
                    "This order has a Bonat voucher applied, but no %s payment line is attached to it. Validate is blocked until the voucher payment method is available on this POS — check Point of Sale → Configuration → Bonat Integration, or contact support. %s",
                    methodName,
                    redeemedNotice
                );
            }
            this.dialog.add(AlertDialog, { title, body });
            return;
        }

        const bonat_merchant_id = order.get_bonat_merchant_id();
        const bonat_merchant_name = order.get_bonat_merchant_name();
        const branch_id = this.pos.config.name;
        const branch_name = this.pos.config.name;
        const session_id = String(this.pos.session.id);
        const session_name = this.pos.session.display_name || this.pos.session.name;
        const customer = order.getPartner() || {};
        const customer_id = customer.id || null;
        const customer_name = customer.name || "Guest";
        let customer_phone = "";
        let dial_code = "";

        if (customer && customer.phone) {
            const cleanedNumber = customer.phone.replace(/\D/g, "");
            if (cleanedNumber.length === 12) {
                customer_phone = "9665" + cleanedNumber.slice(4);
                dial_code = "9665";
            } else if (cleanedNumber.length === 10) {
                customer_phone = "05" + cleanedNumber.slice(2);
                dial_code = "05";
            } else if (cleanedNumber.length === 9) {
                customer_phone = "5" + cleanedNumber.slice(1);
                dial_code = "5";
            }
        }
        const customer_email = customer.email || "";

        const products = order.getOrderlines().map((line) => {
            const product = line.product_id;
            return {
                product: {
                    category: {
                        id:
                            product.categ_id?.id ??
                            product.categ_id?.[0] ??
                            product.pos_categ_ids?.[0]?.id ??
                            null,
                        name:
                            product.categ_id?.name ??
                            product.categ_id?.[1] ??
                            product.pos_categ_ids?.[0]?.name ??
                            "Unknown",
                    },
                    id: product.id,
                    name: product.display_name || "Unnamed Product",
                    price: line.price_unit || 0,
                },
                quantity: line.getQuantity?.() ?? 0,
                unit_price: line.price_unit || 0,
                total_price: line.displayPrice || 0,
            };
        });

        const taxes = order
            .getOrderlines()
            .map((orderLine) =>
                (orderLine.tax_ids || []).map((tax) => ({
                    id: tax.id,
                    name: tax.name,
                    rate: tax.amount,
                }))
            )
            .flat();

        const subtotal_price = parseFloat(order.priceExcl || 0).toFixed(2);
        const amount_tax = parseFloat(order.amountTaxes || 0).toFixed(2);
        const amount_total = parseFloat(order.priceIncl || 0).toFixed(2);

        const timestamp = Math.floor(Date.now() / 1000);
        const order_creation_data = {
            timestamp: timestamp,
            event: "order.created",
            business: {
                name: bonat_merchant_name,
                reference: bonat_merchant_id,
            },
            order: {
                order_id: parseInt(order.tracking_number, 10) || 0,
                branch: {
                    id: branch_id,
                    name: branch_name,
                },
                pos: {
                    id: session_id,
                    name: session_name,
                },
                taxes: taxes,
                products: products,
                quantity: order
                    .getOrderlines()
                    .reduce((sum, line) => sum + (line.getQuantity?.() ?? 0), 0),
                subtotal_price: parseFloat(subtotal_price),
                amount_tax: parseFloat(amount_tax),
                total_price: parseFloat(amount_total),
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
            },
        };

        if (customer && customer.id) {
            order_creation_data.order.customer = {
                id: customer_id ? String(customer_id) : "0",
                name: customer_name,
                dial_code: parseInt(dial_code || ""),
                phone: customer_phone,
                email: customer_email,
            };
        }

        // Redemption (bonatApi.redeem()) no longer happens here — see the
        // BON-2568 note at the top of this file. Any applied Bonat code was
        // already redeemed server-side in promo_code_button.js by the time
        // this point is reached.

        await this._finalizeOrderCreation(order_creation_data);
        await super.validateOrder(...arguments);
    },

    async _finalizeOrderCreation(order_creation_data) {
        const response = await this.pos.bonatApi.orderCreated(order_creation_data);
        if (response.success) {
            console.log("[bonat] order creation success:", response);
        } else {
            // Non-fatal by design, matching on-premise: the sale completes even if
            // Bonat did not record it, and the failure is left in the console for
            // diagnosis rather than blocking the cashier.
            console.error("[bonat] order creation failed:", response);
        }
    },
});
