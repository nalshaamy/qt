# -*- coding: utf-8 -*-

from odoo import api, fields, models


class FlexsysPosReceiptPreview(models.TransientModel):
    _name = "flexsys.pos.receipt.preview"
    _description = "FLPOS Receipt Preview"

    template_id = fields.Many2one(
        "flexsys.pos.receipt.template",
        required=True,
        readonly=True,
    )
    preview_html = fields.Html(
        compute="_compute_preview_html",
        sanitize=False,
    )

    @api.depends("template_id", "template_id.preview_html")
    def _compute_preview_html(self):
        for wizard in self:
            wizard.preview_html = wizard.template_id.preview_html
