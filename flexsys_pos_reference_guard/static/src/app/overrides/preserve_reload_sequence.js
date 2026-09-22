/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import DeviceIdentifierSequence from "@point_of_sale/app/utils/devices_identifier_sequence";
import { chooseReclaimableDraft } from "./draft_reuse_safety";

/**
 * Use a unique per-tab message response to decline draft-number reuse whenever
 * another live POS tab/window is visible. If this API is missing or a check
 * errors, we keep the higher counter and accept a harmless numbering gap.
 * Server-side reference collision repair remains the ultimate safety net.
 */
const POS_ID = String(odoo.pos_config_id);
const TAB_ID = `${Date.now()}-${Math.random()}`;
const channel = typeof BroadcastChannel === "undefined"
    ? null
    : new BroadcastChannel(`flexsys-pos-reference-guard-tabs-${POS_ID}`);

if (channel) {
    channel.addEventListener("message", (event) => {
        const message = event.data;
        if (message?.kind === "probe" && message.tab !== TAB_ID) {
            channel.postMessage({ kind: "present", tab: TAB_ID, probe: message.probe });
        }
    });
}

async function noOtherTabResponds() {
    if (!channel) {
        return false;
    }
    const probe = `${TAB_ID}-${Math.random()}`;
    return new Promise((resolve) => {
        let sawAnotherTab = false;
        const onMessage = (event) => {
            if (event.data?.kind === "present" && event.data.probe === probe) {
                sawAnotherTab = true;
            }
        };
        channel.addEventListener("message", onMessage);
        channel.postMessage({ kind: "probe", tab: TAB_ID, probe });
        setTimeout(() => {
            channel.removeEventListener("message", onMessage);
            resolve(!sawAnotherTab);
        }, 450);
    });
}

patch(PosStore.prototype, {
    async reloadData(fullReload = false) {
        const orders = this.models["pos.order"].getAll();
        this.device.saveUnusedNumber(orders);

        const current = this.device?.data;
        const parsedNext = Number(current?.next_number);
        const preservedSequence = current?.device_identifier
            ? {
                  device_identifier: String(current.device_identifier),
                  next_number: Number.isSafeInteger(parsedNext) && parsedNext > 0 ? parsedNext : 1,
                  unsynced_number_stack: [],
              }
            : null;

        // Only the latest, completely empty, unsynced local draft may be reused.
        // A server query or another-window probe failure NEVER rolls the number back.
        if (preservedSequence && this.config?.id && String(this.config.id) === POS_ID) {
            const year = String(new Date().getFullYear()).slice(-2);
            const prefix = `${year}${preservedSequence.device_identifier}-${POS_ID}-`;
            const eligible = chooseReclaimableDraft({
                orders,
                nextNumber: preservedSequence.next_number,
                prefix,
            });
            if (eligible) {
                try {
                    const soleTab = await noOtherTabResponds();
                    if (soleTab) {
                        const available = await this.data.call(
                            "pos.order",
                            "flexsys_can_recycle_empty_draft_ref",
                            [eligible.reference, this.config.id]
                        );
                        // Check no new number was allocated during the async check.
                        const latest = this.device.data;
                        if (
                            available === true &&
                            latest?.device_identifier === preservedSequence.device_identifier &&
                            Number(latest?.next_number) === preservedSequence.next_number
                        ) {
                            preservedSequence.next_number = eligible.number;
                        }
                    }
                } catch (error) {
                    console.info("FlexSys: kept the higher POS counter (draft reuse not verified).", error);
                }
            }
        }

        await this.data.resetIndexedDB();
        sessionStorage.clear();
        localStorage.clear();

        if (preservedSequence) {
            // The patched device.save() also updates the durable cookie. Merely
            // changing localStorage would leave a higher stale cookie which
            // would undo the verified one-step rollback on the next POS startup.
            localStorage.setItem(
                DeviceIdentifierSequence.uniqueDeviceIdentifierKey,
                JSON.stringify(preservedSequence)
            );
            this.device.save(preservedSequence);
        }

        const url = new URL(window.location.href);
        if (fullReload) {
            url.searchParams.set("limited_loading", "0");
        }
        window.location.href = url.href;
    },
});
