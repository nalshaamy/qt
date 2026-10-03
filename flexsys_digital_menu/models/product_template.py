from odoo import api, fields, models

from .menu_product import BADGE_TYPES


class ProductTemplate(models.Model):
    _inherit = "product.template"

    digital_menu_enabled = fields.Boolean(string="Digital Menu Enabled", default=False)
    digital_menu_short_description = fields.Text(string="Default Short Description", translate=True)
    digital_menu_image = fields.Image(string="Default Menu Image", max_width=1600, max_height=1600)
    digital_menu_calories = fields.Float(string="Calories", digits=(10, 1))
    digital_menu_ingredients = fields.Text(string="Ingredients", translate=True)
    digital_menu_allergens = fields.Text(string="Allergens", translate=True)
    digital_menu_spicy_level = fields.Selection(
        [("none", "Not Spicy"), ("mild", "Mild"), ("medium", "Medium"), ("hot", "Hot")],
        default="none",
    )
    digital_menu_vegetarian = fields.Boolean(string="Vegetarian")
    digital_menu_vegan = fields.Boolean(string="Vegan")
    digital_menu_gluten_info = fields.Selection(
        [("unknown", "Not Specified"), ("contains", "Contains Gluten"), ("free", "Gluten Free")],
        default="unknown",
    )
    digital_menu_featured_default = fields.Boolean(string="Featured by Default")
    digital_menu_default_badge = fields.Selection(BADGE_TYPES, default="none", string="Default Badge")
    digital_menu_custom_badge = fields.Char(string="Custom Badge", translate=True)
    digital_menu_notes = fields.Text(string="Internal Menu Notes")
    digital_menu_availability = fields.Selection(
        [("available", "Available"), ("sold_out", "Sold Out"), ("hidden", "Hidden")],
        default="available",
        required=True,
    )

    digital_menu_line_ids = fields.One2many("flexsys.menu.product", "product_tmpl_id", string="Menu Assignments")
    digital_menu_count = fields.Integer(compute="_compute_digital_menu_summary")
    digital_menu_branch_count = fields.Integer(compute="_compute_digital_menu_summary")
    digital_menu_is_featured = fields.Boolean(compute="_compute_digital_menu_summary")

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
