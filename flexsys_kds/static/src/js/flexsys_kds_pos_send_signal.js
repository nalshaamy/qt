/** @odoo-module **/

// REAL BUG FIX ("On Send to KDS / Subsequent Changes Bypass Send
// Gate"), confirmed STILL reproducing live even after two rounds of
// purely backend-side attempts to infer a genuine Send from
// last_order_preparation_change's own content - see
// pos_order.py::flexsys_kds_register_send()'s own docstring for the
// complete root-cause explanation of why interpreting that Odoo-core
// field's own value was abandoned as a strategy.
//
// This patch is deliberately minimal and defensive:
//   - It NEVER replaces or modifies Odoo's own native Send behavior -
//     super.sendOrderInPreparation() is always called first, and its
//     own result is always returned unchanged.
//   - The added RPC call is wrapped in its own try/catch, entirely
//     separate from the native call above - if it fails for any
//     reason (network issue, unexpected order id shape, anything at
//     all), the native Send/print flow the cashier actually depends on
//     is completely unaffected. The only consequence of this call
//     failing is that FlexSys KDS falls back to not having received an
//     explicit signal for this specific Send - a safe "stays pending
//     until it does work" failure, not a broken POS screen.
//   - Only ever ADDS a call after Odoo's own success - never wraps,
//     delays, or gates the original method's own execution.
//
// Honest caveat, stated plainly: this patches
// PosStore.prototype.sendOrderInPreparation specifically, confirmed
// directly from Odoo 19's own core source
// (addons/point_of_sale/static/src/app/services/pos_store.js) to be
// the method the native "Send" action (Preparation Display enabled)
// actually calls. The native "New Order" action's own equivalent
// method name has NOT been confirmed against Odoo 19's own source in
// the same way - this patch does not attempt to guess at it. Under
// "On Send to KDS" mode with Preparation Display disabled, this
// specific mechanism therefore does not yet apply; that scenario
// still relies on the backend-side kds_last_processed_send_signal
// fallback in pos_order.py, which carries the same caveat already
// documented in RELEASE_STATUS.md for the "New" action generally.
import { patch } from "@web/core/utils/patch";
import { rpc } from "@web/core/network/rpc";
import { PosStore } from "@point_of_sale/app/services/pos_store";

patch(PosStore.prototype, {
    async sendOrderInPreparation(order, opts = {}) {
        const result = await super.sendOrderInPreparation(order, opts);
        try {
            const orderId = order && order.id;
            // A locally-created order not yet synced to the backend
            // uses a temporary, non-numeric or negative id in Odoo's
            // own offline-first POS model - skip silently rather than
            // risk targeting the wrong record. By the time
            // sendOrderInPreparation() has actually run,
            // updateLastOrderChange() (called within Odoo's own native
            // method above) has already persisted the order server-side
            // in the overwhelming majority of cases, so this should
            // rarely skip in practice - but failing to register the
            // explicit signal here only means this module's own
            // backend-side fallback (kds_last_processed_send_signal)
            // is what ends up handling this specific Send instead, not
            // a loss of the Send itself.
            if (typeof orderId === "number" && orderId > 0) {
                await rpc("/web/dataset/call_kw", {
                    model: "pos.order",
                    method: "flexsys_kds_register_send",
                    args: [[orderId]],
                    kwargs: {},
                });
            }
        } catch (error) {
            // Deliberately swallowed, not re-thrown: see this file's
            // own top-of-file comment for why a failure here must
            // never affect the cashier's own native Send/print flow.
            console.error("FlexSys KDS: failed to register explicit Send signal", error);
        }
        return result;
    },
});
