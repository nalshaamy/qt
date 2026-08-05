/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { rpc } from "@web/core/network/rpc";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

/*
 * Odoo 19 POS no longer exposes this.pos.add_new_order().
 * This button now accepts the QR order on the server side.
 * The server creates/links the backend POS order, then we refresh/open the ticket screen.
 */
patch(ControlButtons.prototype, {
    async onClickFlexSysOperationsQrOrders() {
        if (this.__flexsys_operationsLoadingQrOrder) {
            return;
        }
        this.__flexsys_operationsLoadingQrOrder = true;

        try {
            const configId = this.pos?.config?.id || false;

            const response = await rpc("/operations/api/pos/pending-orders", {
                pos_config_id: configId,
            });

            const orders = response.orders || [];

            if (!orders.length) {
                this.dialog.add(AlertDialog, {
                    title: "Orders",
                    body: "لا توجد طلبات QR جديدة لهذه نقطة البيع.",
                });
                return;
            }

            const order = orders[0];
            const linesText = (order.lines || [])
                .map((line) => `${line.qty} x ${line.product_name}`)
                .join("\n");

            const confirmed = window.confirm(
                `طلب جديد: ${order.name}\n${linesText}\n\nهل تريد استلام الطلب في نقطة البيع؟`
            );

            if (!confirmed) {
                return;
            }

            const result = await rpc("/operations/api/orders/action", {
                order_id: order.id,
                action: "accept",
            });

            if (!result || !result.success) {
                this.dialog.add(AlertDialog, {
                    title: "Orders",
                    body: result?.error || "تعذر استلام الطلب.",
                });
                return;
            }

            this.notification.add(`تم استلام ${order.name} وإنشاء طلب نقطة البيع`, {
                type: "success",
            });

            // The POS order is created in the backend. Refresh ticket screen/list so it appears.
            setTimeout(() => {
                window.location.reload();
            }, 600);
        } finally {
            this.__flexsys_operationsLoadingQrOrder = false;
        }
    },
});
