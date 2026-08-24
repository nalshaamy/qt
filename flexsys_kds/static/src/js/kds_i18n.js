/** @odoo-module **/

/**
 * Static (non-data-driven) UI strings for the KDS screen.
 *
 * REAL BUG FIX, confirmed live: these were previously wrapped in _t()
 * so they'd be picked up by Odoo's translation extraction - reverted
 * to plain literals after a confirmed collision: `_t("NEW")` happened
 * to match an existing Arabic translation already shipped somewhere in
 * Odoo's own core catalog for the generic word "New" (used constantly
 * throughout Odoo's UI), so it silently rendered as "جديد" while the
 * other labels (ALL, PREPARING, READY...) had no matching entry and
 * stayed in English - an inconsistent, confusing mix, and not
 * something this module could reliably prevent by wrapping in _t(),
 * since Odoo's translation lookup matches by source string across
 * every loaded catalog, not scoped to this module.
 *
 * LOCALIZATION ARCHITECTURE ("Arabic Localization & RTL Specification",
 * item 3, "Internal KDS Translation"): implemented exactly as that
 * earlier fix's own comment anticipated - "a small dedicated glossary
 * lookup local to this module... not the shared Odoo-wide _t()
 * mechanism, which is what caused this collision in the first place."
 * Two complete, namespaced dictionaries below (KDS_LABELS_EN/
 * KDS_LABELS_AR), selected by getKdsLabels(lang) based on the logged-in
 * Odoo user's own active language (kds_app.js's own `user` service,
 * `.lang` - never inferred from the browser) - immune to Odoo's own
 * global translation catalog by construction, since these keys
 * (`filterNew`, `statusReady`, etc.) never pass through _t()/the
 * shared catalog lookup at all. Adding a third language later means
 * adding a third dictionary object and one more case in
 * getKdsLabels() - no rewrite of this module's own call sites, which
 * only ever read `this.labels.someKey`, never the raw English/Arabic
 * string directly.
 *
 * Anything that comes from a model Selection field (order type, priority,
 * order/line state, line_change) is unaffected by this - the backend
 * controller already returns a translated *_label for those from the
 * field definitions themselves (see controllers/kds.py::_selection_labels).
 */
export const KDS_LABELS_EN = {
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
    wasStage: "was",
    filterLate: "LATE",

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
    employeeFilterLabel: "Employee",
    companyFilterLabel: "Company",
    posConfigFilterLabel: "POS",

    orderTypeDineIn: "Dine In",
    orderTypeTakeAway: "Take Away",
    orderTypeDelivery: "Delivery",
    orderTypePickup: "Pickup",
    orderTypeDriveThru: "Drive Thru",

    printDisabledTooltip: "Printing is not enabled for this station",
};

// LOCALIZATION ("Arabic Localization & RTL Specification"), item 6,
// "Approved Arabic Terminology": every value below uses the client's
// own approved terminology table exactly (Ready=جاهز, Completed=مكتمل,
// Cancelled=ملغى, Station=محطة, Printer=طابعة, POS=نقطة البيع,
// Employee=الموظف, Branch=الفرع, Company=الشركة, Fullscreen=ملء الشاشة,
// "No orders for this filter."=لا توجد طلبات لهذا الفلتر.) - the same
// exact keys as KDS_LABELS_EN above, so getKdsLabels() can swap the
// whole object safely with zero call-site changes anywhere.
export const KDS_LABELS_AR = {
    connection: "الاتصال",
    online: "متصل",
    offline: "غير متصل",
    printerOnline: "الطابعة متصلة",
    enterFullscreen: "فتح ملء الشاشة",
    exitFullscreen: "الخروج من ملء الشاشة",
    branchLabel: "الفرع",
    timeLabel: "الوقت",

    filterAll: "الكل",
    filterNew: "جديد",
    filterPreparing: "قيد التحضير",
    filterReady: "جاهز",
    filterCompleted: "مكتمل",
    filterCancelled: "ملغى",
    wasStage: "كان",
    filterLate: "متأخر",

    noOrders: "لا توجد طلبات لهذا الفلتر.",

    actionStart: "بدء",
    actionReady: "جاهز",
    actionComplete: "إكمال",

    ordersLabel: "الطلبات",
    avgPrepLabel: "متوسط التحضير",
    slaLabel: "SLA",
    itemsLabel: "أصناف",

    filterAllOption: "الكل",
    orderTypeFilterLabel: "نوع الطلب",
    employeeFilterLabel: "الموظف",
    companyFilterLabel: "الشركة",
    posConfigFilterLabel: "نقطة البيع",

    orderTypeDineIn: "صالة",
    orderTypeTakeAway: "طلب خارجي",
    orderTypeDelivery: "توصيل",
    orderTypePickup: "استلام",
    orderTypeDriveThru: "طلب من السيارة",

    printDisabledTooltip: "الطباعة غير مفعّلة لهذه المحطة",
};

// LOCALIZATION, item 5, "Language Source - Internal KDS: Use the
// logged-in Odoo user's active language... Do not infer language from
// browser text direction alone." Called from kds_app.js's own setup()
// with the real Odoo `user` service's own `.lang` (e.g. "en_US",
// "ar_001", "ar_SA") - never the browser's own `navigator.language` or
// any `dir` attribute. Unrecognized/future languages fall back to
// English rather than failing - the same fail-safe default this
// module already relies on elsewhere.
export function getKdsLabels(lang) {
    if (typeof lang === "string" && lang.startsWith("ar")) {
        return KDS_LABELS_AR;
    }
    return KDS_LABELS_EN;
}

// Backward-compatible default export - kept exactly as before for any
// code path that hasn't been updated to call getKdsLabels(lang) yet;
// always resolves to English, matching the original, pre-localization
// behavior exactly.
export const KDS_LABELS = KDS_LABELS_EN;
