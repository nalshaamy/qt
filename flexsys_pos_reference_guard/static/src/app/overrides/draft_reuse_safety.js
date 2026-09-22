/** @odoo-module **/

/**
 * A number may be reclaimed only when the POS has allocated it to exactly one
 * EMPTY local draft and it is the most recently allocated number. This is an
 * eligibility check, NOT proof that no other tab/server has the same number.
 * The caller must perform both the other-tab probe and a server check.
 */
export function chooseReclaimableDraft({ orders, nextNumber, prefix }) {
    if (!Number.isSafeInteger(nextNumber) || nextNumber <= 1 || !prefix) {
        return null;
    }
    const number = nextNumber - 1;
    const reference = `${prefix}${String(number).padStart(6, "0")}`;
    const matching = (orders || []).filter((order) => order?.pos_reference === reference);
    if (matching.length !== 1) {
        return null;
    }
    const draft = matching[0];
    if (
        draft.isSynced ||
        draft.finalized ||
        draft.state !== "draft" ||
        !Array.isArray(draft.lines) || draft.lines.length !== 0 ||
        !Array.isArray(draft.payment_ids) || draft.payment_ids.length !== 0
    ) {
        return null;
    }
    // A pending paid/un-synced order or a different un-synced draft is reason
    // to avoid rolling back a shared sequence before wiping local databases.
    if ((orders || []).some((order) => order !== draft && !order.isSynced)) {
        return null;
    }
    return { number, reference, uuid: draft.uuid };
}
