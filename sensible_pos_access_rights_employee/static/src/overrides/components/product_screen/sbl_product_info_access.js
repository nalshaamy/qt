/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";

// Restrict all POS UI entry points, including long-press on a product card.
// The permission is read at call time so changing cashiers takes effect immediately.
patch(PosStore.prototype, {
    async onProductInfoClick(...args) {
        if (this.cashier?.sbl_hide_pos_action_product_info) {
            return;
        }
        return super.onProductInfoClick(...args);
    },
});
