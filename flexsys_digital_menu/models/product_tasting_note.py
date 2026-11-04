from odoo import fields, models


class FlexSysProductTastingNote(models.Model):
    _name = "flexsys.product.tasting.note"
    _description = "Product Tasting Note"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)

    name = fields.Char(
        string="Tasting Note",
        required=True,
        translate=True,
    )

    product_tmpl_id = fields.Many2one(
        "product.template",
        string="Product",
        required=True,
        ondelete="cascade",
        index=True,
    )