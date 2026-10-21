/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { localization } from "@web/core/l10n/localization";
import { onMounted, onPatched, onWillStart, useRef } from "@odoo/owl";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";
import { ReceiptHeader } from "@point_of_sale/app/screens/receipt_screen/receipt/receipt_header/receipt_header";

// Keep all POS startup/model loading paths untouched. Fetch display-only settings
// once, lazily, when an actual receipt component is about to render.
const FLEX_SYS_RIYAL_SYMBOL_ENABLED = true;
const SYMBOL_URL = "/flexsys_pos_receipt/static/src/img/saudi_riyal_mark.svg";
const settingsCache = new Map();

const DEFAULT_SETTINGS = Object.freeze({
    show_company_footer: false,
    currency_symbol_mode: "new",
    header_enabled: false,
    header_position: "above",
    header_image: "",
    footer_enabled: false,
    footer_image: "",
    thank_you_enabled: false,
    thank_you_ar: "",
    thank_you_en: "",
});

function waitForImage(src) {
    if (!src) return Promise.resolve();
    return new Promise((resolve) => {
        const image = new Image();
        let finished = false;
        const finish = () => {
            if (finished) return;
            finished = true;
            clearTimeout(timeout);
            resolve();
        };
        const timeout = setTimeout(finish, 1500);
        image.onload = finish;
        image.onerror = finish;
        image.src = src;
        if (image.complete) finish();
    });
}

async function getReceiptSettings(configId) {
    if (!Number.isInteger(configId) || configId <= 0) return DEFAULT_SETTINGS;
    if (settingsCache.has(configId)) return settingsCache.get(configId);
    const promise = (async () => {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 2500);
        try {
            const response = await fetch(`/flexsys_pos_receipt/settings/${configId}`, {
                credentials: "same-origin", cache: "no-store", signal: controller.signal,
            });
            if (!response.ok) return DEFAULT_SETTINGS;
            const result = await response.json();
            if (!result || typeof result !== "object") return DEFAULT_SETTINGS;
            const settings = { ...DEFAULT_SETTINGS, ...result };
            await Promise.all([waitForImage(settings.header_image), waitForImage(settings.footer_image)]);
            return settings;
        } catch (error) {
            // Offline POS can still print the native fiscal receipt without promos.
            return DEFAULT_SETTINGS;
        } finally {
            clearTimeout(timeout);
        }
    })();
    settingsCache.set(configId, promise);
    return promise;
}

function decorateReceiptCurrency(root, settings) {
    if (!root || !FLEX_SYS_RIYAL_SYMBOL_ENABLED || settings?.currency_symbol_mode === "sr") return;
    const containers = root.querySelectorAll(
        ".orderline .product-price, .pos-receipt-taxes, .pos-receipt-amount, .paymentlines"
    );
    for (const container of containers) {
        const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
        const nodes = [];
        while (walker.nextNode()) nodes.push(walker.currentNode);
        for (const node of nodes) {
            const content = node.nodeValue;
            if (!/(?:\d[\d,.]*\s*SR\b|\bSR\s*\d)/.test(content)) continue;
            const fragment = document.createDocumentFragment();
            let start = 0;
            for (const match of content.matchAll(/\bSR\b/g)) {
                fragment.append(document.createTextNode(content.slice(start, match.index)));
                const icon = document.createElement("img");
                icon.className = "flexsys-riyal-symbol";
                icon.src = SYMBOL_URL;
                icon.alt = "SR";
                icon.setAttribute("aria-label", "Saudi Riyal");
                fragment.append(icon);
                start = match.index + match[0].length;
            }
            fragment.append(document.createTextNode(content.slice(start)));
            node.replaceWith(fragment);
        }
    }
}

patch(OrderReceipt.prototype, {
    setup() {
        super.setup(...arguments);
        this.flexsysSettings = DEFAULT_SETTINGS;
        this.flexsysReceiptEl = useRef("flexsysReceipt");
        onWillStart(async () => {
            this.flexsysSettings = await getReceiptSettings(this.order?.config?.id);
        });
        onMounted(() => decorateReceiptCurrency(this.flexsysReceiptEl.el, this.flexsysSettings));
        onPatched(() => decorateReceiptCurrency(this.flexsysReceiptEl.el, this.flexsysSettings));
    },
    get flexsysIsArabic() {
        return localization.direction === "rtl";
    },
    get flexsysDisplayOrderNumber() {
        return this.order?.tracking_number || this.order?.pos_reference || "";
    },
    get flexsysThankYouMessage() {
        if (!this.flexsysSettings.thank_you_enabled) return "";
        return (this.flexsysIsArabic ? this.flexsysSettings.thank_you_ar : this.flexsysSettings.thank_you_en) || "";
    },
    flexsysTaxName(name) {
        if (this.flexsysIsArabic && typeof name === "string" && /^(VAT Taxes|VAT|Value Added Tax)$/i.test(name.trim())) {
            return "ضريبة القيمة المضافة";
        }
        return name;
    },
});

patch(ReceiptHeader.prototype, {
    setup() {
        if (typeof super.setup === "function") {
            super.setup(...arguments);
        }
        this.flexsysSettings = DEFAULT_SETTINGS;
        onWillStart(async () => {
            this.flexsysSettings = await getReceiptSettings(this.order?.config?.id);
        });
    },
    get flexsysIsArabic() {
        return localization.direction === "rtl";
    },
});
