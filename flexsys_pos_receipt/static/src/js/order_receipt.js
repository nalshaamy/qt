/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { localization } from "@web/core/l10n/localization";
import { onMounted, onPatched, useRef } from "@odoo/owl";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";

// Receipt presentation only. No change to currency setup or fiscal calculations.
// Switch to false to show Odoo's SR text instead of the new visual symbol.
const FLEX_SYS_RIYAL_SYMBOL_ENABLED = true;
const SYMBOL_URL = "/flexsys_pos_receipt/static/src/img/saudi_riyal_mark.svg";

function decorateReceiptCurrency(root) {
    if (!root || !FLEX_SYS_RIYAL_SYMBOL_ENABLED) return;
    const containers = root.querySelectorAll(
        ".orderline .product-price, .pos-receipt-taxes, .pos-receipt-amount, .paymentlines"
    );
    for (const container of containers) {
        const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
        const nodes = [];
        while (walker.nextNode()) nodes.push(walker.currentNode);
        for (const node of nodes) {
            const text = node.nodeValue;
            // Process numeric amounts only; do not modify product names or VAT numbers.
            if (!/(?:\d[\d,.]*\s*SR\b|\bSR\s*\d)/.test(text)) continue;
            const pattern = /\bSR\b/g;
            const fragment = document.createDocumentFragment();
            let start = 0;
            for (const match of text.matchAll(pattern)) {
                fragment.append(document.createTextNode(text.slice(start, match.index)));
                const icon = document.createElement("img");
                icon.className = "flexsys-riyal-symbol";
                icon.src = SYMBOL_URL;
                icon.alt = "SR";
                icon.setAttribute("aria-label", "Saudi Riyal");
                fragment.append(icon);
                start = match.index + match[0].length;
            }
            fragment.append(document.createTextNode(text.slice(start)));
            node.replaceWith(fragment);
        }
    }
}

patch(OrderReceipt.prototype, {
    setup() {
        super.setup(...arguments);
        this.flexsysReceiptEl = useRef("flexsysReceipt");
        onMounted(() => decorateReceiptCurrency(this.flexsysReceiptEl.el));
        onPatched(() => decorateReceiptCurrency(this.flexsysReceiptEl.el));
    },
    get flexsysIsArabic() {
        return localization.direction === "rtl";
    },
    flexsysTaxName(name) {
        if (this.flexsysIsArabic && typeof name === "string" && /^(VAT Taxes|VAT|Value Added Tax)$/i.test(name.trim())) {
            return "ضريبة القيمة المضافة";
        }
        return name;
    },
});
