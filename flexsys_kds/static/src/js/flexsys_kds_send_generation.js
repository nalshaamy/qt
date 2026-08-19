/** @odoo-module **/

// REAL BUG FIX ("FINAL IMPLEMENTATION REQUEST - Frontend Durable Send
// Generation - Offline-Safe KDS Send"): the confirmed, currently-open
// gap in the otherwise-complete v7.12.1 backend architecture. Backend
// confirmed accepted as-is by the client's own explicit instruction -
// this file adds ONLY the missing frontend increment, nothing else.
//
// Hook point: PosStore.prototype.sendOrderInPreparation(order, opts) -
// confirmed directly from Odoo 19's own core source
// (addons/point_of_sale/static/src/app/services/pos_store.js) to be
// the method the native "Send" action calls, and confirmed by the
// client's own live Network A/B test to be the exact boundary between
// an ordinary POS edit (zero related calls) and a genuine Send
// (get_preparation_change -> sync_from_ui). This is the SAME method
// flexsys_kds_pos_send_signal.js patched in v7.9.3 - that earlier
// patch was removed entirely in v7.11.0 once the client's own evidence
// showed a SEPARATE RPC call added there could itself be lost offline,
// which is exactly the class of failure this current design avoids:
// this patch makes no RPC call of its own at all. It only mutates a
// field on the LOCAL order object already being tracked by Odoo's own
// offline-first POS model - the increment is synchronous, in-memory,
// and completes before this function's own native body (including any
// network activity) even begins.
//
// Why this increment is safe to perform unconditionally, every time
// this method is called, without first determining whether the native
// method's own internal reprint-detection logic will treat this
// specific call as a "reprint": a reprint recomputes the same order
// content that was already sent, so even if this causes
// kds_send_generation to advance without any actual line-level change,
// the backend's own reconciliation (_flexsys_kds_diff_lines) still
// correctly finds nothing new to apply - a harmless, idempotent no-op,
// never a duplicate ticket or incorrect data. The backend's own
// authorization comparison (`incoming > last_processed`, not exact
// equality) is likewise tolerant of an occasional multi-step advance,
// so this single, simple increment point remains correct even in an
// edge case this delivery process cannot fully rule out without direct
// live access - namely, whether this exact method is ever invoked more
// than once for a single logical cashier Send action.
//
// Deliberately minimal and maximally defensive, matching every prior
// hook in this module's own history: super.sendOrderInPreparation() is
// always called, unconditionally, with its own result always returned
// completely unmodified; the increment itself is wrapped in its own
// try/catch, entirely separate from the native call, so a failure here
// (an unexpected order shape, anything at all) can never affect the
// actual Send/print flow the cashier depends on.
import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";

patch(PosStore.prototype, {
    async sendOrderInPreparation(order, opts = {}) {
        try {
            if (order) {
                // Local, synchronous, offline-safe: no RPC, no network
                // dependency of any kind. Odoo's own offline-first POS
                // model (this field loaded via this module's own
                // _load_pos_data_fields() override - no further
                // frontend wiring needed for it to be tracked,
                // persisted, and eventually included in this order's
                // own sync_from_ui payload) carries this value forward
                // exactly like any other native order field, surviving
                // a disconnect/reconnect or a local browser reload the
                // same way last_order_preparation_change already does.
                order.kds_send_generation = (order.kds_send_generation || 0) + 1;
            }
        } catch (error) {
            // Deliberately swallowed, not re-thrown: a failure here
            // must never affect the cashier's own native Send/print
            // flow - see this file's own top-of-file comment.
            console.error("FlexSys KDS: failed to increment kds_send_generation", error);
        }
        return await super.sendOrderInPreparation(order, opts);
    },
});
