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
    # Legacy single-source field kept for upgrade compatibility. New UI and logic use
    # source_pos_category_ids so one public category can aggregate several POS categories.
    pos_category_id = fields.Many2one("pos.category", string="Source POS Category (Legacy)")
    source_pos_category_ids = fields.Many2many(
        "pos.category",
        "flexsys_menu_category_pos_category_rel",
        "menu_category_id",
        "pos_category_id",
        string="Source POS Categories",
        help="Optional POS categories grouped into this public Digital Menu category.",
    )
    sequence = fields.Integer(default=10)
    visible = fields.Boolean(default=True)
    featured = fields.Boolean(default=False)
    image = fields.Image(max_width=1024, max_height=1024)
    icon = fields.Char(help="Optional emoji or short icon text.")
    slab_background = fields.Char(help="Optional #RRGGBB override. Leave empty to inherit the theme.")
    public_key = fields.Char(default=lambda self: uuid.uuid4().hex[:16], required=True, copy=False, index=True)


    def init(self):
        """Upgrade bridge from the old Many2one source POS category to Many2many.

        The legacy column remains intentionally so upgrades are non-destructive. Odoo
        creates the M2M relation before model init; this statement is idempotent.
        """
        self.env.cr.execute("SELECT to_regclass(%s)", ("flexsys_menu_category_pos_category_rel",))
        if not self.env.cr.fetchone()[0]:
            return
        self.env.cr.execute("""
            INSERT INTO flexsys_menu_category_pos_category_rel (menu_category_id, pos_category_id)
            SELECT id, pos_category_id
              FROM flexsys_menu_category
             WHERE pos_category_id IS NOT NULL
            ON CONFLICT DO NOTHING
        """)

    def matches_product_pos_category(self, product):
        """Return whether product belongs to one of this category's POS sources.

        Odoo versions differ in the product-side POS category field name, so this
        is deliberately tolerant while remaining ORM-only at runtime.
        """
        self.ensure_one()
        if not self.source_pos_category_ids:
            return False
        if "pos_categ_ids" in product._fields:
            return bool(product.pos_categ_ids & self.source_pos_category_ids)
        if "pos_categ_id" in product._fields and product.pos_categ_id:
            return product.pos_categ_id in self.source_pos_category_ids
        return False

    _public_key_unique = models.Constraint(
        "unique(public_key)",
        "Category public key must be unique.",
    )
    @api.constrains("slab_background")
    def _check_slab_background(self):
        for record in self:
            if record.slab_background and not HEX_RE.match(record.slab_background):
                raise ValidationError("Slab background must use #RRGGBB format.")

