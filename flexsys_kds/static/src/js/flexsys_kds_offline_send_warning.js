/** @odoo-module **/

// REAL BUG FIX ("Offline Recovery - نتيجة الاختبار الحي"): confirmed
// live that Odoo 19's own POS does NOT automatically retry
// `sync_from_ui` after a reconnect for a Send pressed while offline -
// "لا يوجد Automatic RPC retry بعد Reconnect في هذا السيناريو." The
// client's own explicitly approved design for THIS round (Auto-Retry
// deliberately deferred to a future round, only once a confirmed-
// reliable Odoo 19 re-sync method is identified): an EXPLICIT,
// persistent "Pending/Failed Kitchen Send" warning - never a silent
// loss, never a false success indication, and never a silent
// auto-retry.
//
// Deliberately the lowest-risk possible design, given this project's
// own confirmed history with frontend changes (the entirely-removed
// v7.9.3/v7.9.6 patches, and the POS-startup-breaking
// _load_pos_data_fields() override reverted in v7.13.1):
//
// - The pending marker is stored in the browser's own plain
//   `localStorage` - completely independent of any Odoo data model,
//   record, or field. It cannot conflict with, corrupt, or even be
//   seen by any Odoo POS data-loading/serialization mechanism at all.
// - The only Odoo-specific surface touched is patching
//   `PosStore.prototype.sendOrderInPreparation` - the SAME confirmed
//   hook point (directly cited from Odoo 19's own core source) already
//   used, safely, by flexsys_kds_send_generation.js in an earlier
//   round (since removed for unrelated reasons - the increment
//   mechanism it supported was reverted in v7.13.1, but the hook
//   point's own safety was never in question).
// - Every other piece is a standard, stable, well-documented browser
//   API (`localStorage`, `navigator.onLine`, the `online` window
//   event) or a standard, widely-used Odoo/OWL service pattern
//   (`notification.add(..., {sticky: true})`) - never an uncertain or
//   conflicting-documentation internal mechanism.
// - super.sendOrderInPreparation()'s own call, return value, and
//   thrown-error behavior are never suppressed or altered - only
//   observed, from the outside, to decide whether to mark/clear the
//   pending flag and whether to show the warning. Every piece of this
//   module's own logic is wrapped in its own try/catch, so a failure
//   here can never affect the actual Send/print flow the cashier
//   depends on.
import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { _t } from "@web/core/l10n/translation";

const PENDING_KEY_PREFIX = "flexsys_kds_pending_send:";
const PENDING_WARNING_MESSAGE = _t(
    "Kitchen order was not delivered. Please press Send again."
);

function pendingKey(orderUuid) {
    return PENDING_KEY_PREFIX + orderUuid;
}

function markPending(orderUuid) {
    try {
        window.localStorage.setItem(pendingKey(orderUuid), String(Date.now()));
    } catch (error) {
        console.error("FlexSys KDS: failed to persist pending Send flag", error);
    }
}

function clearPending(orderUuid) {
    try {
        window.localStorage.removeItem(pendingKey(orderUuid));
    } catch (error) {
        console.error("FlexSys KDS: failed to clear pending Send flag", error);
    }
}

function hasAnyPending() {
    try {
        for (let i = 0; i < window.localStorage.length; i++) {
            const key = window.localStorage.key(i);
            if (key && key.startsWith(PENDING_KEY_PREFIX)) {
                return true;
            }
        }
    } catch (error) {
        console.error("FlexSys KDS: failed to scan pending Send flags", error);
    }
    return false;
}

patch(PosStore.prototype, {
    setup(...args) {
        super.setup(...args);
        // REAL BUG FIX ("Offline Recovery"): on reconnect, the warning
        // is re-shown (not auto-retried) if any Send is still pending -
        // "Reconnect → warning remains." Registered once per POS
        // session start; wrapped defensively so a failure here can
        // never affect the rest of POS startup.
        try {
            window.addEventListener("online", () => {
                try {
                    if (hasAnyPending() && this.notification) {
                        this.notification.add(PENDING_WARNING_MESSAGE, {
                            type: "danger",
                            sticky: true,
                        });
                    }
                } catch (error) {
                    console.error(
                        "FlexSys KDS: failed to show reconnect pending-Send warning", error);
                }
            });
        } catch (error) {
            console.error("FlexSys KDS: failed to register online listener", error);
        }
    },

    async sendOrderInPreparation(order, opts = {}) {
        const orderUuid = order && order.uuid;
        // REAL BUG FIX ("Offline Recovery"): checked BEFORE the native
        // call too, not only in the catch block below - some offline
        // scenarios may resolve locally without throwing at all
        // (Odoo's own offline-first order model queuing the write
        // silently); navigator.onLine is a second, independent signal
        // that does not depend on assuming how the native call itself
        // behaves when offline.
        if (orderUuid && !navigator.onLine) {
            markPending(orderUuid);
            try {
                if (this.notification) {
                    this.notification.add(PENDING_WARNING_MESSAGE, {
                        type: "danger",
                        sticky: true,
                    });
                }
            } catch (error) {
                console.error("FlexSys KDS: failed to show pending-Send warning", error);
            }
        }
        try {
            const result = await super.sendOrderInPreparation(order, opts);
            // REAL BUG FIX ("Offline Recovery"): "بعد نجاح الإرسال، امسح
            // الـPending flag" - cleared only after the native call
            // itself has genuinely completed without raising, matching
            // this module's own established "acknowledge only after
            // success" principle elsewhere.
            if (orderUuid) {
                clearPending(orderUuid);
            }
            return result;
        } catch (error) {
            if (orderUuid) {
                markPending(orderUuid);
                try {
                    if (this.notification) {
                        this.notification.add(PENDING_WARNING_MESSAGE, {
                            type: "danger",
                            sticky: true,
                        });
                    }
                } catch (notifyError) {
                    console.error(
                        "FlexSys KDS: failed to show pending-Send warning", notifyError);
                }
            }
            // Re-thrown, never swallowed - the native error handling
            // this method's own callers already rely on must continue
            // to run exactly as it did before this patch existed.
            throw error;
        }
    },
});
