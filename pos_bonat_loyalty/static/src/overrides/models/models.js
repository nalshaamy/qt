/** @odoo-module */

import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { patch } from "@web/core/utils/patch";

patch(PosOrder.prototype, {
    setup(vals) {
        super.setup(...arguments);
        this.appliedCode = vals.appliedCode || this.appliedCode || '';
        this.bonat_merchant_id = vals.bonat_merchant_id || this.bonat_merchant_id || this.config?.company_id?.bonat_merchant_id || this.pos?.company?.bonat_merchant_id || '';
        this.bonat_merchant_name = vals.bonat_merchant_name || this.bonat_merchant_name || this.config?.company_id?.bonat_merchant_name || this.pos?.company?.bonat_merchant_name || '';
        this.bonatVoucherMethod = vals.bonatVoucherMethod || this.bonatVoucherMethod || '';
        this.bonatVoucherAmount = vals.bonatVoucherAmount || this.bonatVoucherAmount || 0;
        this.bonatVoucherCurrency = vals.bonatVoucherCurrency || this.bonatVoucherCurrency || '';
    },
    serialize(options) {
        const json = super.serialize(...arguments);
        json.appliedCode = this.get_applied_bonat_code();
        json.bonat_merchant_id = this.get_bonat_merchant_id();
        json.bonat_merchant_name = this.get_bonat_merchant_name();
        json.bonatVoucherMethod = this.bonatVoucherMethod || '';
        json.bonatVoucherAmount = this.bonatVoucherAmount || 0;
        json.bonatVoucherCurrency = this.bonatVoucherCurrency || '';
        return json;
    },
    export_for_printing(baseUrl, headerData) {
        const result = super.export_for_printing(...arguments);
        result.appliedCode = this.get_applied_bonat_code() || '';
        result.bonat_merchant_id = this.get_bonat_merchant_id() || '';
        result.bonat_merchant_name = this.get_bonat_merchant_name() || '';
        result.bonatVoucherMethod = this.bonatVoucherMethod || '';
        result.bonatVoucherAmount = this.bonatVoucherAmount || 0;
        result.bonatVoucherCurrency = this.bonatVoucherCurrency || '';
        return result;
    },
    set_applied_bonat_code(code) {
        this.appliedCode = code;
    },
    set_bonat_merchant_id(bonat_merchant_id) {
        this.bonat_merchant_id = bonat_merchant_id;
    },
    set_bonat_merchant_name(bonat_merchant_name) {
        this.bonat_merchant_name = bonat_merchant_name;
    },
    get_applied_bonat_code() {
        return this.appliedCode;
    },
    get_bonat_merchant_id() {
        return this.bonat_merchant_id;
    },
    get_bonat_merchant_name() {
        return this.bonat_merchant_name;
    },
    set_bonat_voucher(method, amount, currency) {
        this.bonatVoucherMethod = method || '';
        this.bonatVoucherAmount = amount || 0;
        this.bonatVoucherCurrency = currency || '';
    },
    get_bonat_voucher_method() {
        return this.bonatVoucherMethod || '';
    },
    get_bonat_voucher_amount() {
        return this.bonatVoucherAmount || 0;
    },
    get_bonat_voucher_currency() {
        return this.bonatVoucherCurrency || '';
    },
    clear_bonat_voucher() {
        this.bonatVoucherMethod = '';
        this.bonatVoucherAmount = 0;
        this.bonatVoucherCurrency = '';
        this.appliedCode = '';
    },
});

patch(PosOrderline.prototype, {
    setup(vals) {
        super.setup(...arguments);
        this.discountAmount = vals.discountAmount || this.discountAmount || "";
        this.isPercentage = vals.isPercentage || this.isPercentage || "";
        this.maxDiscountAmt = vals.maxDiscountAmt || this.maxDiscountAmt || "";
        this.response_data_type_2 = vals.response_data_type_2 || this.response_data_type_2 || "";
        this.percentage_partial_discount = vals.percentage_partial_discount || this.percentage_partial_discount || false;
        this.fix_amt_partial_disc = vals.fix_amt_partial_disc || this.fix_amt_partial_disc || false;
        this.allowedQty = vals.allowedQty || this.allowedQty || 0;
        this.qtyApplied = vals.qtyApplied || this.qtyApplied || 0;
        this.percentage_qty_applied = vals.percentage_qty_applied || this.percentage_qty_applied || 0;
        this.disc_applied = vals.disc_applied || this.disc_applied || 0;
        this.base_unit_price = vals.base_unit_price || this.base_unit_price || 0;
    },
    set_discountAmount(discountAmount) {
        this.discountAmount = discountAmount;
    },
    set_isPercentage(isPercentage) {
        this.isPercentage = isPercentage;
    },
    set_maxDiscountAmt(maxDiscountAmt) {
        this.maxDiscountAmt = maxDiscountAmt;
    },
    set_response_data_type_2(response_data_type_2) {
        this.response_data_type_2 = response_data_type_2;
    },
    set_percentage_partial_discount(percentage_partial_discount) {
        this.percentage_partial_discount = percentage_partial_discount;
    },
    set_fix_amt_partial_disc(fix_amt_partial_disc) {
        this.fix_amt_partial_disc = fix_amt_partial_disc;
    },
    set_allowedQty(allowedQty) {
        this.allowedQty = allowedQty;
    },
    set_qty_applied(qtyApplied) {
        this.qtyApplied = qtyApplied;
    },
    set_percentage_qty_applied(percentage_qty_applied) {
        this.percentage_qty_applied = percentage_qty_applied;
    },
    set_disc_applied(disc_applied) {
        this.disc_applied = disc_applied;
    },
    set_base_unit_price(base_unit_price) {
        this.base_unit_price = base_unit_price;
    },
    get_base_unit_price() {
        return this.base_unit_price;
    },
    get_disc_applied() {
        return this.disc_applied;
    },
    get_percentage_qty_applied() {
        return this.percentage_qty_applied;
    },
    get_qty_applied() {
        return this.qtyApplied;
    },
    get_allowedQty() {
        return this.allowedQty;
    },
    get_fix_amt_partial_disc() {
        return this.fix_amt_partial_disc;
    },
    get_percentage_partial_discount() {
        return this.percentage_partial_discount;
    },
    get_response_data_type_2() {
        return this.response_data_type_2;
    },
    get_discountAmount() {
        return this.discountAmount;
    },
    get_isPercentage() {
        return this.isPercentage;
    },
    get_maxDiscountAmt() {
        return this.maxDiscountAmt;
    },
    getDisplayData() {
        return {
            ...super.getDisplayData(...arguments),
            maxDiscountAmt: this.maxDiscountAmt || "",
            discountAmount: this.discountAmount || "",
            percentage_partial_discount: this.percentage_partial_discount || "",
            fix_amt_partial_disc: this.fix_amt_partial_disc || "",
            allowedQty: this.allowedQty || "",
            qtyApplied: this.qtyApplied || "",
            percentage_qty_applied: this.percentage_qty_applied || "",
            disc_applied: this.disc_applied || "",
            base_unit_price: this.base_unit_price || "",
        };
    },
    get_all_prices(qty = this.get_quantity()) {
        const maxDiscountAmt = this.get_maxDiscountAmt();
        const allowedQty = this.get_allowedQty();
        const isPercentage = this.get_isPercentage();
        const response_data_type_2 = this.get_response_data_type_2();
        const discountAmount = this.get_discountAmount();
        const fix_amt_partial_disc = this.get_fix_amt_partial_disc();
        const percentage_partial_discount = this.get_percentage_partial_discount();

        if (response_data_type_2 && isPercentage && percentage_partial_discount) {
            const price_unit = this.get_unit_price();
            let taxtotal = 0;
            let taxdetail = {};

            const product = this.get_product();
            const taxes_ids = (this.tax_ids || product.taxes_id).filter((t) => t in this.pos.taxes_by_id);
            const product_taxes = this.pos.get_taxes_after_fp(taxes_ids, this.order.fiscal_position);

            const all_taxes_before_discount = this.compute_all(
                product_taxes,
                price_unit,
                qty,
                this.pos.currency.rounding
            );

            let totalIncluded = 0;
            let totalExcluded = 0;

            if (qty > allowedQty) {
                let discountForApplicableQty = (discountAmount / 100) * price_unit * allowedQty;

                if (discountForApplicableQty > maxDiscountAmt) {
                    discountForApplicableQty = maxDiscountAmt;
                }
                const discountedUnitPrice = price_unit - (discountForApplicableQty / allowedQty);

                const taxesForDiscountedQty = this.compute_all(
                    product_taxes,
                    discountedUnitPrice,
                    allowedQty,
                    this.pos.currency.rounding
                );

                const remainingQty = qty - allowedQty;
                const taxesForRemainingQty = this.compute_all(
                    product_taxes,
                    price_unit,
                    remainingQty,
                    this.pos.currency.rounding
                );

                totalIncluded = taxesForDiscountedQty.total_included + taxesForRemainingQty.total_included;
                totalExcluded = taxesForDiscountedQty.total_excluded + taxesForRemainingQty.total_excluded;

                const combinedTaxes = [...taxesForDiscountedQty.taxes, ...taxesForRemainingQty.taxes];
                combinedTaxes.forEach(function(tax) {
                    taxtotal += tax.amount;
                    if (taxdetail[tax.id]) {
                        taxdetail[tax.id].amount += tax.amount;
                        taxdetail[tax.id].base += tax.base;
                    } else {
                        taxdetail[tax.id] = {
                            amount: tax.amount,
                            base: tax.base,
                        };
                    }
                });
            } else {
                const discountedUnitPrice = this.get_unit_price() * (1.0 - this.get_discount() / 100.0);
                const all_taxes_after_discount = this.compute_all(
                    product_taxes,
                    discountedUnitPrice,
                    qty,
                    this.pos.currency.rounding
                );

                totalIncluded = all_taxes_after_discount.total_included;
                totalExcluded = all_taxes_after_discount.total_excluded;

                all_taxes_after_discount.taxes.forEach(function(tax) {
                    taxtotal += tax.amount;
                    taxdetail[tax.id] = {
                        amount: tax.amount,
                        base: tax.base,
                    };
                });
            }

            const discountTax = all_taxes_before_discount.total_included - totalIncluded;
            return {
                priceWithTax: totalIncluded,
                priceWithoutTax: totalExcluded,
                priceWithTaxBeforeDiscount: all_taxes_before_discount.total_included,
                priceWithoutTaxBeforeDiscount: all_taxes_before_discount.total_excluded,
                tax: taxtotal,
                taxDetails: taxdetail,
            };
        } else if (response_data_type_2 && !isPercentage && fix_amt_partial_disc) {
            const price_unit = this.get_unit_price();
            let taxtotal = 0;
            let taxdetail = {};

            const product = this.get_product();
            const taxes_ids = (this.tax_ids || product.taxes_id).filter((t) => t in this.pos.taxes_by_id);
            const product_taxes = this.pos.get_taxes_after_fp(taxes_ids, this.order.fiscal_position);

            const all_taxes_before_discount = this.compute_all(
                product_taxes,
                this.get_unit_price(),
                qty,
                this.pos.currency.rounding
            );

            let totalIncluded = 0;
            let totalExcluded = 0;

            if (qty > allowedQty) {
                const totalDiscount = Math.min(discountAmount * allowedQty, maxDiscountAmt);
                const discountedUnitPrice = price_unit - (totalDiscount / allowedQty);

                const taxesForDiscountedQty = this.compute_all(
                    product_taxes,
                    discountedUnitPrice,
                    allowedQty,
                    this.pos.currency.rounding
                );
                const remainingQty = qty - allowedQty;
                const taxesForRemainingQty = this.compute_all(
                    product_taxes,
                    price_unit,
                    remainingQty,
                    this.pos.currency.rounding
                );

                totalIncluded = taxesForDiscountedQty.total_included + taxesForRemainingQty.total_included;
                totalExcluded = taxesForDiscountedQty.total_excluded + taxesForRemainingQty.total_excluded;

                const combinedTaxes = [...taxesForDiscountedQty.taxes, ...taxesForRemainingQty.taxes];
                combinedTaxes.forEach(function(tax) {
                    taxtotal += tax.amount;
                    if (taxdetail[tax.id]) {
                        taxdetail[tax.id].amount += tax.amount;
                        taxdetail[tax.id].base += tax.base;
                    } else {
                        taxdetail[tax.id] = {
                            amount: tax.amount,
                            base: tax.base,
                        };
                    }
                });
            } else {
                const discountedUnitPrice = this.get_unit_price() * (1.0 - this.get_discount() / 100.0);
                const all_taxes_after_discount = this.compute_all(
                    product_taxes,
                    discountedUnitPrice,
                    qty,
                    this.pos.currency.rounding
                );

                totalIncluded = all_taxes_after_discount.total_included;
                totalExcluded = all_taxes_after_discount.total_excluded;

                all_taxes_after_discount.taxes.forEach(function(tax) {
                    taxtotal += tax.amount;
                    taxdetail[tax.id] = {
                        amount: tax.amount,
                        base: tax.base,
                    };
                });
            }

            const discountTax = all_taxes_before_discount.total_included - totalIncluded;

            return {
                priceWithTax: totalIncluded,
                priceWithoutTax: totalExcluded,
                priceWithTaxBeforeDiscount: all_taxes_before_discount.total_included,
                priceWithoutTaxBeforeDiscount: all_taxes_before_discount.total_excluded,
                tax: taxtotal,
                taxDetails: taxdetail,
            };
        } else {
            var price_unit = this.get_unit_price() * (1.0 - this.get_discount() / 100.0);
            var taxtotal = 0;

            var product = this.get_product();
            var taxes_ids = this.tax_ids || product.taxes_id;
            taxes_ids = taxes_ids.filter((t) => t in this.pos.taxes_by_id);
            var taxdetail = {};
            var product_taxes = this.pos.get_taxes_after_fp(taxes_ids, this.order.fiscal_position);

            var all_taxes = this.compute_all(
                product_taxes,
                price_unit,
                qty,
                this.pos.currency.rounding
            );
            var all_taxes_before_discount = this.compute_all(
                product_taxes,
                this.get_unit_price(),
                qty,
                this.pos.currency.rounding
            );
            all_taxes.taxes.forEach(function(tax) {
                taxtotal += tax.amount;
                taxdetail[tax.id] = {
                    amount: tax.amount,
                    base: tax.base,
                };
            });
            return {
                priceWithTax: all_taxes.total_included,
                priceWithoutTax: all_taxes.total_excluded,
                priceWithTaxBeforeDiscount: all_taxes_before_discount.total_included,
                priceWithoutTaxBeforeDiscount: all_taxes_before_discount.total_excluded,
                tax: taxtotal,
                taxDetails: taxdetail,
            };
        }
    }
});
