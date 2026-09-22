/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import DeviceIdentifierSequence from "@point_of_sale/app/utils/devices_identifier_sequence";

/**
 * Preserve the POS browser numbering identity across Odoo's "Reload Data".
 *
 * In the deployed Odoo 19 build, PosStore.reloadData() clears IndexedDB,
 * sessionStorage and localStorage. Clearing localStorage removes the
 * DeviceIdentifierSequence key, so the next POS boot registers a new device
 * identifier and starts next_number from 1.
 *
 * FlexSys keeps the intentional data reload but restores only the numbering
 * identity after localStorage.clear():
 *   - device_identifier stays unchanged
 *   - next_number stays monotonic
 *   - unsynced_number_stack is reset to [] (numbers are never recycled)
 *
 * This patch deliberately does not preserve any other localStorage value.
 */
patch(PosStore.prototype, {
    async reloadData(fullReload = false) {
        const orders = this.models["pos.order"].getAll();

        // Keep the guard behavior consistent before the local databases are
        // reset. The patched saveUnusedNumber() never recycles identifiers.
        this.device.saveUnusedNumber(orders);

        const current = this.device?.data;
        const parsedNextNumber = Number(current?.next_number);
        const preservedSequence = current?.device_identifier
            ? {
                  device_identifier: String(current.device_identifier),
                  next_number:
                      Number.isInteger(parsedNextNumber) && parsedNextNumber > 0
                          ? parsedNextNumber
                          : 1,
                  unsynced_number_stack: [],
              }
            : null;

        await this.data.resetIndexedDB();
        sessionStorage.clear();
        localStorage.clear();

        // Restore only the sequence identity that Odoo would otherwise erase.
        // If the key was already unavailable/corrupt, fall back to Odoo's
        // native initialize() behavior and let it register a fresh device.
        if (preservedSequence) {
            localStorage.setItem(
                DeviceIdentifierSequence.uniqueDeviceIdentifierKey,
                JSON.stringify(preservedSequence)
            );
        }

        const url = new URL(window.location.href);
        if (fullReload) {
            url.searchParams.set("limited_loading", "0");
        }
        window.location.href = url.href;
    },
});
