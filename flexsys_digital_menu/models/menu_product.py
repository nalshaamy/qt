import uuid

from odoo import api, fields, models
from odoo.exceptions import ValidationError


BADGE_TYPES = [
    ("none", "None"),
    ("featured", "Featured"),
    ("best_seller", "Best Seller"),
    ("new", "New"),
    ("chef", "Chef Recommendation"),
    ("seasonal", "Seasonal"),
    ("custom", "Custom"),
]


class FlexSysMenuProduct(models.Model):
    _name = "flexsys.menu.product"
    _description = "FlexSys Digital Menu Product Assignment"
    _order = "sequence, id"

    menu_id = fields.Many2one("flexsys.menu", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="menu_id.company_id", store=True, index=True)
    product_tmpl_id = fields.Many2one(
        "product.template",
        required=True,
        ondelete="cascade",
        index=True,
        domain="[('sale_ok', '=', True)]",
    )
    category_id = fields.Many2one("flexsys.menu.category", ondelete="set null", domain="[('menu_id', '=', menu_id)]")
    pos_config_id = fields.Many2one(
        "pos.config",
        string="Branch / POS",
        ondelete="cascade",
        domain="[('company_id', '=', company_id)]",
        help="Leave empty for the menu-wide rule. Set a POS configuration to create a branch override.",
    )
    is_branch_override = fields.Boolean(compute="_compute_is_branch_override")

    sequence = fields.Integer(default=10)
    featured_sequence = fields.Integer(default=10)
    visibility = fields.Selection(
        [("inherit", "Inherit"), ("visible", "Visible"), ("hidden", "Hidden")],
        default="inherit",
        required=True,
    )
    featured_mode = fields.Selection(
        [("inherit", "Inherit"), ("yes", "Featured"), ("no", "Not Featured")],
        default="inherit",
        required=True,
    )
    badge_mode = fields.Selection(
        [("inherit", "Inherit"), ("none", "No Badge"), ("custom", "Override Badge")],
        default="inherit",
        required=True,
    )
    badge_type = fields.Selection(BADGE_TYPES, default="none")
    custom_badge = fields.Char(translate=True)

    name_override = fields.Char(translate=True)
    description_override = fields.Text(translate=True)
    image_override = fields.Image(max_width=1600, max_height=1600)

    availability_override = fields.Selection(
        [
            ("inherit", "Inherit"),
            ("available", "Available"),
            ("sold_out", "Sold Out"),
            ("hidden", "Hidden"),
        ],
        default="inherit",
        required=True,
    )
    schedule_id = fields.Many2one("flexsys.menu.schedule", ondelete="set null")

    price_mode = fields.Selection(
        [("inherit", "Inherit"), ("odoo", "Odoo / Pricelist"), ("override", "Fixed Menu Price")],
        default="inherit",
        required=True,
    )
    override_price = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(related="menu_id.currency_id", store=True, readonly=True)

    public_key = fields.Char(default=lambda self: uuid.uuid4().hex[:16], required=True, copy=False, index=True)

    effective_visibility = fields.Char(compute="_compute_effective_preview")
    effective_availability = fields.Char(compute="_compute_effective_preview")
    effective_featured = fields.Boolean(compute="_compute_effective_preview")
    effective_price = fields.Monetary(compute="_compute_effective_preview", currency_field="currency_id")

    _sql_constraints = [
        ("public_key_unique", "unique(public_key)", "Menu product public key must be unique."),
    ]


    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        products = records.mapped("product_tmpl_id").filtered(lambda product: not product.digital_menu_enabled)
        if products:
            products.write({"digital_menu_enabled": True})
        return records

    @api.depends("pos_config_id")
    def _compute_is_branch_override(self):
        for record in self:
            record.is_branch_override = bool(record.pos_config_id)

    @api.constrains("menu_id", "product_tmpl_id", "pos_config_id")
    def _check_unique_assignment(self):
        for record in self:
            domain = [
                ("id", "!=", record.id),
                ("menu_id", "=", record.menu_id.id),
                ("product_tmpl_id", "=", record.product_tmpl_id.id),
            ]
            if record.pos_config_id:
                domain.append(("pos_config_id", "=", record.pos_config_id.id))
            else:
                domain.append(("pos_config_id", "=", False))
            if self.search_count(domain):
                raise ValidationError("A product can only have one rule per menu and branch.")

    @api.constrains("menu_id", "category_id", "pos_config_id", "schedule_id")
    def _check_relational_consistency(self):
        for record in self:
            if record.category_id and record.category_id.menu_id != record.menu_id:
                raise ValidationError("The selected category must belong to the same menu.")
            if record.pos_config_id and record.pos_config_id.company_id != record.menu_id.company_id:
                raise ValidationError("The branch/POS must belong to the same company as the menu.")
            if record.pos_config_id and record.pos_config_id not in record.menu_id.pos_config_ids:
                raise ValidationError("The branch/POS must be enabled on the menu before using it as an override.")
            if record.schedule_id and record.schedule_id.company_id and record.schedule_id.company_id != record.menu_id.company_id:
                raise ValidationError("The schedule must belong to the menu company or be shared.")

    def _base_line(self):
        self.ensure_one()
        if not self.pos_config_id:
            return self
        return self.search(
            [
                ("menu_id", "=", self.menu_id.id),
                ("product_tmpl_id", "=", self.product_tmpl_id.id),
                ("pos_config_id", "=", False),
            ],
            limit=1,
        )

    def _effective_line_value(self, field_name, inherit_value="inherit"):
        self.ensure_one()
        value = self[field_name]
        if self.pos_config_id and value == inherit_value:
            base = self._base_line()
            if base and base != self:
                return base[field_name]
        return value

    def _effective_visibility_bool(self):
        self.ensure_one()
        # Product-level Show in Digital Menu is the single master switch.
        # Advanced rules can further hide a product, but never bypass this switch.
        if not self.product_tmpl_id.digital_menu_enabled:
            return False
        value = self._effective_line_value("visibility")
        if value == "hidden":
            return False
        return True

    def _effective_featured_bool(self):
        self.ensure_one()
        value = self._effective_line_value("featured_mode")
        if value == "yes":
            return True
        if value == "no":
            return False
        return bool(self.product_tmpl_id.digital_menu_featured_default)

    def _effective_badge(self):
        self.ensure_one()
        line = self
        mode = line.badge_mode
        if self.pos_config_id and mode == "inherit":
            base = self._base_line()
            if base and base != self and base.badge_mode != "inherit":
                line = base
                mode = base.badge_mode
        if mode == "none":
            return ("none", "")
        if mode == "custom":
            return (line.badge_type or "none", line.custom_badge or "")
        return (self.product_tmpl_id.digital_menu_default_badge or "none", self.product_tmpl_id.digital_menu_custom_badge or "")

    def _effective_category(self):
        self.ensure_one()
        if self.category_id:
            return self.category_id
        if self.pos_config_id:
            base = self._base_line()
            if base and base.category_id:
                return base.category_id
        return self.env["flexsys.menu.category"]

    def _effective_name(self):
        self.ensure_one()
        if self.name_override:
            return self.name_override
        if self.pos_config_id:
            base = self._base_line()
            if base and base.name_override:
                return base.name_override
        return self.product_tmpl_id.name

    def _effective_description(self):
        self.ensure_one()
        if self.description_override:
            return self.description_override
        if self.pos_config_id:
            base = self._base_line()
            if base and base.description_override:
                return base.description_override
        return self.product_tmpl_id.digital_menu_short_description or ""

    def _effective_image_source(self):
        self.ensure_one()
        if self.image_override:
            return self.image_override
        if self.pos_config_id:
            base = self._base_line()
            if base and base.image_override:
                return base.image_override
        return self.product_tmpl_id.digital_menu_image or self.product_tmpl_id.image_1024

    def _effective_availability_value(self):
        self.ensure_one()
        value = self._effective_line_value("availability_override")
        if value != "inherit":
            return value
        return self.product_tmpl_id.digital_menu_availability or "available"

    def _effective_schedule(self):
        self.ensure_one()
        if self.schedule_id:
            return self.schedule_id
        if self.pos_config_id:
            base = self._base_line()
            if base and base.schedule_id:
                return base.schedule_id
        return self.env["flexsys.menu.schedule"]

    def _effective_price_mode(self):
        self.ensure_one()
        if self.price_mode != "inherit":
            return self.price_mode, self.override_price
        if self.pos_config_id:
            base = self._base_line()
            if base and base.price_mode != "inherit":
                return base.price_mode, base.override_price
        return "odoo", 0.0

    def _get_pricelist(self):
        self.ensure_one()
        if self.pos_config_id and "pricelist_id" in self.pos_config_id._fields and self.pos_config_id.pricelist_id:
            return self.pos_config_id.pricelist_id
        return self.menu_id.pricelist_id

    def _get_effective_price(self, variant=None):
        self.ensure_one()
        mode, override = self._effective_price_mode()
        if mode == "override":
            return override
        variant = variant or self.product_tmpl_id.product_variant_id
        pricelist = self._get_pricelist()
        if pricelist and variant:
            return pricelist._get_product_price(variant, 1.0)
        return variant.lst_price if variant else self.product_tmpl_id.list_price

    def _get_effective_availability(self, stock_qty=None):
        self.ensure_one()
        value = self._effective_availability_value()
        if value in ("hidden", "sold_out"):
            return value

        schedule = self._effective_schedule()
        if schedule and not schedule.is_active_at(tz_name=self.menu_id.timezone):
            return "hidden"

        if self.menu_id.availability_source == "stock" and self.product_tmpl_id.is_storable:
            if stock_qty is None:
                variants = self.product_tmpl_id.product_variant_ids
                stock_qty = sum(variants.mapped("qty_available")) if variants else 0.0
            if stock_qty <= 0:
                return "sold_out"
        return "available"

    @api.depends(
        "visibility", "featured_mode", "availability_override", "price_mode", "override_price",
        "pos_config_id", "menu_id.pricelist_id", "product_tmpl_id.list_price",
        "product_tmpl_id.digital_menu_enabled", "product_tmpl_id.digital_menu_availability",
        "product_tmpl_id.digital_menu_featured_default",
    )
    def _compute_effective_preview(self):
        for record in self:
            if not record.product_tmpl_id or not record.menu_id:
                record.effective_visibility = "Hidden"
                record.effective_availability = "Hidden"
                record.effective_featured = False
                record.effective_price = 0.0
                continue
            visible = record._effective_visibility_bool()
            availability = record._get_effective_availability() if visible else "hidden"
            record.effective_visibility = "Visible" if visible else "Hidden"
            record.effective_availability = dict([
                ("available", "Available"), ("sold_out", "Sold Out"), ("hidden", "Hidden")
            ]).get(availability, availability)
            record.effective_featured = record._effective_featured_bool()
            try:
                record.effective_price = record._get_effective_price()
            except Exception:
                record.effective_price = record.product_tmpl_id.list_price
