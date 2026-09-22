from odoo import fields, models


class FlexSysPosReferenceGuardLog(models.Model):
    _name = "flexsys.pos.reference.guard.log"
    _description = "FlexSys POS Reference Guard Log"
    _order = "id desc"

    order_id = fields.Many2one(
        "pos.order",
        string="POS Order",
        readonly=True,
        ondelete="set null",
        index=True,
    )
    order_uuid = fields.Char(string="Order UUID", readonly=True, index=True)
    session_id = fields.Many2one("pos.session", string="Session", readonly=True, index=True)
    config_id = fields.Many2one("pos.config", string="Point of Sale", readonly=True, index=True)
    cashier_name = fields.Char(string="Cashier", readonly=True, index=True)
    user_id = fields.Many2one("res.users", string="User", readonly=True, index=True)
    original_pos_reference = fields.Char(string="Original Receipt Number", readonly=True, index=True)
    replacement_pos_reference = fields.Char(string="Replacement Receipt Number", readonly=True, index=True)
    original_tracking_number = fields.Char(string="Original Order Number", readonly=True)
    replacement_tracking_number = fields.Char(string="Replacement Order Number", readonly=True)
    duplicate_order_id = fields.Many2one(
        "pos.order",
        string="Existing Duplicate Order",
        readonly=True,
        ondelete="set null",
    )
    reason = fields.Char(string="Reason", readonly=True)
