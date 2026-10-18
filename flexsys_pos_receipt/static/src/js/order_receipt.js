/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { localization } from "@web/core/l10n/localization";
import { onMounted, onPatched, useRef } from "@odoo/owl";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";

// Only presentation logic. Monetary amounts and fiscal QR continue to come from Odoo.
// Visual-only receipt formatting. Switch to false if a device does not support U+20C1.
const FLEX_SYS_RIYAL_SYMBOL_ENABLED = true;
const SAUDI_RIYAL_SYMBOL = "\u20c1";
function decorateReceiptCurrency(root) {
    if (!FLEX_SYS_RIYAL_SYMBOL_ENABLED || !root) return;
    const containers = root.querySelectorAll(
        ".orderline .product-price, .pos-receipt-taxes, .pos-receipt-amount, .paymentlines"
    );
    for (const container of containers) {
        const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
        const textNodes = [];
        while (walker.nextNode()) textNodes.push(walker.currentNode);
        for (const node of textNodes) {
            // Only replace the currency label adjacent to a numeric price.
            // Do not alter text such as item names, VAT number or fiscal QR.
            const prior = node.nodeValue;
            const next = prior
                .replace(/(\d[\d,.]*)([ \u00a0]*)SR\b/g, `$1$2${SAUDI_RIYAL_SYMBOL}`)
                .replace(/\bSR([ \u00a0]*)(\d)/g, `${SAUDI_RIYAL_SYMBOL}$1$2`);
            if (next !== prior) node.nodeValue = next;
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
