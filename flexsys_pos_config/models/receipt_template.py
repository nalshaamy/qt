# -*- coding: utf-8 -*-

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class FlexsysPosReceiptTemplate(models.Model):
    _name = "flexsys.pos.receipt.template"
    _description = "FLPOS Receipt Template"
    _order = "name, id"

    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    pos_config_id = fields.Many2one(
        "pos.config",
        string="Point of Sale",
        required=True,
        domain="[('company_id', '=', company_id)]",
        index=True,
        ondelete="cascade",
    )
    is_default = fields.Boolean(
        string="Default Template",
        default=False,
        help="Use this template as the active receipt design for the selected Point of Sale.",
    )
    description = fields.Text(translate=True)
    block_ids = fields.One2many(
        "flexsys.pos.receipt.block",
        "template_id",
        string="Receipt Blocks",
        copy=True,
    )
    preview_html = fields.Html(
        string="Preview",
        compute="_compute_preview_html",
        sanitize=False,
    )

    _name_pos_config_unique = models.Constraint(
        "UNIQUE(name, pos_config_id)",
        "Template names must be unique per Point of Sale.",
    )

    @api.constrains("is_default", "pos_config_id", "active")
    def _check_single_default_template(self):
        for template in self.filtered(lambda rec: rec.is_default and rec.active):
            duplicate = self.search_count(
                [
                    ("id", "!=", template.id),
                    ("pos_config_id", "=", template.pos_config_id.id),
                    ("is_default", "=", True),
                    ("active", "=", True),
                ]
            )
            if duplicate:
                raise ValidationError(
                    _("Only one active default receipt template is allowed per Point of Sale.")
                )

    @api.onchange("pos_config_id")
    def _onchange_pos_config_id(self):
        if self.pos_config_id:
            self.company_id = self.pos_config_id.company_id

    @api.depends(
        "name",
        "pos_config_id",
        "block_ids.sequence",
        "block_ids.enabled",
        "block_ids.block_type",
        "block_ids.title",
        "block_ids.content",
        "block_ids.alignment",
        "block_ids.font_size",
        "block_ids.bold",
    )
    def _compute_preview_html(self):
        for template in self:
            template.preview_html = template._build_preview_html()

    def _build_preview_html(self):
        self.ensure_one()
        blocks = self.block_ids.filtered("enabled").sorted("sequence")
        block_html = "".join(self._render_preview_block(block) for block in blocks)
        if not block_html:
            block_html = (
                '<div class="text-muted text-center py-5">'
                + str(escape(_("Add and enable receipt blocks to display the preview.")))
                + "</div>"
            )

        pos_name = self.pos_config_id.display_name or _("Point of Sale")
        return Markup(
            """
            <div class="o_flexsys_receipt_preview_wrap">
                <div class="o_flexsys_receipt_preview">
                    <div class="o_flexsys_receipt_preview_inner">
                        <div class="text-center text-muted small mb-2">%s</div>
                        %s
                    </div>
                </div>
            </div>
            """
        ) % (escape(pos_name), Markup(block_html))

    def _render_preview_block(self, block):
        title = escape(block.title or block.display_name)
        custom_content = escape(block.content or "")
        templates = {
            "logo": '<section class="text-center"><div class="o_flexsys_demo_logo">FS</div></section>',
            "company": """
                <section>
                    <div class="fw-bold fs-5">FlexSys Demo Company</div>
                    <div>VAT: 310000000000003</div>
                    <div>CR: 5900000000</div>
                    <div>www.flexsys.sa</div>
                </section>
            """,
            "queue": """
                <section class="text-center border rounded py-2">
                    <div class="small">Queue Number</div><div class="fw-bold fs-3">A-042</div>
                </section>
            """,
            "header": """
                <section class="text-center">
                    <div class="fw-bold fs-5">FlexSys Demo Company</div>
                    <div>VAT: 310000000000003</div>
                    <div>www.flexsys.sa</div>
                </section>
            """,
            "order_info": """
                <section class="border-top border-bottom py-2">
                    <div class="d-flex justify-content-between"><span>Order</span><strong>#0042</strong></div>
                    <div class="d-flex justify-content-between"><span>Cashier</span><span>Demo User</span></div>
                    <div class="d-flex justify-content-between"><span>Date</span><span>22/07/2026 10:30</span></div>
                </section>
            """,
            "customer": """
                <section>
                    <div class="d-flex justify-content-between"><span>Customer</span><span>Guest Customer</span></div>
                    <div class="d-flex justify-content-between"><span>Mobile</span><span>05X XXX XXXX</span></div>
                </section>
            """,
            "items": """
                <section>
                    <div class="d-flex justify-content-between"><span>1 × Cappuccino</span><span>18.00</span></div>
                    <div class="d-flex justify-content-between"><span>2 × Cookie</span><span>14.00</span></div>
                </section>
            """,
            "totals": """
                <section class="border-top pt-2">
                    <div class="d-flex justify-content-between"><span>Subtotal</span><span>27.83</span></div>
                    <div class="d-flex justify-content-between"><span>VAT 15%%</span><span>4.17</span></div>
                    <div class="d-flex justify-content-between fw-bold fs-5"><span>Total</span><span>32.00 SAR</span></div>
                </section>
            """,
            "payments": '<section><div class="d-flex justify-content-between"><span>Card</span><span>32.00 SAR</span></div></section>',
            "qr": '<section class="text-center"><div class="border d-inline-flex align-items-center justify-content-center" style="width:88px;height:88px;">QR</div></section>',
            "message": '<section>%s</section>' % (custom_content or escape(_("Thank you for your visit."))),
            "divider": '<div style="border-top:1px dashed #777;"></div>',
            "spacer": '<div style="height:16px;"></div>',
            "footer": """
                <section class="border-top pt-2">
                    <div>%s</div>
                    <div class="small text-muted">Powered by FLPOS</div>
                </section>
            """ % (custom_content or escape(_("Every Receipt Is a Marketing Opportunity"))),
        }
        body = templates.get(block.block_type, "")
        style = "text-align:%s;" % block.alignment
        size_classes = {"small": "small", "normal": "", "large": "fs-5", "xlarge": "fs-3"}
        css_class = " ".join(filter(None, [size_classes.get(block.font_size, ""), "fw-bold" if block.bold else ""]))
        return str(
            Markup('<div class="o_flexsys_receipt_block %s mb-3" style="%s" data-block="%s">%s%s</div>')
            % (
                escape(css_class),
                escape(style),
                escape(block.block_type),
                Markup('<div class="small text-muted text-uppercase mb-1">%s</div>' % title) if block.show_title else Markup(""),
                Markup(body),
            )
        )

    def action_preview(self):
        self.ensure_one()
        return {
            "name": _("Receipt Preview"),
            "type": "ir.actions.act_window",
            "res_model": "flexsys.pos.receipt.preview",
            "view_mode": "form",
            "target": "new",
            "context": {"default_template_id": self.id},
        }

    @api.model_create_multi
    def create(self, vals_list):
        templates = super().create(vals_list)
        templates._ensure_default_blocks()
        return templates

    def _ensure_default_blocks(self):
        Block = self.env["flexsys.pos.receipt.block"]
        defaults = [
            (10, "logo", _("Logo")),
            (20, "company", _("Company Information")),
            (30, "queue", _("Queue Number")),
            (40, "order_info", _("Order Information")),
            (50, "items", _("Items")),
            (60, "totals", _("Totals")),
            (70, "payments", _("Payments")),
            (80, "qr", _("ZATCA QR")),
            (90, "footer", _("Footer")),
        ]
        for template in self.filtered(lambda rec: not rec.block_ids):
            Block.create(
                [
                    {
                        "template_id": template.id,
                        "sequence": sequence,
                        "block_type": block_type,
                        "title": title,
                    }
                    for sequence, block_type, title in defaults
                ]
            )
