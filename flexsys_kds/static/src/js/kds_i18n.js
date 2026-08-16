/** @odoo-module **/

/**
 * Static (non-data-driven) UI strings for the KDS screen.
 *
 * These were previously wrapped in _t() so they'd be picked up by
 * Odoo's translation extraction - reverted to plain literals after a
 * real, confirmed bug: `_t("NEW")` happened to match an existing
 * Arabic translation already shipped somewhere in Odoo's own core
 * catalog for the generic word "New" (used constantly throughout
 * Odoo's UI), so it silently rendered as "جديد" while the other
 * labels (ALL, PREPARING, READY...) had no matching entry and stayed
 * in English - an inconsistent, confusing mix, and not something this
 * module can reliably prevent by wrapping in _t(), since Odoo's
 * translation lookup matches by source string across every loaded
 * catalog, not scoped to this module.
 *
 * Plain literals now guarantee this screen always shows the same
 * fixed English text regardless of the user's language, exactly
 * matching the public kiosk (which never used _t() at all, for the
 * same reason - see controllers/kds_kiosk.py). If proper Arabic (or
 * any other language) support for these specific labels is wanted
 * later, the safer path is a small dedicated glossary lookup local to
 * this module (like the *_label fields the backend controller already
 * computes for Selection values), not the shared Odoo-wide _t()
 * mechanism, which is what caused this collision in the first place.
 *
 * Anything that comes from a model Selection field (order type, priority,
 * order/line state, line_change) is unaffected by this - the backend
 * controller already returns a translated *_label for those from the
 * field definitions themselves (see controllers/kds.py::_selection_labels).
 */
export const KDS_LABELS = {
    connection: "Connection",
    online: "Online",
    offline: "Offline",
    printerOnline: "Printer Online",
    enterFullscreen: "Enter Fullscreen",
    exitFullscreen: "Exit Fullscreen",
    branchLabel: "Branch",
    timeLabel: "Time",

    filterAll: "ALL",
    filterNew: "NEW",
    filterPreparing: "PREPARING",
    filterReady: "READY",
    filterCompleted: "COMPLETED",
    filterCancelled: "CANCELLED",
    filterLate: "LATE",
    filterPriority: "PRIORITY",

    noOrders: "No orders for this filter.",

    actionStart: "START",
    actionReady: "READY",
    actionComplete: "COMPLETE",

    ordersLabel: "Orders",
    avgPrepLabel: "Avg. Prep",
    slaLabel: "SLA",
    itemsLabel: "items",

    filterAllOption: "All",
    orderTypeFilterLabel: "Order Type",
    priorityFilterLabel: "Priority",
    employeeFilterLabel: "Employee",
    companyFilterLabel: "Company",
    posConfigFilterLabel: "POS",

    orderTypeDineIn: "Dine In",
    orderTypeTakeAway: "Take Away",
    orderTypeDelivery: "Delivery",
    orderTypePickup: "Pickup",
    orderTypeDriveThru: "Drive Thru",

    priorityNormal: "Normal",
    priorityPriority: "Priority",
    priorityUrgent: "Urgent",
    priorityVip: "VIP",

    printDisabledTooltip: "Printing is not enabled for this station",
};
