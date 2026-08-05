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

function isFlexSysOperationsQrOrder(order) {
    if (!order) {
        return false;
    }
    const reference = String(order.pos_reference || order.name || "").trim();
    return Boolean(
        relationId(order.operations_qr_order_id) ||
        reference.startsWith("QR") ||
        reference.startsWith("FS")
    );
}

patch(PosOrder.prototype, {
    async _flexsys_operationsCancelLinkedQrOrder() {
        if (!isFlexSysOperationsQrOrder(this) || this.__flexsys_operationsQrCancelSent) {
            return;
        }
        this.__flexsys_operationsQrCancelSent = true;

        try {
            const result = await rpc("/operations/api/pos/cancel-order", {
                pos_order_id: typeof this.id === "number" ? this.id : false,
                pos_uuid: this.uuid || false,
                pos_reference: this.pos_reference || false,
                pos_name: this.name || false,
                qr_order_id: relationId(this.operations_qr_order_id),
            });

            if (!result?.success) {
                this.__flexsys_operationsQrCancelSent = false;
            }
        } catch (error) {
            // Allow a retry if the first request failed.
            this.__flexsys_operationsQrCancelSent = false;
            console.warn("FlexSys: failed to cancel linked QR order", error);
        }
    },

    async delete(...args) {
        // In Odoo 19 the cashier can remove a draft order only from the POS
        // browser. Notify the server before the local POS record disappears.
        await this._flexsys_operationsCancelLinkedQrOrder();
        return await super.delete(...args);
    },
});
