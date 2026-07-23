# -*- coding: utf-8 -*-
# FLPOS - Builds enhanced POS session closing report data.

from collections import defaultdict

from odoo import api, models
from odoo.tools import format_amount


class PosSession(models.Model):
    """Extend POS sessions with helpers used by the enhanced closing report."""

    _inherit = "pos.session"

    @api.model
    def _flexsys_money(self, amount, currency):
        """Format a monetary value using the session currency and user locale."""
        return format_amount(self.env, amount or 0.0, currency)

    def _flexsys_get_closing_report_data(self):
        """Build the complete closing report dataset from standard POS records.

        The method does not store reporting fields, keeping the module standalone
        and safe to uninstall.
        """
        self.ensure_one()
        currency = self.currency_id or self.company_id.currency_id
        orders = self.order_ids.filtered(lambda order: order.state not in ("draft", "cancel"))
        lines = orders.mapped("lines")
        payments = orders.mapped("payment_ids")

        gross_sales = sum(lines.mapped("price_subtotal_incl"))
        net_untaxed = sum(lines.mapped("price_subtotal"))
        tax_total = gross_sales - net_untaxed
        discount_total = sum(
            (line.price_unit * line.qty) - line.price_subtotal
            for line in lines
            if line.qty > 0
        )
        refund_total = abs(sum(
            line.price_subtotal_incl for line in lines if line.qty < 0
        ))
        sold_qty = sum(line.qty for line in lines if line.qty > 0)
        refund_qty = abs(sum(line.qty for line in lines if line.qty < 0))

        payment_map = defaultdict(lambda: {"count": 0, "amount": 0.0})
        for payment in payments:
            method = payment.payment_method_id
            key = method.id
            payment_map[key]["name"] = method.name
            payment_map[key]["count"] += 1
            payment_map[key]["amount"] += payment.amount
        payment_rows = sorted(payment_map.values(), key=lambda row: row["amount"], reverse=True)

        variant_map = defaultdict(lambda: {
            "qty": 0.0,
            "refund_qty": 0.0,
            "gross": 0.0,
            "discount": 0.0,
            "net": 0.0,
            "tax": 0.0,
        })
        for line in lines:
            product = line.product_id
            row = variant_map[product.id]
            row.update({
                "product": product.display_name,
                "template": product.product_tmpl_id.name,
                "category": product.pos_categ_ids[:1].display_name if product.pos_categ_ids else "—",
                "attributes": ", ".join(product.product_template_attribute_value_ids.mapped("display_name")) or "—",
                "barcode": product.barcode or "—",
            })
            if line.qty >= 0:
                row["qty"] += line.qty
            else:
                row["refund_qty"] += abs(line.qty)
            line_gross = line.price_unit * line.qty
            row["gross"] += line_gross
            row["discount"] += line_gross - line.price_subtotal
            row["net"] += line.price_subtotal_incl
            row["tax"] += line.price_subtotal_incl - line.price_subtotal

        variant_rows = sorted(
            variant_map.values(),
            key=lambda row: (row["qty"], row["net"]),
            reverse=True,
        )

        cash_methods = payments.filtered(lambda p: getattr(p.payment_method_id, "is_cash_count", False))
        cash_received = sum(cash_methods.mapped("amount"))
        opening_cash = getattr(self, "cash_register_balance_start", 0.0) or 0.0
        expected_cash = getattr(self, "cash_register_balance_end", opening_cash + cash_received) or 0.0
        actual_cash = getattr(self, "cash_register_balance_end_real", 0.0) or 0.0

        average_order = gross_sales / len(orders) if orders else 0.0
        durations = False
        if self.start_at and self.stop_at:
            seconds = int((self.stop_at - self.start_at).total_seconds())
            hours, remainder = divmod(seconds, 3600)
            minutes = remainder // 60
            durations = f"{hours:02d}:{minutes:02d}"

        return {
            "currency": currency,
            "order_count": len(orders),
            "sold_qty": sold_qty,
            "refund_qty": refund_qty,
            "gross_sales": gross_sales,
            "net_untaxed": net_untaxed,
            "tax_total": tax_total,
            "discount_total": discount_total,
            "refund_total": refund_total,
            "average_order": average_order,
            "payment_rows": payment_rows,
            "variant_rows": variant_rows,
            "opening_cash": opening_cash,
            "cash_received": cash_received,
            "expected_cash": expected_cash,
            "actual_cash": actual_cash,
            "cash_difference": actual_cash - expected_cash,
            "duration": durations,
        }
