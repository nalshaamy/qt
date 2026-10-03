import uuid

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .menu_theme import HEX_RE


class FlexSysMenuCategory(models.Model):
    _name = "flexsys.menu.category"
    _description = "FlexSys Digital Menu Category"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    menu_id = fields.Many2one("flexsys.menu", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="menu_id.company_id", store=True, index=True)
    pos_category_id = fields.Many2one("pos.category", string="Source POS Category")
    sequence = fields.Integer(default=10)
    visible = fields.Boolean(default=True)
    featured = fields.Boolean(default=False)
    image = fields.Image(max_width=1024, max_height=1024)
    icon = fields.Char(help="Optional emoji or short icon text.")
    slab_background = fields.Char(help="Optional #RRGGBB override. Leave empty to inherit the theme.")
    public_key = fields.Char(default=lambda self: uuid.uuid4().hex[:16], required=True, copy=False, index=True)

    _sql_constraints = [
        ("public_key_unique", "unique(public_key)", "Category public key must be unique."),
    ]
    @api.constrains("slab_background")
    def _check_slab_background(self):
        for record in self:
            if record.slab_background and not HEX_RE.match(record.slab_background):
                raise ValidationError("Slab background must use #RRGGBB format.")

