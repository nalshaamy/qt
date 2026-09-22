/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";

/**
 * Keep the browser-side counter aligned when the backend repairs a duplicate
 * inside the same device namespace.
 *
 * Example:
 *   browser submits 2656-3-000003 (already used)
 *   backend repairs it to 2656-3-000004
 *
 * Before the payment flow creates the next blank order, this hook advances the
 * local device counter to at least 5. If an unsynced draft already owns 000004,
 * it is shifted forward as well so the browser never immediately recreates the
 * collision that the server just repaired.
 */
patch(PosStore.prototype, {
    _flexsysCurrentReferencePrefix() {
        const data = this.device?.data;
        const deviceIdentifier = data?.device_identifier;
        const configId = this.config?.id;
        if (!deviceIdentifier || !configId) {
            return null;
        }
        const year2Digits = String(new Date().getFullYear()).slice(-2);
        return `${year2Digits}${deviceIdentifier}-${configId}-`;
    },

    _flexsysReferenceNumber(reference, prefix) {
        if (!reference || !prefix || !String(reference).startsWith(prefix)) {
            return null;
        }
        const suffix = String(reference).slice(prefix.length);
        if (!/^\d+$/.test(suffix)) {
            return null;
        }
        const number = Number(suffix);
        return Number.isSafeInteger(number) && number > 0 ? number : null;
    },

    _flexsysTrackingNumber(number) {
        return `${this.device.identifier}${String(number % 1000).padStart(3, "0")}`;
    },

    _flexsysAlignDeviceSequence(syncedOrders = []) {
        const data = this.device?.data;
        const prefix = this._flexsysCurrentReferencePrefix();
        if (!data || !prefix) {
            return;
        }

        let maxSyncedNumber = 0;
        const syncedUuids = new Set();
        for (const order of syncedOrders || []) {
            if (order?.uuid) {
                syncedUuids.add(order.uuid);
            }
            const number = this._flexsysReferenceNumber(order?.pos_reference, prefix);
            if (number && number > maxSyncedNumber) {
                maxSyncedNumber = number;
            }
        }
        if (!maxSyncedNumber) {
            return;
        }

        const localOrders = this.models["pos.order"].getAll();
        const occupied = new Set();
        const conflicts = [];

        for (const order of localOrders) {
            const number = this._flexsysReferenceNumber(order.pos_reference, prefix);
            if (!number) {
                continue;
            }

            // A just-synced server record is authoritative.
            if (syncedUuids.has(order.uuid) || order.isSynced) {
                occupied.add(number);
                continue;
            }

            // Unsynced orders at/below the repaired sequence could collide with
            // the authoritative server reference and must be shifted forward.
            if (number <= maxSyncedNumber) {
                conflicts.push({ order, number });
            } else {
                occupied.add(number);
            }
        }

        conflicts.sort((a, b) => a.number - b.number);
        let candidate = maxSyncedNumber + 1;
        for (const { order } of conflicts) {
            while (occupied.has(candidate)) {
                candidate += 1;
            }
            const suffix = String(candidate).padStart(6, "0");
            order.pos_reference = `${prefix}${suffix}`;
            order.tracking_number = this._flexsysTrackingNumber(candidate);
            occupied.add(candidate);
            candidate += 1;
        }

        const highestOccupied = occupied.size ? Math.max(...occupied) : maxSyncedNumber;
        const parsedCurrent = Number(data.next_number);
        const currentNext = Number.isSafeInteger(parsedCurrent) && parsedCurrent > 0 ? parsedCurrent : 1;
        const desiredNext = Math.max(currentNext, highestOccupied + 1, candidate);

        if (desiredNext !== currentNext || (data.unsynced_number_stack || []).length) {
            this.device.save({
                device_identifier: data.device_identifier,
                next_number: desiredNext,
                unsynced_number_stack: [],
            });
        }
    },

    async postSyncAllOrders(orders) {
        const result = await super.postSyncAllOrders(...arguments);
        this._flexsysAlignDeviceSequence(orders);
        return result;
    },
});
