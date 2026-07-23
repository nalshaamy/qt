/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { useService } from "@web/core/utils/hooks";
import { TextInputPopup } from "@point_of_sale/app/components/popups/text_input_popup/text_input_popup";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { Component } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { OrderlinePopup } from "@pos_bonat_loyalty/popup/orderline_popup";

export class BonatCodeButton extends Component {
    static template = "pos_bonat_loyalty.BonatCodeButton";

    setup() {
        this.pos = usePos();
        this.dialog = useService("dialog");
        this.orm = useService("orm");
    }

    async fetch_bonat_code() {
        // Capture env services before the first await: BonatCodeButton can be
        // destroyed by ControlButtons re-render while a popup is open (Odoo 19
        // lifecycle change), and useService-wrapped calls throw "Component is
        // destroyed" when invoked on a destroyed instance.
        const { orm, dialog } = this.env.services;
        const pos = this.pos;

        const code = await makeAwaitable(dialog, TextInputPopup, {
            title: _t("Enter Bonat Code"),
            startingValue: "",
            placeholder: _t("Bonat code"),
        });

        if (code) {
            const trimmedCode = code.trim();
            if (trimmedCode !== "") {

                const order = pos.getOrder();
                const products = order.getOrderlines().map((line) => ({
                    product_id: line.getProduct().id,
                    quantity: line.getQuantity(),
                }));

                const response = await orm.call(
                    "res.company",
                    "get_bonat_code_response",
                    [trimmedCode]
                );

                console.log("\n\n\n\n\n >>>>>>>>>>> reward code check response:", response);
                if (response.success) {
                    if (order) {
                        order.set_applied_bonat_code(trimmedCode);
                    }
                    if (response.data.method === "Voucher") {
                        order.set_bonat_voucher(
                            "Voucher",
                            response.data.discount_amount || 0,
                            response.data.currency || "",
                        );
                        return;
                    }
                    order.set_bonat_voucher("", 0, "");
                    if (response.data.type == 1) {
                        const discountAmount = response.data.discount_amount || 0;
                        const isPercentage = response.data.is_percentage || false;
                        const lines = order.getOrderlines();
                        // In Odoo 19, use models registry to get product
                        const discountProductId = pos.config.discount_product_id?.id || pos.config.discount_product_id;
                        const product = pos.models["product.product"].get(discountProductId);
                        if (product === undefined) {
                            await dialog.add(AlertDialog, {
                                title: _t("No discount product found"),
                                body: _t(
                                    "To apply a discount, please enable the 'Global Discounts' option in the Point of Sale settings and configure a discount product."
                                ),
                            });
                            return;
                        }
                        lines.filter((line) => line.getProduct() === product).forEach((line) => order.removeOrderline(line));

                        // Odoo 19: order.calculate_base_amount() was removed. Sum the untaxed
                        // base (priceExcl) of the discountable lines instead.
                        const baseToDiscount = lines
                            .filter((ll) => ll.isGlobalDiscountApplicable())
                            .reduce((sum, ll) => sum + ll.priceExcl, 0);

                        let discount = 0;
                        if (isPercentage) {
                            discount = (-discountAmount / 100) * baseToDiscount;
                        } else {
                            discount = -discountAmount;
                        }
                        if (discount < 0) {
                            // Odoo 19: order.add_product() was removed in favor of
                            // pos.addLineToOrder(vals, order, opts, configure).
                            await pos.addLineToOrder(
                                {
                                    product_id: product,
                                    product_tmpl_id: product.product_tmpl_id,
                                    price_unit: discount,
                                    qty: 1,
                                    tax_ids: [["clear"]],
                                    price_type: "automatic",
                                },
                                order,
                                { merge: false },
                                false
                            );
                        }
                    }
                    if (response.data.type == 2) {
                        const isPercentage = response.data.is_percentage || false;
                        const orderlines = order.getOrderlines();
                        const productIds = response.data.allowed_products.product_id;
                        const productDetails = await orm.call(
                            "product.product",
                            "search_read",
                            [
                                [
                                    ["id", "in", productIds]
                                ]
                            ], { fields: ["id", "display_name"] }
                        );
                        productDetails.forEach(product => {
                            product.display_name = product.display_name.replace(/\[.*?\]/, '').trim();
                        });
                        let allowedQty = response.data.allowed_products.quantity
                        let discountAmount = response.data.discount_amount || 0;
                        let maxDiscountAmt = response.data.max_discount_amount || 0;

                        const payload = await makeAwaitable(dialog, OrderlinePopup, {
                            title: _t("Select Linewise Discount"),
                            allowed_products: productDetails,
                            allowedQty: allowedQty,
                            discountAmount: discountAmount,
                            maxDiscountAmt: maxDiscountAmt,
                            isPercentage: isPercentage,
                        });
                        if (payload) {
                            for (const popupProduct of payload.updatedProducts) {
                                const productId = popupProduct.product_id.toString();
                                const selectedQty = popupProduct.quantity || 0;
                                const existingLine = order.getOrderlines().find((line) => line.getProduct().id.toString() === productId);

                                if (!existingLine && selectedQty > 0) {
                                    // In Odoo 19, get product from models registry and use pos.addLineToOrder.
                                    // Must await sequentially so all lines exist before the discount loop runs.
                                    const productModel = pos.models["product.product"].get(parseInt(productId));
                                    if (productModel) {
                                        await pos.addLineToOrder(
                                            {
                                                product_id: productModel,
                                                product_tmpl_id: productModel.product_tmpl_id,
                                                qty: selectedQty,
                                                price_type: "automatic",
                                            },
                                            order,
                                            {},
                                            false
                                        );
                                    }
                                }
                            }

                            const response_data_type_2 = true;
                            let discountApplied = false;
                            let totalDiscountApplied = 0;
                            let percentage_disc_applied = false;

                            order.getOrderlines().forEach((line) => {
                                const productId = line.getProduct().id.toString();
                                const quantity = line.getQuantity();
                                const selectedQty = payload.updatedProducts.find(product => product.product_id.toString() === productId)?.quantity || 0;
                                const allowedProducts = response.data.allowed_products.product_id || [];
                                let allowedQty = response.data.allowed_products.quantity || 0;

                                if (allowedProducts.includes(productId) && selectedQty > 0) {
                                    line.set_discountAmount(discountAmount);
                                    line.set_isPercentage(isPercentage);
                                    line.set_maxDiscountAmt(maxDiscountAmt);
                                    line.set_response_data_type_2(response_data_type_2);
                                    if (allowedQty > 0) {
                                        if (isPercentage) {
                                            if (quantity <= selectedQty) {
                                                if (quantity < selectedQty) {
                                                    line.setQuantity(selectedQty);
                                                }
                                                const base_unit_price = line.displayPriceUnit;
                                                line.set_base_unit_price(base_unit_price);
                                                const discountForApplicableQty = (discountAmount / 100) * line.price_unit * selectedQty;
                                                const finalDiscount = Math.min(discountForApplicableQty, maxDiscountAmt - totalDiscountApplied);
                                                const discountedPricePerUnit = line.price_unit - (finalDiscount / selectedQty);
                                                line.setUnitPrice(discountedPricePerUnit);
                                                if (maxDiscountAmt > totalDiscountApplied){
                                                    line.set_percentage_qty_applied(selectedQty);
                                                } else {
                                                    line.set_percentage_qty_applied(0);
                                                }
                                                totalDiscountApplied += finalDiscount;
                                            } else if (quantity > selectedQty) {
                                                maxDiscountAmt -= totalDiscountApplied;
                                                line.set_maxDiscountAmt(maxDiscountAmt);
                                                line.set_allowedQty(selectedQty);
                                                line.set_percentage_partial_discount(true);
                                            } else {
                                                console.log("Discount Is Invalid");
                                            }

                                        } else {
                                            if (quantity <= selectedQty) {
                                                if (quantity < selectedQty) {
                                                    line.setQuantity(selectedQty);
                                                }
                                                const discountForApplicableQty = discountAmount * selectedQty;
                                                const base_unit_price = line.displayPriceUnit;
                                                line.set_base_unit_price(base_unit_price);
                                                const finalDiscount = Math.min(discountForApplicableQty, maxDiscountAmt - totalDiscountApplied);
                                                if (line.price_unit < finalDiscount / selectedQty) {
                                                    const disc_applied = line.price_unit * selectedQty
                                                    totalDiscountApplied += disc_applied;
                                                    line.setUnitPrice(0);
                                                    line.set_disc_applied(disc_applied);
                                                    line.set_qty_applied(selectedQty);
                                                } else {
                                                    const discountedPricePerUnit = line.price_unit - (finalDiscount / selectedQty);
                                                    line.setUnitPrice(discountedPricePerUnit);
                                                    totalDiscountApplied += finalDiscount;
                                                    line.set_qty_applied(selectedQty);
                                                }
                                                discountAmount -= totalDiscountApplied;
                                                line.set_allowedQty(selectedQty);
                                            } else if (quantity > selectedQty) {
                                                const fix_amt_partial_disc = true;
                                                line.set_fix_amt_partial_disc(fix_amt_partial_disc);
                                                line.set_allowedQty(selectedQty);
                                            } else {
                                                console.log("Discount Is Invalid");
                                            }
                                        }
                                    }
                                }
                            });

                        }
                    }
                } else {
                    dialog.add(AlertDialog, {
                        title: _t("Invalid Code"),
                        body: _t(response.error || "Entered code is not valid."),
                    });
                }
            }
        }
    }

}

// Odoo 19 removed ProductScreen.addControlButton(). Register the button as a
// sub-component of the core ControlButtons so the template inheritance in
// promo_code_button.xml can render <BonatCodeButton/>.
ControlButtons.components = {
    ...ControlButtons.components,
    BonatCodeButton,
};
