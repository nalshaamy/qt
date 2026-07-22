# -*- coding: utf-8 -*-

from odoo import fields, models


class FlexsysPosReceiptBlock(models.Model):
    _name = "flexsys.pos.receipt.block"
    _description = "FLPOS Receipt Block"
    _order = "sequence, id"

    sequence = fields.Integer(default=10, index=True)
    template_id = fields.Many2one(
        "flexsys.pos.receipt.template",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        related="template_id.company_id",
        store=True,
        index=True,
    )
    enabled = fields.Boolean(default=True)
    block_type = fields.Selection(
        [
            ("header", "Header"),
            ("order_info", "Order Information"),
            ("items", "Items"),
            ("totals", "Totals"),
            ("payments", "Payments"),
            ("qr", "QR Code"),
            ("message", "Custom Message"),
            ("footer", "Footer"),
        ],
        required=True,
        default="message",
        index=True,
    )
    title = fields.Char(required=True, translate=True)
    show_title = fields.Boolean(
        string="Show Block Title",
        default=False,
        help="Display the block title on the printed receipt.",
    )
    content = fields.Text(
        translate=True,
        help="Optional text used by blocks such as Custom Message.",
    )
