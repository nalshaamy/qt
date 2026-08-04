from odoo import fields, models, _
from odoo.exceptions import AccessError


class FlexSysOperationEvent(models.Model):
    """Immutable operational event emitted by Operations services.

    The event store is intentionally append-only. Applications may read events,
    while creation is performed through EventService to keep payloads uniform.
    """

    _name = "flexsys.operation.event"
    _description = "Operations Event"
    _order = "occurred_at desc, id desc"

    name = fields.Char(required=True, index=True)
    event_type = fields.Char(required=True, index=True)
    aggregate_model = fields.Char(required=True, index=True)
    aggregate_id = fields.Integer(required=True, index=True)
    aggregate_reference = fields.Char(index=True)
    company_id = fields.Many2one(
        "res.company", required=True, index=True, default=lambda self: self.env.company
    )
    pos_config_id = fields.Many2one("pos.config", string="Branch / Point of Sale", index=True)
    source = fields.Char(index=True)
    actor_name = fields.Char(index=True)
    actor_type = fields.Selection(
        [("flexsys", "FlexSys User"), ("odoo", "Odoo User"), ("system", "System")],
        default="system",
        required=True,
        index=True,
    )
    occurred_at = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    payload = fields.Json(default=dict)
    visibility = fields.Selection(
        [("internal", "Internal"), ("customer", "Customer"), ("both", "Internal and Customer")],
        default="internal",
        required=True,
        index=True,
    )
    customer_message_ar = fields.Char(string="Customer Message (Arabic)")
    customer_message_en = fields.Char(string="Customer Message (English)")
    customer_progress = fields.Float(digits=(5, 2))

    def write(self, vals):
        if not self.env.context.get("allow_event_mutation"):
            raise AccessError(_("Operations events are immutable."))
        return super().write(vals)

    def unlink(self):
        if not self.env.context.get("allow_event_mutation"):
            raise AccessError(_("Operations events cannot be deleted."))
        return super().unlink()
