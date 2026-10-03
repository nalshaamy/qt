from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from .menu_product import BADGE_TYPES


class ProductTemplate(models.Model):
    _inherit = "product.template"

    # Simple daily-use controls. This is the single master switch exposed to users.
    digital_menu_enabled = fields.Boolean(string="Show in Digital Menu", default=False)
    digital_menu_short_description = fields.Text(string="Short Description", translate=True)
    digital_menu_image = fields.Image(string="Menu Image", max_width=1600, max_height=1600)
    digital_menu_calories = fields.Float(string="Calories", digits=(10, 1))
    digital_menu_ingredients = fields.Text(string="Ingredients", translate=True)
    digital_menu_allergens = fields.Text(string="Allergens", translate=True)
    digital_menu_spicy_level = fields.Selection(
        [("none", "Not Spicy"), ("mild", "Mild"), ("medium", "Medium"), ("hot", "Hot")],
        default="none",
        string="Spicy Level",
    )
    digital_menu_vegetarian = fields.Boolean(string="Vegetarian")
    digital_menu_vegan = fields.Boolean(string="Vegan")
    digital_menu_gluten_info = fields.Selection(
        [("unknown", "Not Specified"), ("contains", "Contains Gluten"), ("free", "Gluten Free")],
        default="unknown",
        string="Gluten Info",
    )
    digital_menu_featured_default = fields.Boolean(string="Featured")
    digital_menu_default_badge = fields.Selection(BADGE_TYPES, default="none", string="Badge")
    digital_menu_custom_badge = fields.Char(string="Custom Badge", translate=True)
    digital_menu_notes = fields.Text(string="Internal Menu Notes")

    # Internal default availability. It intentionally is not shown as a second checkbox
    # in the simple product UI. Effective availability is calculated by the menu engine.
    digital_menu_availability = fields.Selection(
        [("available", "Available"), ("sold_out", "Sold Out"), ("hidden", "Hidden")],
        default="available",
        required=True,
    )

    digital_menu_line_ids = fields.One2many("flexsys.menu.product", "product_tmpl_id", string="Menu Assignments")

    # Simple-mode proxy fields. Canonical menu-specific data stays in flexsys.menu.product;
    # these fields expose the primary/base assignment without duplicating its data.
    digital_menu_primary_menu_id = fields.Many2one(
        "flexsys.menu",
        string="Menu",
        compute="_compute_digital_menu_simple_fields",
        inverse="_inverse_digital_menu_primary_menu_id",
    )
    digital_menu_primary_category_id = fields.Many2one(
        "flexsys.menu.category",
        string="Menu Category",
        compute="_compute_digital_menu_simple_fields",
        inverse="_inverse_digital_menu_primary_category_id",
    )
    digital_menu_display_order = fields.Integer(
        string="Display Order",
        compute="_compute_digital_menu_simple_fields",
        inverse="_inverse_digital_menu_display_order",
    )

    # Kept for compatibility / advanced use, but no longer shown as a status dashboard.
    digital_menu_count = fields.Integer(compute="_compute_digital_menu_summary")
    digital_menu_branch_count = fields.Integer(compute="_compute_digital_menu_summary")
    digital_menu_is_featured = fields.Boolean(compute="_compute_digital_menu_summary")

    def _digital_menu_simple_line(self):
        """Return the primary menu assignment used by the simple product UI.

        Prefer a menu-wide/base rule. If an older installation only has a branch
        override, expose that line so users do not lose sight of their assignment;
        the first edit in simple mode promotes it to a base rule when safe.
        """
        self.ensure_one()
        lines = self.digital_menu_line_ids.sorted(lambda line: (line.sequence, line.id))
        base_lines = lines.filtered(lambda line: not line.pos_config_id)
        return base_lines[:1] or lines[:1]

    @api.depends(
        "digital_menu_line_ids",
        "digital_menu_line_ids.menu_id",
        "digital_menu_line_ids.category_id",
        "digital_menu_line_ids.sequence",
        "digital_menu_line_ids.pos_config_id",
    )
    def _compute_digital_menu_simple_fields(self):
        for product in self:
            line = product._digital_menu_simple_line()
            product.digital_menu_primary_menu_id = line.menu_id if line else False
            product.digital_menu_primary_category_id = line.category_id if line else False
            product.digital_menu_display_order = line.sequence if line else 10

    def _ensure_digital_menu_simple_base_line(self, menu=None):
        """Get/create the canonical base assignment for simple-mode edits."""
        self.ensure_one()
        menu = menu or self.digital_menu_primary_menu_id
        if not menu:
            return self.env["flexsys.menu.product"]

        base = self.digital_menu_line_ids.filtered(
            lambda line: line.menu_id == menu and not line.pos_config_id
        )[:1]
        if base:
            return base

        current = self._digital_menu_simple_line()
        # Upgrade-friendly behavior: old simple assignments may have been created as
        # branch overrides. Promote the matching line to menu-wide instead of forcing
        # the user to recreate it.
        if current and current.menu_id == menu and current.pos_config_id:
            current.write({"pos_config_id": False})
            return current

        if current and not current.pos_config_id and len(self.digital_menu_line_ids.filtered(lambda l: not l.pos_config_id)) == 1:
            values = {"menu_id": menu.id}
            if current.category_id and current.category_id.menu_id != menu:
                values["category_id"] = False
            current.write(values)
            return current

        return self.env["flexsys.menu.product"].create({
            "menu_id": menu.id,
            "product_tmpl_id": self.id,
            "sequence": 10,
            "visibility": "inherit",
        })

    def _inverse_digital_menu_primary_menu_id(self):
        for product in self:
            menu = product.digital_menu_primary_menu_id
            current = product._digital_menu_simple_line()
            if not menu:
                # Clearing the simple Menu only removes the primary base rule. Advanced
                # additional assignments/branch overrides are preserved deliberately.
                if current and not current.pos_config_id:
                    current.unlink()
                continue
            line = product._ensure_digital_menu_simple_base_line(menu=menu)
            if line.category_id and line.category_id.menu_id != menu:
                line.category_id = False

    def _inverse_digital_menu_primary_category_id(self):
        for product in self:
            menu = product.digital_menu_primary_menu_id
            category = product.digital_menu_primary_category_id
            if not menu:
                if category:
                    raise ValidationError(_("Select a Digital Menu before selecting a Menu Category."))
                continue
            if category and category.menu_id != menu:
                raise ValidationError(_("The selected category must belong to the selected Digital Menu."))
            line = product._ensure_digital_menu_simple_base_line(menu=menu)
            line.category_id = category

    def _inverse_digital_menu_display_order(self):
        for product in self:
            menu = product.digital_menu_primary_menu_id
            if not menu:
                continue
            line = product._ensure_digital_menu_simple_base_line(menu=menu)
            line.sequence = product.digital_menu_display_order or 10

    @api.onchange("digital_menu_primary_menu_id")
    def _onchange_digital_menu_primary_menu_id(self):
        for product in self:
            if product.digital_menu_primary_category_id and (
                not product.digital_menu_primary_menu_id
                or product.digital_menu_primary_category_id.menu_id != product.digital_menu_primary_menu_id
            ):
                product.digital_menu_primary_category_id = False

    @api.depends("digital_menu_line_ids", "digital_menu_line_ids.pos_config_id", "digital_menu_line_ids.featured_mode")
    def _compute_digital_menu_summary(self):
        for product in self:
            product.digital_menu_count = len(product.digital_menu_line_ids.mapped("menu_id"))
            product.digital_menu_branch_count = len(product.digital_menu_line_ids.mapped("pos_config_id"))
            product.digital_menu_is_featured = any(line._effective_featured_bool() for line in product.digital_menu_line_ids)

    def action_preview_digital_menu(self):
        self.ensure_one()
        lines = self.digital_menu_line_ids.filtered(lambda line: line.menu_id.state == "published")
        line = lines[:1] or self.digital_menu_line_ids[:1]
        if not line:
            return False
        return {
            "type": "ir.actions.act_url",
            "url": f"/digital-menu/preview-content/{line.menu_id.id}#product={line.public_key}",
            "target": "new",
        }

    def action_open_digital_menu_advanced(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Advanced Digital Menu Settings"),
            "res_model": "flexsys.menu.product",
            "view_mode": "list,form",
            "domain": [("product_tmpl_id", "=", self.id)],
            "context": {"default_product_tmpl_id": self.id},
        }
