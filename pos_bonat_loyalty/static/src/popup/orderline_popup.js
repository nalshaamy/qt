/** @odoo-module */

import { Dialog } from "@web/core/dialog/dialog";
import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";

export class OrderlinePopup extends Component {
    static template = "OrderlinePopup";
    static components = { Dialog };
    static props = {
        title: { type: String, optional: true },
        confirmText: { type: String, optional: true },
        cancelText: { type: String, optional: true },
        allowed_products: { type: Array, optional: true },
        allowedQty: { type: Number, optional: true },
        discountAmount: { type: Number, optional: true },
        maxDiscountAmt: { type: Number, optional: true },
        isPercentage: { type: Boolean, optional: true },
        getPayload: { type: Function, optional: true },
        close: Function,
    };
    static defaultProps = {
        confirmText: _t("Apply"),
        cancelText: _t("Cancel"),
        title: _t("Confirm?"),
        allowed_products: [],
        allowedQty: 0,
        discountAmount: 0,
        maxDiscountAmt: 0,
        isPercentage: false,
    };

    setup() {
        this.pos = usePos();
    }

    updateCart(ev) {
        const button = ev.currentTarget.closest(".add-one") ? "add-one" : "remove-one";
        const inputField = ev.currentTarget.closest(".quantity-control").querySelector("input.disc_quantity");

        if (inputField) {
            let currentQuantity = parseInt(inputField.value) || 0;
            const minQuantity = parseInt(inputField.getAttribute("data-min")) || 0;
            const addButton = ev.currentTarget.closest(".quantity-control").querySelector(".add-one");

            if (button === 'add-one' && !addButton.hasAttribute('disabled')) {
                currentQuantity += 1;
            } else if (button === 'remove-one' && currentQuantity > minQuantity) {
                currentQuantity -= 1;
            }
            inputField.value = currentQuantity;
        }
        const totalQty = Array.from(document.querySelectorAll(".disc_quantity"))
            .map(input => parseInt(input.value || "0", 10))
            .reduce((sum, qty) => sum + qty, 0);
        const allowedQty = this.props.allowedQty;

        if (totalQty >= allowedQty) {
            document.querySelectorAll('.add-one').forEach(button => {
                button.setAttribute('disabled', 'true');
            });
        } else {
            document.querySelectorAll('.add-one').forEach(button => {
                button.removeAttribute('disabled');
            });
        }
    }

    onInput() {
        const totalQty = Array.from(document.querySelectorAll(".disc_quantity"))
            .map(input => parseInt(input.value || "0", 10))
            .reduce((sum, qty) => sum + qty, 0);
        const allowedQty = this.props.allowedQty;
        const input = event.target;

        if (totalQty > allowedQty) {
            const currentValue = parseInt(input.value || "0", 10);
            const excess = totalQty - allowedQty;
            input.value = Math.max(0, currentValue - excess);
            document.querySelectorAll('.btn-link[aria-label="Add one"]').forEach(button => {
                button.setAttribute('disabled', 'true');
            });
        }
    }

    confirmChanges() {
        const updatedProducts = this.props.allowed_products.map(product => {
            const inputElement = document.querySelector(`#qty_${product.id}`);
            const quantity = inputElement ? parseInt(inputElement.value || "0", 10) : 0;

            return {
                product_id: product.id,
                product_name: product.display_name,
                quantity: quantity,
            };
        });
        this.props.getPayload?.({ updatedProducts });
        this.props.close();
    }

    cancel() {
        this.props.close();
    }

    formatCurrency(value) {
        return this.pos.env.utils.formatCurrency(value);
    }
}
