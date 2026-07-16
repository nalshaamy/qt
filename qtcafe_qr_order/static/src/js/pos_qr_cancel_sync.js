/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { rpc } from "@web/core/network/rpc";
import { PosOrder } from "@point_of_sale/app/models/pos_order";

function relationId(value) {
    if (!value) {
        return false;
    }
    if (typeof value === "number") {
        return value;
    }
    return value.id || false;
}

function isQtCafeQrOrder(order) {
    if (!order) {
        return false;
    }
    const reference = String(order.pos_reference || order.name || "").trim();
    return Boolean(
        relationId(order.qtcafe_qr_order_id) ||
        reference.startsWith("QR") ||
        reference.startsWith("QT")
    );
}

patch(PosOrder.prototype, {
    async _qtcafeCancelLinkedQrOrder() {
        if (!isQtCafeQrOrder(this) || this.__qtcafeQrCancelSent) {
            return;
        }
        this.__qtcafeQrCancelSent = true;

        try {
            const result = await rpc("/qtcafe/pos/cancel_qr_order", {
                pos_order_id: typeof this.id === "number" ? this.id : false,
                pos_uuid: this.uuid || false,
                pos_reference: this.pos_reference || false,
                pos_name: this.name || false,
                qr_order_id: relationId(this.qtcafe_qr_order_id),
            });

            if (!result?.success) {
                this.__qtcafeQrCancelSent = false;
            }
        } catch (error) {
            // Allow a retry if the first request failed.
            this.__qtcafeQrCancelSent = false;
            console.warn("QT Cafe: failed to cancel linked QR order", error);
        }
    },

    async delete(...args) {
        // In Odoo 19 the cashier can remove a draft order only from the POS
        // browser. Notify the server before the local POS record disappears.
        await this._qtcafeCancelLinkedQrOrder();
        return await super.delete(...args);
    },
});
