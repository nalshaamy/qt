"""Order serialization and application operations."""

from .base_service import BaseService


class OrderService(BaseService):
    """Provide order-related operations outside HTTP controllers."""

    _STATE_LABELS = {
        "new": "جديد",
        "accepted": "تم الاعتماد",
        "preparing": "قيد التحضير",
        "ready": "منفذ",
        "cancelled": "ملغي",
    }

    @classmethod
    def _state_label(cls, state):
        """Return the customer-facing label used by the existing API."""
        return cls._STATE_LABELS.get(state, state or "")

    @staticmethod
    def _selection_label(record, field_name, value):
        """Resolve an Odoo selection label without changing legacy fallback."""
        return dict(record._fields[field_name].selection).get(value, value or "")

    def serialize_order(self, order):
        """Return the legacy order payload consumed by current clients.

        Field names, values, and fallbacks intentionally match the original
        controller implementation to make this extraction behavior-neutral.
        """
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
            "payment_method_label": self._selection_label(
                order, "payment_method", order.payment_method
            ),
            "order_type": order.order_type or "",
            "order_type_label": self._selection_label(
                order, "order_type", order.order_type
            ),
            "table_name": order.table_id.display_name if order.table_id else "",
            "car_details": order.car_details or "",
            "delivery_distance_km": order.delivery_distance_km or 0.0,
            "delivery_google_maps_url": order.delivery_google_maps_url or "",
            "create_date": str(order.create_date or ""),
            "lines": [
                {
                    "product": line.product_id.display_name,
                    "qty": line.qty,
                    "price_unit": line.price_unit,
                    "subtotal": line.subtotal,
                    "note": line.note or "",
                }
                for line in order.line_ids
            ],
        }
