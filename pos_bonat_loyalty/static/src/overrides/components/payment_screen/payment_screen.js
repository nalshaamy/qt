/** @odoo-module */

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { patch } from "@web/core/utils/patch";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";

patch(PaymentScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = useService("orm");
    },

    async validateOrder(isForceValidate) {
        const order = this.pos.getOrder();
        const bonat_code = order.get_applied_bonat_code();
        const bonat_merchant_id = order.get_bonat_merchant_id();
        const bonat_merchant_name = order.get_bonat_merchant_name();
        const branch_id = this.pos.config.name;
        const branch_name = this.pos.config.name;
        const session_id = String(this.pos.session.id);
        const session_name = this.pos.session.display_name || this.pos.session.name;
        const customer = order.getPartner() || {};
        const customer_id = customer.id || null;
        const customer_name = customer.name || "Guest";
        let customer_phone = "";
        let dial_code = '';

        if (customer && customer.phone) {
            let cleanedNumber = customer.phone.replace(/\D/g, '');
            if (cleanedNumber.length === 12) {
                customer_phone = '9665' + cleanedNumber.slice(4);
                dial_code = '9665';
            } else if (cleanedNumber.length === 10) {
                customer_phone = '05' + cleanedNumber.slice(2);
                dial_code = '05';
            } else if (cleanedNumber.length === 9) {
                customer_phone = '5' + cleanedNumber.slice(1);
                dial_code = '5';
            }
        }
        const customer_email = customer.email || "";

        const products = order.getOrderlines().map((line) => {
            const product = line.product_id;
            return {
                product: {
                    category: {
                        id: product.categ_id?.id ?? product.categ_id?.[0] ?? product.pos_categ_ids?.[0]?.id ?? null,
                        name: product.categ_id?.name ?? product.categ_id?.[1] ?? product.pos_categ_ids?.[0]?.name ?? "Unknown",
                    },
                    id: product.id,
                    name: product.display_name || "Unnamed Product",
                    price: line.price_unit || 0,
                },
                quantity: line.getQuantity?.() ?? 0,
                unit_price: line.price_unit || 0,
                total_price: line.displayPrice || 0,
            };
        });

        const taxes = order.getOrderlines().map((orderLine) => {
            return (orderLine.tax_ids || []).map((tax) => ({
                id: tax.id,
                name: tax.name,
                rate: tax.amount,
            }));
        }).flat();

        const subtotal_price = parseFloat(order.priceExcl || 0).toFixed(2);
        const amount_tax = parseFloat(order.amountTaxes || 0).toFixed(2);
        const amount_total = parseFloat(order.priceIncl || 0).toFixed(2);

        const timestamp = Math.floor(Date.now() / 1000);
        const order_creation_data = {
            timestamp: timestamp,
            event: "order.created",
            business: {
                name: bonat_merchant_name,
                reference: bonat_merchant_id,
            },
            order: {
                order_id: parseInt(order.tracking_number, 10) || 0,
                branch: {
                    id: branch_id,
                    name: branch_name,
                },
                pos: {
                    id: session_id,
                    name: session_name,
                },
                taxes: taxes,
                products: products,
                quantity: order.getOrderlines().reduce((sum, line) => sum + (line.getQuantity?.() ?? 0), 0),
                subtotal_price: parseFloat(subtotal_price),
                amount_tax: parseFloat(amount_tax),
                total_price: parseFloat(amount_total),
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
            },
        };

        if (customer && customer.id) {
            order_creation_data.order.customer = {
                id: customer_id ? String(customer_id) : "0",
                name: customer_name,
                dial_code: parseInt(dial_code || ''),
                phone: customer_phone,
                email: customer_email,
            };
        }
        const { orm, dialog } = this.env.services;
        if (bonat_code && bonat_code.length) {
            const redeem_data = {
                reward_code: bonat_code,
                merchant_id: bonat_merchant_id,
                branch_id: branch_id,
                date: new Date().toISOString(),
                timestamp: Math.floor(Date.now() / 1000),
            };

            const data = await orm.call(
                "pos.session",
                "pos_reward_redeem",
                [redeem_data],
            );
            if (!data.success) {
                dialog.add(AlertDialog, {
                    title: _t("Error validating"),
                    body: data.error || _t("Failed to redeem Bonat code."),
                });
            }
        }
        await this._finalizeOrderCreation(order_creation_data);
        await super.validateOrder(...arguments);
    },

    async _finalizeOrderCreation(order_creation_data) {
        const { orm } = this.env.services;
        const response = await orm.call(
            "pos.session",
            "pos_order_creation_request",
            [order_creation_data]
        );

        if (response.success) {
            console.log("Order creation success:", response);
        }
    }
});
