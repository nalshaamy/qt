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
        value = format_amount(self.env, amount or 0.0, currency)
        # Remove invisible direction/BOM characters that wkhtmltopdf may expose
        # as garbled text in narrow RTL reports.
        for char in ("\u00a0", "\u202f"):
            value = value.replace(char, " ")
        for char in ("\u200e", "\u200f", "\u202a", "\u202b", "\u202c", "\u202d", "\u202e", "\u2066", "\u2067", "\u2068", "\u2069", "\ufeff"):
            value = value.replace(char, "")
        return value.strip()

    @api.model
    def _flexsys_qty(self, quantity):
        """Render quantities compactly on narrow thermal reports."""
        quantity = quantity or 0.0
        rounded = round(quantity)
        if abs(quantity - rounded) < 0.000001:
            return str(int(rounded))
        return (f"{quantity:.3f}").rstrip("0").rstrip(".")

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
            attribute_value_records = product.product_template_attribute_value_ids
            attribute_items = [
                {
                    "attribute": value.attribute_id.name,
                    "value": value.name,
                }
                for value in attribute_value_records
            ]
            attribute_values = [item["value"] for item in attribute_items]
            row.update({
                "product_id": product.id,
                "template_id": product.product_tmpl_id.id,
                "product": product.display_name,
                "template": product.product_tmpl_id.display_name,
                "category": product.pos_categ_ids[:1].display_name if product.pos_categ_ids else "—",
                "attributes": " | ".join(attribute_values) or "—",
                "attribute_items": attribute_items,
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

        # Group sold variants under their product template for the thermal
        # report. This keeps an 80 mm printout readable while still showing
        # exactly how many units of each attribute combination were sold.
        product_group_map = {}
        for row in variant_rows:
            product = row.get("product")
            # variant_map is keyed by product ID; recover the product record
            # through the current row name only when legacy cached data is
            # encountered. New rows always carry product_id/template_id below.
            product_id = row.get("product_id")
            product_record = self.env["product.product"].browse(product_id) if product_id else False
            template_id = row.get("template_id") or (product_record.product_tmpl_id.id if product_record else product)
            template_name = row.get("template") or (product_record.product_tmpl_id.display_name if product_record else product)
            group = product_group_map.setdefault(template_id, {
                "template": template_name,
                "qty": 0.0,
                "refund_qty": 0.0,
                "net": 0.0,
                "variants": [],
            })
            group["qty"] += row["qty"]
            group["refund_qty"] += row["refund_qty"]
            group["net"] += row["net"]
            group["variants"].append({
                "attributes": row.get("attributes") or "—",
                "attribute_items": row.get("attribute_items") or [],
                "qty": row["qty"],
                "refund_qty": row["refund_qty"],
                "net": row["net"],
            })

        product_groups = []
        for group in product_group_map.values():
            group["variants"] = sorted(
                group["variants"],
                key=lambda variant: (variant["qty"], variant["net"]),
                reverse=True,
            )
            has_named_variant = any(
                variant.get("attributes") and variant["attributes"] != "—"
                for variant in group["variants"]
            )
            group["show_variants"] = has_named_variant or len(group["variants"]) > 1
            group["variant_count"] = len([
                variant for variant in group["variants"]
                if variant.get("attributes") and variant["attributes"] != "—"
            ])
            positive_group_qty = group["qty"] if group["qty"] > 0 else 0.0
            for variant in group["variants"]:
                variant["display_attributes"] = (
                    variant["attributes"]
                    if variant.get("attributes") and variant["attributes"] != "—"
                    else "بدون متغير"
                )
                variant["share_percent"] = (
                    (variant["qty"] / positive_group_qty) * 100.0
                    if positive_group_qty and variant["qty"] > 0
                    else 0.0
                )
            product_groups.append(group)
        product_groups.sort(key=lambda group: (group["qty"], group["net"]), reverse=True)

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

        labels = {
            "title": "\u062a\u0642\u0631\u064a\u0631 \u0625\u063a\u0644\u0627\u0642 \u062c\u0644\u0633\u0629 \u0646\u0642\u0637\u0629 \u0627\u0644\u0628\u064a\u0639",
            "session": "\u0627\u0644\u062c\u0644\u0633\u0629",
            "pos": "\u0646\u0642\u0637\u0629 \u0627\u0644\u0628\u064a\u0639",
            "user": "\u0627\u0644\u0645\u0633\u062a\u062e\u062f\u0645",
            "opened": "\u0627\u0644\u0641\u062a\u062d",
            "closed": "\u0627\u0644\u0625\u063a\u0644\u0627\u0642",
            "duration": "\u0627\u0644\u0645\u062f\u0629",
            "sales_summary": "\u0645\u0644\u062e\u0635 \u0627\u0644\u0645\u0628\u064a\u0639\u0627\u062a",
            "gross_sales": "\u0625\u062c\u0645\u0627\u0644\u064a \u0627\u0644\u0645\u0628\u064a\u0639\u0627\u062a",
            "order_count": "\u0639\u062f\u062f \u0627\u0644\u0637\u0644\u0628\u0627\u062a",
            "average_order": "\u0645\u062a\u0648\u0633\u0637 \u0627\u0644\u0637\u0644\u0628",
            "net_untaxed": "\u0627\u0644\u0635\u0627\u0641\u064a \u0642\u0628\u0644 \u0627\u0644\u0636\u0631\u064a\u0628\u0629",
            "taxes": "\u0627\u0644\u0636\u0631\u0627\u0626\u0628",
            "discounts": "\u0627\u0644\u062e\u0635\u0648\u0645\u0627\u062a",
            "refunds": "\u0627\u0644\u0645\u0631\u062a\u062c\u0639\u0627\u062a",
            "sold_qty": "\u0627\u0644\u0643\u0645\u064a\u0629 \u0627\u0644\u0645\u0628\u0627\u0639\u0629",
            "refund_qty": "\u0643\u0645\u064a\u0629 \u0627\u0644\u0645\u0631\u062a\u062c\u0639",
            "payments": "\u0637\u0631\u0642 \u0627\u0644\u062f\u0641\u0639",
            "no_payments": "\u0644\u0627 \u062a\u0648\u062c\u062f \u062f\u0641\u0639\u0627\u062a",
            "cash_reconciliation": "\u0645\u0637\u0627\u0628\u0642\u0629 \u0627\u0644\u0646\u0642\u062f\u064a\u0629",
            "opening_cash": "\u0627\u0644\u0631\u0635\u064a\u062f \u0627\u0644\u0627\u0641\u062a\u062a\u0627\u062d\u064a",
            "cash_received": "\u0627\u0644\u0645\u0642\u0628\u0648\u0636 \u0627\u0644\u0646\u0642\u062f\u064a",
            "expected_cash": "\u0627\u0644\u0631\u0635\u064a\u062f \u0627\u0644\u0645\u062a\u0648\u0642\u0639",
            "actual_cash": "\u0627\u0644\u0631\u0635\u064a\u062f \u0627\u0644\u0641\u0639\u0644\u064a",
            "difference": "\u0627\u0644\u0641\u0631\u0642",
            "products": "\u0627\u0644\u0645\u0646\u062a\u062c\u0627\u062a",
            "quantity": "\u0627\u0644\u0643\u0645\u064a\u0629",
            "refund": "\u0645\u0631\u062a\u062c\u0639",
            "no_products": "\u0644\u0627 \u062a\u0648\u062c\u062f \u0645\u0628\u064a\u0639\u0627\u062a \u0645\u0646\u062a\u062c\u0627\u062a",
            "cashier_signature": "\u062a\u0648\u0642\u064a\u0639 \u0627\u0644\u0643\u0627\u0634\u064a\u0631",
            "supervisor_signature": "\u062a\u0648\u0642\u064a\u0639 \u0627\u0644\u0645\u0634\u0631\u0641",
        }

        return {
            "labels": labels,
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
            "product_groups": product_groups,
            "opening_cash": opening_cash,
            "cash_received": cash_received,
            "expected_cash": expected_cash,
            "actual_cash": actual_cash,
            "cash_difference": actual_cash - expected_cash,
            "duration": durations,
        }

    def action_flexsys_preview_thermal_closing_report(self):
        """Open the 80 mm thermal closing report in a new browser tab."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/report/pdf/flexsys_pos_config.report_pos_session_closing_thermal/{self.id}",
            "target": "new",
        }

    def action_flexsys_download_thermal_closing_report(self):
        """Download the 80 mm thermal closing report as a PDF file."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": (
                "/report/pdf/flexsys_pos_config.report_pos_session_closing_thermal/"
                f"{self.id}?download=true"
            ),
            "target": "self",
        }
