/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { patch } from "@web/core/utils/patch";

/*
 * Port of static/src/overrides/components/product_screen/product_screen.js.
 *
 * The getters are unchanged apart from where they read the configuration from:
 * the Bonat company fields are manual x_ fields, which Odoo does not put in the
 * preloaded POS payload, so Demo Mode comes from pos.bonat (loaded at startup by
 * bonat_store.js) rather than from config.company_id.
 */
patch(ProductScreen.prototype, {
    /*
     * Clear the applied Bonat code when the cashier edits the discount line.
     *
     * Odoo 19 removed updateSelectedOrderline(); numpad edits flow through
     * onNumpadClick(). The line to watch is the Bonat discount product (resolved
     * at startup by bonat_store.js), with the legacy pos_discount product as
     * fallback — the same dual check classic 19 and the Odoo 17 pair use, so all
     * four builds reset on the same lines. (The classic build originally watched
     * only the core Global Discount product, which made the reset near-dead
     * code; classic adopted this build's Bonat-product check in 19.0.8.28.)
     */
    onNumpadClick(buttonValue) {
        const selectedLine = this.currentOrder?.getSelectedOrderline();
        const lineProductId = selectedLine && selectedLine.getProduct()?.id;
        const bonatProductId = this.pos?.bonat?.discountProduct?.id;
        const legacyProductId =
            this.pos.config.discount_product_id?.id || this.pos.config.discount_product_id;
        if (
            lineProductId &&
            (lineProductId === bonatProductId || lineProductId === legacyProductId)
        ) {
            this.currentOrder.set_applied_bonat_code("");
            this.currentOrder.set_bonat_merchant_id("");
            this.currentOrder.set_bonat_merchant_name("");
        }
        return super.onNumpadClick(buttonValue);
    },

    get bonatVoucherActive() {
        const order = this.currentOrder;
        return !!(
            order &&
            order.get_bonat_voucher_method &&
            order.get_bonat_voucher_method() === "Voucher"
        );
    },

    // No client-side "remove voucher" control on purpose (classic parity —
    // classic 19's BON-1835 Challenge B1, superseding this build's QA D1
    // gating): Odoo 17 had one and removed it under BON-1043/PR #62 —
    // clear_bonat_voucher() zeroed order state client-side only, so the
    // Validate-time _orderHasUnresolvedBonatVoucher guard saw "no voucher"
    // instead of "voucher with no payment line" and let a redeemed voucher
    // validate at full price with no error. D1's "keep it while enforcement is
    // off" carve-out lost its audience once voucher codes started being
    // declined at scan time on an unconfigured POS (classic Challenge B2
    // parity): a banner voucher can no longer exist without enforcement
    // active, except an order recovered from before this version — cosmetic
    // there, and not worth a whole escape hatch that has burned customers
    // before. The only supported way to drop a voucher is deleting its payment
    // line on the Payment screen, which the sticky _bonatVoucherManuallyRemoved
    // flag there accounts for.

    get bonatDemoModeActive() {
        return !!this.pos?.bonat?.demoMode;
    },

    get bonatDemoBannerLabel() {
        return _t("DEMO — no real transactions");
    },

    get bonatVoucherLabel() {
        const order = this.currentOrder;
        if (!order) {
            return "";
        }
        const amount = order.get_bonat_voucher_amount();
        const currency = order.get_bonat_voucher_currency() || this.pos?.currency?.name || "";
        return `${_t("Bonat Voucher:")} ${amount} ${currency} ${_t("applied.")}`;
    },

});
