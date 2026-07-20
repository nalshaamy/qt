/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { patch } from "@web/core/utils/patch";

patch(ProductScreen.prototype, {
    // Odoo 19: updateSelectedOrderline() was removed; numpad edits now flow through
    // onNumpadClick(). Clear the applied Bonat code when the discount line is edited.
    onNumpadClick(buttonValue) {
        const selectedLine = this.currentOrder.getSelectedOrderline();
        const discountProductId = this.pos.config.discount_product_id?.id || this.pos.config.discount_product_id;
        const product = this.pos.models["product.product"].get(discountProductId);
        if (selectedLine && selectedLine.product_id === product) {
            this.currentOrder.set_applied_bonat_code();
            this.currentOrder.set_bonat_merchant_id();
            this.currentOrder.set_bonat_merchant_name();
        }
        return super.onNumpadClick(buttonValue);
    },
    get bonatVoucherActive() {
        const order = this.currentOrder;
        return !!(order && order.get_bonat_voucher_method && order.get_bonat_voucher_method() === "Voucher");
    },
    get bonatVoucherLabel() {
        const order = this.currentOrder;
        if (!order) return "";
        const amt = order.get_bonat_voucher_amount();
        const curr = order.get_bonat_voucher_currency() || this.pos?.currency?.name || "";
        return `${_t("Bonat Voucher:")} ${amt} ${curr} ${_t("applied.")}`;
    },
    removeBonatVoucher() {
        const order = this.currentOrder;
        if (order && order.clear_bonat_voucher) {
            order.clear_bonat_voucher();
        }
    },
});
