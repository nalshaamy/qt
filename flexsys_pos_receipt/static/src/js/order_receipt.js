/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { localization } from "@web/core/l10n/localization";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";

// Only presentation logic. Monetary amounts and fiscal QR continue to come from Odoo.
patch(OrderReceipt.prototype, {
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
