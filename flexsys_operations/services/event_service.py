"""Append-only event publishing for FlexSys Operations."""

from odoo import fields

from .base_service import BaseService


class EventService(BaseService):
    """Publish normalized events without coupling applications together."""

    _CUSTOMER_EVENTS = {
        "order.created": ("تم استلام طلبك", "Your order has been received", 10.0),
        "order.state_changed:new": ("تم استلام طلبك", "Your order has been received", 10.0),
        "order.state_changed:scheduled": ("تمت جدولة طلبك", "Your order has been scheduled", 15.0),
        "order.state_changed:accepted": ("تم اعتماد طلبك", "Your order has been confirmed", 25.0),
        "order.state_changed:preparing": ("بدأنا بتحضير طلبك", "Your order is being prepared", 50.0),
        "order.state_changed:partially_ready": ("تم تجهيز جزء من طلبك", "Part of your order is ready", 75.0),
        "order.state_changed:ready": ("طلبك جاهز للاستلام", "Your order is ready", 90.0),
        "order.state_changed:completed": ("تم تسليم طلبك", "Your order has been completed", 100.0),
        "order.state_changed:cancelled": ("تم إلغاء طلبك", "Your order has been cancelled", 100.0),
        "order.state_changed:rejected": ("تعذر قبول طلبك", "Your order could not be accepted", 100.0),
    }

    def _customer_event_values(self, event_type, payload):
        key = event_type
        if event_type == "order.state_changed":
            key = "%s:%s" % (event_type, (payload or {}).get("to"))
        message = self._CUSTOMER_EVENTS.get(key)
        if not message:
            return {"visibility": "internal"}
        return {
            "visibility": "both",
            "customer_message_ar": message[0],
            "customer_message_en": message[1],
            "customer_progress": message[2],
        }

    def emit(
        self,
        event_type,
        aggregate,
        *,
        payload=None,
        source=None,
        pos_config=None,
        actor_name=None,
        actor_type=None,
    ):
        aggregate.ensure_one()
        company = getattr(aggregate, "company_id", False)
        if not company and getattr(aggregate, "pos_config_id", False):
            company = aggregate.pos_config_id.company_id
        company = company or self.env.company
        pos_config = pos_config or getattr(aggregate, "pos_config_id", False)

        if not actor_name:
            actor_name = self.env.context.get("flexsys_actor_name")
        if not actor_type:
            actor_type = "flexsys" if actor_name else "odoo"
        if not actor_name and self.env.user:
            actor_name = self.env.user.display_name
        if not actor_name:
            actor_name, actor_type = "System", "system"

        event_values = self._customer_event_values(event_type, payload or {})
        return self.env["flexsys.operation.event"].sudo().create({
            "name": event_type.replace(".", " ").replace("_", " ").title(),
            "event_type": event_type,
            "aggregate_model": aggregate._name,
            "aggregate_id": aggregate.id,
            "aggregate_reference": aggregate.display_name,
            "company_id": company.id,
            "pos_config_id": pos_config.id if pos_config else False,
            "source": source or getattr(aggregate, "source", False) or "operations",
            "actor_name": actor_name,
            "actor_type": actor_type,
            "occurred_at": fields.Datetime.now(),
            "payload": payload or {},
            **event_values,
        })
