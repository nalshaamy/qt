import re
import unicodedata
import uuid

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


PAGE_SLUG_RE = re.compile(r"^[\w-]+$", re.UNICODE)


def _page_slugify(value):
    value = unicodedata.normalize("NFKC", value or "").strip().lower()
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"[^\w-]", "", value, flags=re.UNICODE)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or f"page-{uuid.uuid4().hex[:6]}"


class FlexSysBrandPage(models.Model):
    _name = "flexsys.brand.page"
    _description = "FlexSys Brand Page"
    _order = "sequence, name, id"

    name = fields.Char(required=True, translate=True, help="Navigation label shown to customers.")
    title = fields.Char(translate=True, help="Public page heading. Falls back to the navigation label.")
    subtitle = fields.Char(translate=True)
    body_html = fields.Html(string="Content", translate=True, sanitize=True)
    slug = fields.Char(required=True, index=True)
    page_type = fields.Selection(
        [
            ("about", "About Brand"),
            ("branches", "Branches"),
            ("custom", "Custom Page"),
        ],
        default="custom",
        required=True,
    )
    sequence = fields.Integer(default=20)
    is_published = fields.Boolean(default=False, string="Published")
    show_in_navigation = fields.Boolean(default=True, string="Show in Navigation")
    seo_title = fields.Char(translate=True)

    menu_id = fields.Many2one("flexsys.menu", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="menu_id.company_id", store=True, readonly=True, index=True)
    public_url = fields.Char(compute="_compute_public_url")

    _sql_constraints = [
        ("slug_menu_unique", "unique(slug, menu_id)", "Page slug must be unique within the Digital Menu."),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals["slug"] = _page_slugify(vals.get("slug") or vals.get("name"))
        return super().create(vals_list)

    def write(self, vals):
        if "slug" in vals:
            vals["slug"] = _page_slugify(vals["slug"])
        return super().write(vals)

    @api.constrains("slug")
    def _check_slug(self):
        for page in self:
            if not PAGE_SLUG_RE.match(page.slug or ""):
                raise ValidationError(_("Page slug may only contain letters, numbers, underscores and hyphens."))

    @api.depends("menu_id.public_url", "slug")
    def _compute_public_url(self):
        for page in self:
            page.public_url = f"{(page.menu_id.public_url or '').rstrip('/')}/page/{page.slug}" if page.menu_id else False
