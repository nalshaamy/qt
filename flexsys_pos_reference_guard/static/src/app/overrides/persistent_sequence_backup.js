/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import DeviceIdentifierSequence from "@point_of_sale/app/utils/devices_identifier_sequence";

/**
 * Durable backup for the POS device numbering identity.
 *
 * Some browser/POS lifecycles can lose the native localStorage entry even when
 * the origin/access-token key stays the same. When that happens Odoo registers
 * a fresh device identifier and restarts the browser counter from 1.
 *
 * FlexSys keeps a tiny redundant backup in a persistent first-party cookie,
 * scoped per POS configuration. A normal tab close/open does not remove it,
 * and localStorage.clear() does not remove cookies.
 *
 * The cookie contains no customer/payment data; only:
 *   - device_identifier
 *   - next_number
 *   - an always-empty unsynced_number_stack
 *
 * If localStorage is missing on startup, restore the previous identity before
 * Odoo's native initialize() can register a new device. If both copies exist,
 * keep the highest next_number for the same device to avoid counter rollback.
 */

const COOKIE_PREFIX = "flexsys_pos_sequence_backup_";
const MAX_AGE_SECONDS = 60 * 60 * 24 * 365 * 2; // 2 years

function cookieKey() {
    return `${COOKIE_PREFIX}${odoo.pos_config_id}`;
}

function readCookieValue(name) {
    const prefix = `${encodeURIComponent(name)}=`;
    const item = document.cookie
        .split("; ")
        .find((entry) => entry.startsWith(prefix));
    if (!item) {
        return null;
    }
    try {
        return decodeURIComponent(item.slice(prefix.length));
    } catch {
        return null;
    }
}

function writeCookieValue(name, value) {
    const secure = window.location.protocol === "https:" ? "; Secure" : "";
    document.cookie = `${encodeURIComponent(name)}=${encodeURIComponent(value)}; Path=/; Max-Age=${MAX_AGE_SECONDS}; SameSite=Lax${secure}`;
}

function normalizeSequence(data) {
    if (!data?.device_identifier) {
        return null;
    }
    const nextNumber = Number(data.next_number);
    return {
        device_identifier: String(data.device_identifier),
        next_number: Number.isSafeInteger(nextNumber) && nextNumber > 0 ? nextNumber : 1,
        // FlexSys never recycles allocated receipt/order numbers.
        unsynced_number_stack: [],
    };
}

function readBackup() {
    const raw = readCookieValue(cookieKey());
    if (!raw) {
        return null;
    }
    try {
        return normalizeSequence(JSON.parse(raw));
    } catch {
        return null;
    }
}

function writeBackup(data) {
    const normalized = normalizeSequence(data);
    if (normalized) {
        writeCookieValue(cookieKey(), JSON.stringify(normalized));
    }
}

function readNativeLocalData() {
    const key = DeviceIdentifierSequence.uniqueDeviceIdentifierKey;
    try {
        return normalizeSequence(JSON.parse(localStorage.getItem(key)));
    } catch {
        return null;
    }
}

function writeNativeLocalData(data) {
    const normalized = normalizeSequence(data);
    if (!normalized) {
        return;
    }
    localStorage.setItem(
        DeviceIdentifierSequence.uniqueDeviceIdentifierKey,
        JSON.stringify(normalized)
    );
}

patch(DeviceIdentifierSequence.prototype, {
    async initialize() {
        const local = readNativeLocalData();
        const backup = readBackup();

        if (local) {
            // Same device in both stores: never let a stale copy move the
            // sequence backwards. If the backup belongs to another device,
            // the currently active native local copy wins and becomes the new
            // backup baseline.
            const reconciled =
                backup && backup.device_identifier === local.device_identifier
                    ? {
                          device_identifier: local.device_identifier,
                          next_number: Math.max(local.next_number, backup.next_number),
                          unsynced_number_stack: [],
                      }
                    : local;

            writeNativeLocalData(reconciled);
            writeBackup(reconciled);
            this.device_identifier = reconciled.device_identifier;
            return;
        }

        if (backup) {
            // Critical path: localStorage disappeared, but the browser still
            // owns a durable FlexSys backup. Restore it before Odoo registers
            // a new device identifier / restarts at 1.
            writeNativeLocalData(backup);
            this.device_identifier = backup.device_identifier;
            return;
        }

        // First use on this browser/POS: keep native Odoo behavior. Our patched
        // save() below will persist the newly registered identity to the cookie.
        await super.initialize(...arguments);
        writeBackup(readNativeLocalData());
    },

    save(values) {
        const result = super.save(...arguments);
        writeBackup(readNativeLocalData());
        return result;
    },
});
