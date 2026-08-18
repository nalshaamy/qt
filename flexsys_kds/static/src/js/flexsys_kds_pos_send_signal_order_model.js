/** @odoo-module **/

// REAL BUG FIX ("Explicit POS Send Must Trigger KDS Sync"), confirmed
// live: the normal POS "Send" button was already confirmed correctly
// gated (nothing leaks before it, per this same round's own Part 1
// PASS) - but when Odoo's own native "the order has not been sent -
// would you like to send it to preparation?" confirmation dialog
// appeared and the cashier clicked "Order" (Odoo's own explicit Send-
// to-preparation confirmation), FlexSys KDS never received the sync.
//
// flexsys_kds_pos_send_signal.js (this module's own earlier patch)
// hooks PosStore.prototype.sendOrderInPreparation() specifically - the
// method confirmed, from Odoo 19's own core source, to be the native
// "Send" button's own target. It has NOT been independently confirmed
// whether the unsent-order confirmation dialog's own "Order" button
// calls that exact same method, or a different one that itself calls
// something else on the way to actually persisting the send.
//
// What IS confirmed, from that same core source
// (addons/point_of_sale/static/src/app/services/pos_store.js), is that
// order.updateLastOrderChange() is the ACTUAL method that persists
// last_order_preparation_change to the server - the genuine,
// lower-level "this order was just sent" event, common to every UI
// path that leads to a real Send, regardless of which specific button
// or dialog triggered it. This patch hooks that method directly, as a
// second, independent layer - not a replacement for the existing
// sendOrderInPreparation patch, which stays in place unchanged.
//
// Deliberately isolated in its OWN file, separate from
// flexsys_kds_pos_send_signal.js: if this file's own import path turns
// out to be wrong for a given Odoo 19 build, that failure must not be
// able to also break the already-confirmed-working
// sendOrderInPreparation patch - a JS module's own import failure
// prevents everything else in that SAME file from loading too, so
// keeping these as two separate files means a problem with one cannot
// cascade into the other.
//
// Same defensive design as the other patch: super() is always called
// first, unconditionally, its own result always returned unchanged;
// the added RPC call is wrapped in its own try/catch, entirely
// separate from the native call, so a failure here can never affect
// the actual order-saving flow the cashier depends on.
import { patch } from "@web/core/utils/patch";
import { rpc } from "@web/core/network/rpc";
import { PosOrder } from "@point_of_sale/app/models/pos_order";

async function flexsysRegisterSendIfPersisted(order) {
    try {
        const orderId = order && order.id;
        // Same reasoning as the other patch's own matching comment: a
        // locally-created, not-yet-synced order uses a temporary,
        // non-numeric or negative id - skip silently rather than risk
        // targeting the wrong record. This module's own backend-side
        // fallback (kds_last_processed_send_signal) remains available
        // for that case regardless.
        if (typeof orderId === "number" && orderId > 0) {
            await rpc("/web/dataset/call_kw", {
                model: "pos.order",
                method: "flexsys_kds_register_send",
                args: [[orderId]],
                kwargs: {},
            });
        }
    } catch (error) {
        console.error("FlexSys KDS: failed to register explicit Send signal (order model patch)", error);
    }
}

patch(PosOrder.prototype, {
    async updateLastOrderChange(...args) {
        const result = await super.updateLastOrderChange(...args);
        await flexsysRegisterSendIfPersisted(this);
        return result;
    },
});
