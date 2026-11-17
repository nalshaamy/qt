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
    logo_width_mm: 72,
    logo_trim_whitespace: true,
    header_width_mm: 48,
    footer_width_mm: 36,
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
    const cached = settingsCache.get(configId);
    // Allow campaigns configured in backend to update without a permanent
    // page-long cache. Printer can still use fallback data while offline.
    if (cached && Date.now() - cached.fetchedAt < 15_000) return cached.promise;
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
            // Defense in depth: never interpolate untrusted strings into CSS dimensions.
            const rawWidth = Number(settings.logo_width_mm);
            settings.logo_width_mm = Number.isFinite(rawWidth)
                ? Math.max(30, Math.min(72, Math.round(rawWidth)))
                : 72;
            for (const [key, fallback] of [["header_width_mm", 48], ["footer_width_mm", 36]]) {
                const width = Number(settings[key]);
                settings[key] = Number.isFinite(width)
                    ? Math.max(20, Math.min(72, Math.round(width))) : fallback;
            }
            settings.logo_trim_whitespace = settings.logo_trim_whitespace === true;
            await Promise.all([waitForImage(settings.header_image), waitForImage(settings.footer_image)]);
            return settings;
        } catch (error) {
            // Offline POS can still print the native fiscal receipt without promos.
            return DEFAULT_SETTINGS;
        } finally {
            clearTimeout(timeout);
        }
    })();
    settingsCache.set(configId, { promise, fetchedAt: Date.now() });
    return promise;
}

/* The ZATCA extension may insert its QR between sibling images after QWeb
 * inheritance runs. Reposition the already rendered promo relative to the
 * original receipt logo, without moving or modifying the fiscal QR itself. */
function positionHeaderPromo(root, settings) {
    if (!root || !settings?.header_enabled) return;
    const logo = root.querySelector("img.pos-receipt-logo");
    const promo = root.querySelector(".flexsys-header-promo");
    if (!logo || !promo || !logo.parentNode) return;
    if (settings.header_position === "below") {
        if (logo.nextSibling !== promo) logo.parentNode.insertBefore(promo, logo.nextSibling);
    } else if (logo.previousSibling !== promo) {
        logo.parentNode.insertBefore(promo, logo);
    }
}

/* Crop optical whitespace only in the displayed receipt image. Never write
 * to res.company, pos.config, or the native logo asset. Gracefully revert to
 * the original URL on CORS/canvas errors or a missing image. */
const trimmedLogoCache = new Map();
function cropReceiptLogo(src) {
    if (!src) return Promise.resolve(src);
    if (trimmedLogoCache.has(src)) return trimmedLogoCache.get(src);
    const job = new Promise((resolve) => {
        const image = new Image();
        let finished = false;
        const finish = (value) => {
            if (finished) return;
            finished = true;
            clearTimeout(timer);
            resolve(value);
        };
        const timer = setTimeout(() => finish(src), 1300);
        image.onerror = () => finish(src);
        image.onload = () => {
            try {
                const iw = image.naturalWidth;
                const ih = image.naturalHeight;
                if (!iw || !ih || iw > 4000 || ih > 4000) return finish(src);
                const factor = Math.min(1, 1024 / Math.max(iw, ih));
                const width = Math.max(1, Math.round(iw * factor));
                const height = Math.max(1, Math.round(ih * factor));
                const canvas = document.createElement("canvas");
                canvas.width = width;
                canvas.height = height;
                const context = canvas.getContext("2d", { willReadFrequently: true });
                if (!context) return finish(src);
                context.drawImage(image, 0, 0, width, height);
                const rgba = context.getImageData(0, 0, width, height).data;
                let minX = width, minY = height, maxX = -1, maxY = -1;
                for (let y = 0; y < height; y++) {
                    for (let x = 0; x < width; x++) {
                        const offset = (y * width + x) * 4;
                        const alpha = rgba[offset + 3];
                        if (alpha < 35) continue;
                        const lightness = (rgba[offset] + rgba[offset + 1] + rgba[offset + 2]) / 3;
                        if (lightness >= 237) continue;
                        minX = Math.min(minX, x);
                        maxX = Math.max(maxX, x);
                        minY = Math.min(minY, y);
                        maxY = Math.max(maxY, y);
                    }
                }
                if (maxX < 0 || maxY < 0) return finish(src);
                const padding = 2;
                minX = Math.max(0, minX - padding);
                minY = Math.max(0, minY - padding);
                maxX = Math.min(width - 1, maxX + padding);
                maxY = Math.min(height - 1, maxY + padding);
                const cropW = maxX - minX + 1, cropH = maxY - minY + 1;
                // Avoid touching logos that already use most of their canvas.
                if (cropW >= width * .92 && cropH >= height * .92) return finish(src);
                // Avoid blowing up tiny noise / low-quality source images.
                if (cropW < width * .12 || cropH < height * .12) return finish(src);
                const output = document.createElement("canvas");
                output.width = cropW;
                output.height = cropH;
                output.getContext("2d").drawImage(canvas, minX, minY, cropW, cropH, 0, 0, cropW, cropH);
                finish(output.toDataURL("image/png"));
            } catch (error) {
                finish(src);
            }
        };
        image.src = src;
    });
    trimmedLogoCache.set(src, job);
    return job;
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
        onMounted(() => {
            positionHeaderPromo(this.flexsysReceiptEl.el, this.flexsysSettings);
            decorateReceiptCurrency(this.flexsysReceiptEl.el, this.flexsysSettings);
        });
        onPatched(() => {
            positionHeaderPromo(this.flexsysReceiptEl.el, this.flexsysSettings);
            decorateReceiptCurrency(this.flexsysReceiptEl.el, this.flexsysSettings);
        });
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
        this.flexsysTrimmedLogoUrl = null;
        onWillStart(async () => {
            this.flexsysSettings = await getReceiptSettings(this.order?.config?.id);
            if (this.flexsysSettings.logo_trim_whitespace) {
                this.flexsysTrimmedLogoUrl = await cropReceiptLogo(this.logoUrl);
            }
        });
    },
    get flexsysReceiptLogoSrc() {
        return this.flexsysTrimmedLogoUrl || this.logoUrl;
    },
    get flexsysIsArabic() {
        return localization.direction === "rtl";
    },
});
