/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import DeviceIdentifierSequence from "@point_of_sale/app/utils/devices_identifier_sequence";

/**
 * FlexSys guardrail for POS receipt numbering.
 *
 * Odoo normally keeps deleted/unused local order numbers in
 * unsynced_number_stack and may reuse them. In this installation the business
 * impact of a duplicate receipt/order number is higher than the impact of a
 * harmless gap in numbering, so allocated client numbers are never recycled.
 *
 * The server-side guard remains the final authority and repairs any duplicate
 * pos_reference that still reaches the backend.
 */
patch(DeviceIdentifierSequence.prototype, {
    useNext() {
        const data = this.data;
        if (!data) {
            return super.useNext(...arguments);
        }

        const parsed = Number(data.next_number);
        const number = Number.isInteger(parsed) && parsed > 0 ? parsed : 1;

        this.save({
            device_identifier: data.device_identifier,
            next_number: number + 1,
            unsynced_number_stack: [],
        });
        return number;
    },

    saveUnusedNumber(_orders) {
        const data = this.data;
        if (!data) {
            return;
        }

        // Intentionally discard reusable numbers. Gaps are safe; duplicate
        // customer-facing receipt/order numbers are not.
        if ((data.unsynced_number_stack || []).length) {
            this.save({
                device_identifier: data.device_identifier,
                next_number: data.next_number,
                unsynced_number_stack: [],
            });
        }
    },
});
