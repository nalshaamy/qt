# -*- coding: utf-8 -*-
# FLPOS - Builds enhanced POS session closing report data.

from collections import defaultdict
import base64

from odoo import api, fields, models
from odoo.tools import format_amount
from markupsafe import Markup, escape


class PosSession(models.Model):
    """Extend POS sessions with helpers used by the enhanced closing report."""

    _inherit = "pos.session"

    @api.model
    def _flexsys_money(self, amount, currency):
        """Format a monetary value using the session currency and user locale."""
        numeric_amount = amount or 0.0
        is_negative = numeric_amount < 0
        value = format_amount(self.env, abs(numeric_amount) if is_negative else numeric_amount, currency)
        # Remove invisible direction/BOM characters that wkhtmltopdf may expose
        # as garbled text in narrow RTL reports.
        for char in ("\u00a0", "\u202f"):
            value = value.replace(char, " ")
        for char in ("\u200e", "\u200f", "\u202a", "\u202b", "\u202c", "\u202d", "\u202e", "\u2066", "\u2067", "\u2068", "\u2069", "\ufeff"):
            value = value.replace(char, "")
        value = value.strip()
        return f"-{value}" if is_negative and value else value

    @api.model
    def _flexsys_qty(self, quantity):
        """Render quantities compactly on narrow thermal reports."""
        quantity = quantity or 0.0
        rounded = round(quantity)
        if abs(quantity - rounded) < 0.000001:
            return str(int(rounded))
        return (f"{quantity:.3f}").rstrip("0").rstrip(".")

    def _flexsys_report_timezone(self):
        """Return the timezone used for user-facing FLPOS report timestamps."""
        return (
            self.env.user.tz
            or self.env.context.get("tz")
            or self.company_id.partner_id.tz
            or "UTC"
        )

    def _flexsys_datetime(self, value):
        """Render a compact datetime in the current Odoo user's timezone."""
        if not value:
            return False
        value = fields.Datetime.to_datetime(value)
        timezone = self._flexsys_report_timezone()
        localized = fields.Datetime.context_timestamp(self.with_context(tz=timezone), value)
        return localized.strftime("%Y-%m-%d %H:%M")

    def _flexsys_datetime_parts(self, value):
        """Return localized date and time parts for clean report layouts."""
        if not value:
            return {"date": "", "time": ""}
        value = fields.Datetime.to_datetime(value)
        timezone = self._flexsys_report_timezone()
        localized = fields.Datetime.context_timestamp(self.with_context(tz=timezone), value)
        return {"date": localized.strftime("%Y-%m-%d"), "time": localized.strftime("%H:%M")}

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
            line.price_unit * line.qty * ((line.discount or 0.0) / 100.0)
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
        payment_total = sum(row["amount"] for row in payment_rows)
        for row in payment_rows:
            row["percentage"] = (row["amount"] / payment_total * 100.0) if payment_total else 0.0

        # Group completed orders by the actual POS cashier. The optional
        # pos_hr module stores the cashier in employee_id; installations without
        # pos_hr safely fall back to the order user/session opener.
        cashier_map = defaultdict(lambda: {
            "order_count": 0,
            "sales": 0.0,
            "refunds": 0.0,
            "discounts": 0.0,
            "net_sales": 0.0,
            "item_qty": 0.0,
        })
        for order in orders:
            cashier = False
            for field_name in ("employee_id", "cashier_id"):
                if field_name in order._fields:
                    cashier = order[field_name]
                    if cashier:
                        break
            if not cashier and "user_id" in order._fields:
                cashier = order.user_id
            if not cashier:
                cashier = self.user_id

            order_lines = order.lines
            positive_sales = sum(
                line.price_subtotal_incl for line in order_lines if line.qty > 0
            )
            refunds = abs(sum(
                line.price_subtotal_incl for line in order_lines if line.qty < 0
            ))
            discounts = sum(
                line.price_unit * line.qty * ((line.discount or 0.0) / 100.0)
                for line in order_lines if line.qty > 0
            )
            key = f"{cashier._name}:{cashier.id}"
            row = cashier_map[key]
            row["name"] = cashier.display_name
            row["order_count"] += 1
            row["sales"] += positive_sales
            row["refunds"] += refunds
            row["discounts"] += discounts
            row["net_sales"] += positive_sales - refunds
            row["item_qty"] += sum(line.qty for line in order_lines if line.qty > 0)

        for row in cashier_map.values():
            row["average_order"] = (row["net_sales"] / row["order_count"]) if row["order_count"] else 0.0
            row["average_items"] = (row["item_qty"] / row["order_count"]) if row["order_count"] else 0.0

        cashier_rows = sorted(
            cashier_map.values(),
            key=lambda row: (row["net_sales"], row["order_count"]),
            reverse=True,
        )
        cashier_names = [row["name"] for row in cashier_rows]
        cashier_summary = (
            cashier_names[0]
            if len(cashier_names) == 1
            else (f"{len(cashier_names)} أمناء صندوق" if cashier_names else "—")
        )

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
                "template_name": product.product_tmpl_id.name,
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
            if line.qty > 0:
                row["discount"] += line.price_unit * line.qty * ((line.discount or 0.0) / 100.0)
            row["net"] += line.price_subtotal_incl
            row["tax"] += line.price_subtotal_incl - line.price_subtotal

        for row in variant_map.values():
            row["unit_price"] = (row["gross"] / row["qty"]) if row["qty"] else 0.0

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
            clean_template_name = row.get("template_name") or (product_record.product_tmpl_id.name if product_record else template_name)
            group = product_group_map.setdefault(template_id, {
                "template": template_name,
                "clean_template": clean_template_name,
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

        # Keep the optional ranking concise: aggregate variants under their
        # product template, include sold quantities only, and cap the thermal
        # section at ten rows.
        top_selling_products = [
            {
                "rank": index,
                "product": group.get("clean_template") or group["template"],
                "qty": group["qty"],
                "amount": group["net"],
            }
            for index, group in enumerate(
                (
                    group
                    for group in product_groups
                    if group["qty"] > 0
                    and (
                        not self.config_id.flexsys_hide_zero_sales_top_products
                        or abs(group["net"]) > 0.000001
                    )
                ),
                start=1,
            )
        ][:10]

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

        configured_language = self.config_id.flexsys_report_language or "auto"
        user_language = (self.env.user.lang or "en_US").lower()
        report_language = (
            "ar" if user_language.startswith("ar") else "en"
        ) if configured_language == "auto" else configured_language

        ar = {
            "executive": "تقرير تنفيذي", "closing_title": "تقرير إغلاق جلسة نقطة البيع",
            "session": "الجلسة", "issued_at": "وقت إصدار التقرير", "pos": "نقطة البيع",
            "user": "المستخدم", "opened": "وقت الفتح", "closed": "وقت الإغلاق",
            "not_closed": "لم تغلق بعد", "cashier_count": "عدد أمناء الصندوق",
            "duration": "مدة الجلسة", "currency": "العملة", "status": "الحالة",
            "status_closed": "مغلقة", "status_open": "مفتوحة",
            "gross_sales": "إجمالي المبيعات", "net_sales": "صافي المبيعات",
            "order_count": "عدد الطلبات", "taxes": "الضرائب", "discounts": "الخصومات",
            "refunds": "المرتجعات", "product_sales": "تفاصيل مبيعات المنتجات",
            "number": "#", "product_variant": "اسم المنتج / المتغير", "category": "الفئة",
            "attributes": "الخصائص", "quantity": "الكمية", "unit_price": "سعر الوحدة",
            "discount": "الخصم", "tax": "الضريبة", "total": "الإجمالي",
            "sku_barcode": "الرمز / الباركود", "refund": "مرتجع",
            "no_product_sales": "لا توجد مبيعات منتجات في هذه الجلسة",
            "payments": "طرق الدفع", "method": "الطريقة", "transactions": "العمليات",
            "percentage": "النسبة", "amount": "المبلغ", "no_payments": "لا توجد دفعات",
            "cash_control": "مطابقة النقدية", "opening_cash": "الرصيد الافتتاحي",
            "cash_received": "المقبوض النقدي", "expected_cash": "الرصيد المتوقع",
            "actual_cash": "الرصيد الفعلي", "difference": "الفرق",
            "cashier_performance": "أداء أمناء الصندوق", "cashier": "أمين الصندوق",
            "sales": "المبيعات", "average_order": "متوسط الطلب",
            "average_products": "متوسط المنتجات", "net": "الصافي",
            "cashier_signature": "توقيع أمين الصندوق", "supervisor_signature": "توقيع المشرف",
            "approval_date": "تاريخ الاعتماد", "generated_at": "وقت إنشاء التقرير",
        }
        en = {
            "executive": "EXECUTIVE REPORT", "closing_title": "POS SESSION CLOSING REPORT",
            "session": "SESSION", "issued_at": "Report Issued At", "pos": "Point of Sale",
            "user": "User", "opened": "Opening Time", "closed": "Closing Time",
            "not_closed": "Not closed yet", "cashier_count": "Cashiers",
            "duration": "Session Duration", "currency": "Currency", "status": "Status",
            "status_closed": "Closed", "status_open": "Open",
            "gross_sales": "Gross Sales", "net_sales": "Net Sales",
            "order_count": "Orders", "taxes": "Taxes", "discounts": "Discounts",
            "refunds": "Refunds", "product_sales": "PRODUCT SALES DETAILS",
            "number": "#", "product_variant": "Product / Variant", "category": "Category",
            "attributes": "Attributes", "quantity": "Quantity", "unit_price": "Unit Price",
            "discount": "Discount", "tax": "Tax", "total": "Total",
            "sku_barcode": "SKU / Barcode", "refund": "Refund",
            "no_product_sales": "No product sales in this session",
            "payments": "PAYMENTS", "method": "Method", "transactions": "Transactions",
            "percentage": "Percentage", "amount": "Amount", "no_payments": "No payments",
            "cash_control": "CASH CONTROL", "opening_cash": "Opening Balance",
            "cash_received": "Cash Received", "expected_cash": "Expected Balance",
            "actual_cash": "Counted Balance", "difference": "Difference",
            "cashier_performance": "CASHIER PERFORMANCE", "cashier": "Cashier",
            "sales": "Sales", "average_order": "Average Order",
            "average_products": "Average Items", "net": "Net",
            "cashier_signature": "Cashier Signature", "supervisor_signature": "Supervisor Signature",
            "approval_date": "Approval Date", "generated_at": "Report Generated At",
        }
        if report_language == "ar":
            labels = ar
            a4_labels = ar
        else:
            labels = en
            a4_labels = en


        positive_sales = sum(
            line.price_subtotal_incl for line in lines if line.qty > 0
        )
        net_sales = positive_sales - refund_total

        # Closing reports use the dedicated POS receipt logo first, then the
        # company logo. Keeping the selected binary in the report dataset makes
        # the same fallback rule available to both A4 and thermal templates.
        receipt_logo = (
            self.config_id.flexsys_receipt_logo
            if self.config_id.flexsys_enable_custom_receipt_logo
            and self.config_id.flexsys_receipt_logo
            else False
        )
        report_logo = receipt_logo or self.company_id.logo or False
        report_logo_source = (
            "receipt" if receipt_logo else ("company" if self.company_id.logo else False)
        )

        return {
            "labels": labels,
            "a4_labels": a4_labels,
            "report_language": report_language,
            "report_direction": "rtl" if report_language == "ar" else "ltr",
            "report_logo": report_logo,
            "report_logo_source": report_logo_source,
            "report_generated_at": self._flexsys_datetime(fields.Datetime.now()),
            "report_generated_parts": self._flexsys_datetime_parts(fields.Datetime.now()),
            "sales_before_refunds": positive_sales,
            "net_sales": net_sales,
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
            "top_selling_products": top_selling_products,
            "cashier_rows": cashier_rows,
            "cashier_summary": cashier_summary,
            "cashier_count": len(cashier_rows),
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

    def action_flexsys_email_thermal_closing_report(self):
        """Open a reviewable email with the thermal closing PDF attached."""
        self.ensure_one()
        if not self.config_id.flexsys_enable_email_closing_report:
            return False

        pdf_content, _content_type = self.env["ir.actions.report"]._render_qweb_pdf(
            "flexsys_pos_config.report_pos_session_closing_thermal",
            res_ids=[self.id],
        )
        safe_session_name = (self.name or str(self.id)).replace("/", "-")
        attachment = self.env["ir.attachment"].create({
            "name": f"Thermal Closing Report - {safe_session_name}.pdf",
            "type": "binary",
            "datas": base64.b64encode(pdf_content),
            "mimetype": "application/pdf",
            "res_model": self._name,
            "res_id": self.id,
        })
        subject = f"Thermal Closing Report - {self.name or ''}".strip(" -")
        body = (
            f"<p>Please find attached the thermal closing report for "
            f"<strong>{self.display_name}</strong>.</p>"
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": "mail.compose.message",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_composition_mode": "comment",
                "default_model": self._name,
                "default_res_ids": self.ids,
                "default_subject": subject,
                "default_body": body,
                "default_attachment_ids": [(6, 0, attachment.ids)],
            },
        }
