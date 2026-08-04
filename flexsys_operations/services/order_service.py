"""Order application service.

The service owns order creation and serialization so HTTP controllers remain
thin transport adapters.  Legacy model names are intentionally preserved until
a dedicated data migration is introduced.
"""

from __future__ import annotations

import math
from typing import Any

from odoo import fields

from ..common.exceptions import FlexSysValidationError
from .base_service import BaseService


class OrderService(BaseService):
    """Create and serialize Operations orders through one stable boundary."""

    _STATE_LABELS = {
        "scheduled": "مجدول",
        "new": "جديد",
        "accepted": "تم الاعتماد",
        "preparing": "قيد التحضير",
        "partially_ready": "جاهز جزئيًا",
        "ready": "جاهز",
        "completed": "مكتمل",
        "rejected": "مرفوض",
        "cancelled": "ملغي",
    }
    _PAYMENT_FIELDS = {
        "cash": "operations_enable_cash",
        "card": "operations_enable_card",
        "wallet": "operations_enable_wallet",
    }
    _ORDER_TYPE_FIELDS = {
        "dine_in": "operations_enable_dine_in",
        "takeaway": "operations_enable_takeaway",
        "car": "operations_enable_car_order",
        "delivery": "operations_enable_delivery",
    }

    @classmethod
    def _state_label(cls, state):
        return cls._STATE_LABELS.get(state, state or "")

    @staticmethod
    def _selection_label(record, field_name, value):
        selection = record._fields[field_name].selection
        if callable(selection):
            selection = selection(record.env)
        return dict(selection).get(value, value or "")

    @staticmethod
    def _distance_km(lat1, lon1, lat2, lon2):
        """Return great-circle distance in kilometres."""
        radius = 6371.0
        p1 = math.radians(float(lat1))
        p2 = math.radians(float(lat2))
        dlat = math.radians(float(lat2) - float(lat1))
        dlon = math.radians(float(lon2) - float(lon1))
        value = (
            math.sin(dlat / 2) ** 2
            + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
        )
        value = min(max(value, 0.0), 1.0)
        return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))

    def serialize_order(self, order):
        """Return the stable payload consumed by current web clients."""
        return {
            "id": order.id,
            "name": order.name,
            "customer_name": order.customer_name or "",
            "customer_mobile": order.customer_mobile or "",
            "state": order.state,
            "state_label": self._state_label(order.state),
            "partner_id": order.partner_id.id if order.partner_id else False,
            "amount_total": order.amount_total,
            "note": order.note or "",
            "payment_method": order.payment_method or "",
            "payment_method_label": self._selection_label(order, "payment_method", order.payment_method),
            "order_type": order.order_type or "",
            "order_type_label": self._selection_label(order, "order_type", order.order_type),
            "table_name": order.table_id.display_name if order.table_id else "",
            "car_details": order.car_details or "",
            "delivery_distance_km": order.delivery_distance_km or 0.0,
            "delivery_google_maps_url": order.delivery_google_maps_url or "",
            "create_date": str(order.create_date or ""),
            "requested_time": str(order.requested_time or ""),
            "priority": order.priority or "normal",
            "source": order.source or "",
            "preparation_progress": order.preparation_progress or 0.0,
            "ready_line_count": order.ready_line_count or 0,
            "active_line_count": order.active_line_count or 0,
            "unavailable_line_count": order.unavailable_line_count or 0,
            "tracking_url": "/self-order/track/%s" % order.tracking_token,
            "lines": [
                {
                    "product": line.product_id.display_name,
                    "qty": line.qty,
                    "price_unit": line.price_unit,
                    "subtotal": line.subtotal,
                    "note": line.note or "",
                    "preparation_state": line.preparation_state or "new",
                    "unavailable_reason": line.unavailable_reason or "",
                    "kitchen_note": line.kitchen_note or "",
                }
                for line in order.line_ids
            ],
        }

    def create_self_order(
        self,
        *,
        lines,
        payment_method,
        order_type,
        pos_config_id=None,
        fallback_pos_config=None,
        partner=None,
        customer_name=None,
        customer_mobile=None,
        note=None,
        table_id=None,
        car_details=None,
        delivery_latitude=None,
        delivery_longitude=None,
        requested_time=None,
    ):
        """Validate and create one Self Order atomically.

        Raises ``FlexSysValidationError`` for expected customer-facing failures.
        The controller only translates the exception to the JSON contract.
        """
        self._ensure_store_open()
        if not lines:
            raise FlexSysValidationError("السلة فارغة", code="empty_cart")

        pos_config = self._resolve_pos_config(pos_config_id, fallback_pos_config)
        order_lines, products = self._prepare_lines(lines)
        self._ensure_branch_available(pos_config)
        self._ensure_products_available(pos_config, products)
        self._validate_options(pos_config, payment_method, order_type)

        selected_table = self._validate_table(order_type, table_id, pos_config)
        car_details = (car_details or "").strip()
        if order_type == "car" and not car_details:
            raise FlexSysValidationError("أدخل نوع السيارة أو وصفها.", code="car_details_required")

        delivery_values = self._prepare_delivery(
            order_type, pos_config, delivery_latitude, delivery_longitude
        )
        requested_dt = self._parse_requested_time(requested_time)
        state = "scheduled" if requested_dt and requested_dt > fields.Datetime.now() else "new"

        partner = partner if partner and partner.exists() else self.env["res.partner"]
        if partner:
            customer_name = partner.name or ""
            customer_mobile = partner.mobile or partner.phone or ""

        values = {
            "partner_id": partner.id if partner else False,
            "customer_name": customer_name or "",
            "customer_mobile": customer_mobile or "",
            "note": note or "",
            "source": "self_order",
            "state": state,
            "requested_time": requested_dt,
            "pos_config_id": pos_config.id if pos_config else False,
            "payment_method": payment_method,
            "order_type": order_type,
            "table_id": selected_table.id if selected_table else False,
            "car_details": car_details,
            "line_ids": order_lines,
            **delivery_values,
        }
        return self.env["flexsys.operations.order"].sudo().create(values)

    def _ensure_store_open(self):
        settings = self.env["flexsys.operations.store.settings"].sudo().get_settings()
        if not settings.is_open:
            raise FlexSysValidationError(
                settings.closed_message or "المتجر مغلق حاليًا ولا يمكن استقبال طلبات جديدة.",
                code="store_closed",
                details={"store_closed": True},
            )

    def _resolve_pos_config(self, pos_config_id, fallback_pos_config):
        branches = self.env["pos.config"].sudo().search([("operations_branch_enabled", "=", True)])
        if len(branches) > 1 and not pos_config_id:
            raise FlexSysValidationError("اختر الفرع قبل إرسال الطلب.", code="branch_required")

        pos_config = self.env["pos.config"].sudo().browse()
        if pos_config_id:
            try:
                pos_config = self.env["pos.config"].sudo().browse(int(pos_config_id)).exists()
            except (TypeError, ValueError):
                pos_config = self.env["pos.config"].sudo().browse()
        if not pos_config and fallback_pos_config:
            pos_config = fallback_pos_config.sudo().exists()
        return pos_config

    def _prepare_lines(self, raw_lines):
        order_lines = []
        products = self.env["product.product"].sudo().browse()
        for raw_line in raw_lines:
            try:
                product_id = int(raw_line.get("product_id") or 0)
                qty = max(float(raw_line.get("qty") or 1), 0.0)
            except (TypeError, ValueError, AttributeError):
                continue
            product = self.env["product.product"].sudo().browse(product_id).exists()
            if not product or not qty:
                continue
            template = product.product_tmpl_id
            if not template.show_in_qr_menu or not product.sale_ok:
                continue
            products |= product
            order_lines.append((0, 0, {
                "product_id": product.id,
                "qty": qty,
                "price_unit": product.lst_price,
                "note": raw_line.get("note") or "",
            }))
        if not order_lines:
            raise FlexSysValidationError("لا توجد منتجات صالحة في الطلب", code="invalid_lines")
        return order_lines, products

    @staticmethod
    def _ensure_branch_available(pos_config):
        if pos_config and not pos_config.operations_branch_enabled:
            raise FlexSysValidationError("نقطة البيع المختارة غير متاحة للطلبات.", code="branch_disabled")
        if pos_config and not pos_config.operations_branch_is_open:
            raise FlexSysValidationError(
                pos_config.operations_branch_closed_message or "هذا الفرع مغلق حاليًا.",
                code="branch_closed",
            )

    def _ensure_products_available(self, pos_config, products):
        templates = products.mapped("product_tmpl_id")
        availability = {template.id: bool(template.available_in_qr_menu) for template in templates}
        if pos_config and templates:
            overrides = self.env["flexsys.operations.product.availability"].sudo().search([
                ("pos_config_id", "=", pos_config.id),
                ("product_tmpl_id", "in", templates.ids),
            ])
            for record in overrides:
                availability[record.product_tmpl_id.id] = bool(record.available)
        unavailable = products.filtered(
            lambda product: not availability.get(product.product_tmpl_id.id, True)
        )
        if unavailable:
            raise FlexSysValidationError(
                "أحد المنتجات نفدت كميته في هذا الفرع.",
                code="product_unavailable",
                details={"product_ids": unavailable.ids},
            )

    def _validate_options(self, pos_config, payment_method, order_type):
        if payment_method not in self._PAYMENT_FIELDS:
            raise FlexSysValidationError("اختر طريقة الدفع.", code="payment_required")
        if order_type not in self._ORDER_TYPE_FIELDS:
            raise FlexSysValidationError("اختر نوع الطلب.", code="order_type_required")
        if pos_config:
            payment_field = self._PAYMENT_FIELDS[payment_method]
            order_type_field = self._ORDER_TYPE_FIELDS[order_type]
            if not getattr(pos_config, payment_field, True):
                raise FlexSysValidationError("طريقة الدفع المختارة غير متاحة في هذا الفرع.", code="payment_disabled")
            if not getattr(pos_config, order_type_field, True):
                raise FlexSysValidationError("نوع الطلب المختار غير متاح في هذا الفرع.", code="order_type_disabled")

    def _validate_table(self, order_type, table_id, pos_config):
        table = self.env["flexsys.operations.table"].sudo().browse()
        if order_type != "dine_in":
            return table
        try:
            table = self.env["flexsys.operations.table"].sudo().browse(int(table_id or 0)).exists()
        except (TypeError, ValueError):
            table = self.env["flexsys.operations.table"].sudo().browse()
        if not table or table.pos_config_id != pos_config or not table.active:
            raise FlexSysValidationError("اختر طاولة صحيحة للطلب المحلي.", code="invalid_table")
        return table

    def _prepare_delivery(self, order_type, pos_config, latitude, longitude):
        values = {
            "delivery_latitude": 0.0,
            "delivery_longitude": 0.0,
            "delivery_distance_km": 0.0,
            "delivery_google_maps_url": "",
        }
        if order_type != "delivery":
            return values
        try:
            customer_lat = float(latitude)
            customer_lon = float(longitude)
        except (TypeError, ValueError):
            raise FlexSysValidationError("شارك موقع التوصيل أولًا.", code="delivery_location_required")
        if not pos_config or not pos_config.operations_latitude or not pos_config.operations_longitude:
            raise FlexSysValidationError("موقع الفرع غير محدد، تواصل مع المتجر.", code="branch_location_missing")
        distance = self._distance_km(
            pos_config.operations_latitude, pos_config.operations_longitude, customer_lat, customer_lon
        )
        max_distance = pos_config.operations_max_order_distance_km or 0.0
        if max_distance and distance > max_distance:
            raise FlexSysValidationError(
                "موقع التوصيل خارج النطاق المسموح (%.1f كم)." % max_distance,
                code="delivery_out_of_range",
                details={"distance_km": distance, "max_distance_km": max_distance},
            )
        values.update({
            "delivery_latitude": customer_lat,
            "delivery_longitude": customer_lon,
            "delivery_distance_km": distance,
            "delivery_google_maps_url": "https://www.google.com/maps?q=%s,%s" % (customer_lat, customer_lon),
        })
        return values

    @staticmethod
    def _parse_requested_time(requested_time):
        if not requested_time:
            return False
        try:
            return fields.Datetime.to_datetime(requested_time)
        except (TypeError, ValueError):
            raise FlexSysValidationError("وقت الاستلام المطلوب غير صالح", code="invalid_requested_time")
