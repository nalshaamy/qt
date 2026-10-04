import base64
import colorsys
import hashlib
import io
import re
import unicodedata
import uuid
from collections import Counter
from datetime import datetime
from urllib.parse import urlparse

import pytz

import qrcode
from PIL import Image
from qrcode.image.svg import SvgPathImage

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


DOMAIN_RE = re.compile(r"^[A-Za-z0-9.-]+(?::[0-9]+)?$")
SLUG_RE = re.compile(r"^[\w-]+$", re.UNICODE)
LAYOUT_STYLES = [("cards", "Cards"), ("compact", "Compact"), ("image_focus", "Image Focused")]


def _slugify(value):
    value = unicodedata.normalize("NFKC", value or "").strip().lower()
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"[^\w-]", "", value, flags=re.UNICODE)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or f"menu-{uuid.uuid4().hex[:6]}"


def _hex(rgb):
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(round(v)))) for v in rgb)


def _rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _blend(color, target, ratio):
    c = _rgb(color) if isinstance(color, str) else color
    t = _rgb(target) if isinstance(target, str) else target
    return _hex(tuple(c[i] * (1 - ratio) + t[i] * ratio for i in range(3)))


def _relative_luminance(color):
    rgb = [v / 255.0 for v in (_rgb(color) if isinstance(color, str) else color)]

    def channel(v):
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = [channel(v) for v in rgb]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b):
    l1, l2 = sorted((_relative_luminance(a), _relative_luminance(b)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


def _best_text(bg):
    dark = "#17201D"
    light = "#FFFFFF"
    return dark if _contrast(bg, dark) >= _contrast(bg, light) else light


def _color_distance(a, b):
    ar, ag, ab = a
    br, bg, bb = b
    return (ar - br) ** 2 + (ag - bg) ** 2 + (ab - bb) ** 2


class FlexSysMenu(models.Model):
    _name = "flexsys.menu"
    _description = "FlexSys Digital Menu"
    _order = "company_id, sequence, name"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    slug = fields.Char(required=True, index=True)
    public_domain = fields.Char(
        help="Optional hostname used for this menu, e.g. qtcafe.sa. Leave blank to use Odoo web.base.url."
    )
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    pos_config_ids = fields.Many2many(
        "pos.config",
        "flexsys_menu_pos_config_rel",
        "menu_id",
        "pos_config_id",
        string="Branches / POS Configurations",
        domain="[('company_id', '=', company_id)]",
    )
    pricelist_id = fields.Many2one("product.pricelist", check_company=True)
    currency_id = fields.Many2one("res.currency", compute="_compute_currency", store=True, readonly=True)
    timezone = fields.Char(default=lambda self: self.env.company.partner_id.tz or self.env.user.tz or "Asia/Riyadh")

    language_ar = fields.Boolean(default=True, string="Arabic")
    language_en = fields.Boolean(default=True, string="English")
    default_language = fields.Selection([("ar", "Arabic"), ("en", "English")], default="ar", required=True)

    theme_id = fields.Many2one("flexsys.menu.theme", required=True, default=lambda self: self._default_theme())
    brand_name = fields.Char(translate=True, string="Brand Name", help="Public brand name. Falls back to the company name when empty.")
    logo = fields.Image(max_width=1600, max_height=1600)
    hero_image = fields.Image(max_width=2400, max_height=1600)
    tagline = fields.Char(translate=True)
    seo_title = fields.Char(translate=True)
    layout_style_raw = fields.Selection(LAYOUT_STYLES, default="cards", string="Menu Layout (Stored)")
    layout_style = fields.Selection(
        LAYOUT_STYLES, compute="_compute_layout_style", inverse="_inverse_layout_style", string="Menu Layout"
    )
    header_text_color_override = fields.Char(string="Header Text Color", help="Optional #RRGGBB override. Leave empty for automatic contrast.")
    footer_text_color_override = fields.Char(string="Footer Text Color", help="Optional #RRGGBB override. Leave empty for automatic contrast.")

    show_product_images = fields.Boolean(default=True)
    show_descriptions = fields.Boolean(default=True)
    show_prices = fields.Boolean(default=True)
    show_calories = fields.Boolean(default=True)
    show_badges = fields.Boolean(default=True)
    show_dietary = fields.Boolean(default=True)
    show_variants = fields.Boolean(default=True)
    show_ingredients = fields.Boolean(default=True)
    show_allergens = fields.Boolean(default=True)

    state = fields.Selection(
        [("draft", "Draft"), ("published", "Published"), ("archived", "Archived")],
        default="draft",
        required=True,
        index=True,
    )
    is_published = fields.Boolean(compute="_compute_is_published", store=True)
    start_date = fields.Date()
    end_date = fields.Date()
    schedule_ids = fields.Many2many(
        "flexsys.menu.schedule",
        "flexsys_menu_schedule_rel",
        "menu_id",
        "schedule_id",
        string="Schedules",
    )

    availability_source = fields.Selection(
        [("manual", "Manual"), ("stock", "Odoo Stock")],
        default="manual",
        required=True,
    )
    sold_out_behavior = fields.Selection(
        [("show", "Show as Sold Out"), ("hide", "Hide Product")],
        default="show",
        required=True,
    )
    empty_category_behavior = fields.Selection(
        [("hide", "Hide Empty Categories"), ("show", "Show Empty Categories")],
        default="hide",
        required=True,
    )

    category_ids = fields.One2many("flexsys.menu.category", "menu_id", string="Categories")
    product_line_ids = fields.One2many("flexsys.menu.product", "menu_id", string="Products")
    qr_ids = fields.One2many("flexsys.menu.qr", "menu_id", string="QR Codes")
    page_ids = fields.One2many("flexsys.brand.page", "menu_id", string="Brand Pages")
    offer_ids = fields.One2many("flexsys.menu.offer", "menu_id", string="Offers")
    analytics_event_ids = fields.One2many("flexsys.menu.analytics.event", "menu_id", string="Analytics Events")

    analytics_disabled = fields.Boolean(default=False, string="Analytics Disabled")
    analytics_enabled = fields.Boolean(
        compute="_compute_analytics_enabled", inverse="_inverse_analytics_enabled", string="Analytics"
    )
    analytics_retention_days_raw = fields.Integer(default=90, string="Analytics Retention (Days) (Stored)")
    analytics_retention_days = fields.Integer(
        compute="_compute_analytics_retention_days",
        inverse="_inverse_analytics_retention_days",
        string="Analytics Retention (Days)",
    )
    analytics_views = fields.Integer(compute="_compute_analytics_summary")
    analytics_product_opens = fields.Integer(compute="_compute_analytics_summary")
    analytics_searches = fields.Integer(compute="_compute_analytics_summary")
    analytics_top_product = fields.Char(compute="_compute_analytics_summary")
    analytics_top_category = fields.Char(compute="_compute_analytics_summary")
    analytics_top_search = fields.Char(compute="_compute_analytics_summary")
    analytics_arabic_share = fields.Float(compute="_compute_analytics_summary", digits=(5, 1))

    public_url = fields.Char(compute="_compute_public_url")
    product_count = fields.Integer(compute="_compute_counts")
    category_count = fields.Integer(compute="_compute_counts")
    branch_count = fields.Integer(compute="_compute_counts")

    _sql_constraints = [
        ("slug_company_unique", "unique(slug, company_id)", "Menu slug must be unique per company."),
    ]

    @api.constrains("header_text_color_override", "footer_text_color_override")
    def _check_text_color_overrides(self):
        for menu in self:
            for field_name in ("header_text_color_override", "footer_text_color_override"):
                value = (menu[field_name] or "").strip()
                if value and not re.match(r"^#[0-9A-Fa-f]{6}$", value):
                    raise ValidationError(_("Text color overrides must use #RRGGBB format."))

    @api.model
    def _default_theme(self):
        return self.env.ref("flexsys_digital_menu.theme_auto_default", raise_if_not_found=False)

    @api.depends("pricelist_id", "company_id")
    def _compute_currency(self):
        for menu in self:
            menu.currency_id = menu.pricelist_id.currency_id or menu.company_id.currency_id

    @api.depends("layout_style_raw")
    def _compute_layout_style(self):
        for menu in self:
            menu.layout_style = menu.layout_style_raw or "cards"

    def _inverse_layout_style(self):
        for menu in self:
            menu.layout_style_raw = menu.layout_style or "cards"

    @api.depends("state")
    def _compute_is_published(self):
        for menu in self:
            menu.is_published = menu.state == "published"

    @api.depends("slug", "public_domain")
    def _compute_public_url(self):
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        parsed = urlparse(base_url if "://" in base_url else f"https://{base_url}") if base_url else None
        default_scheme = parsed.scheme if parsed and parsed.scheme else "https"
        default_host = parsed.netloc if parsed else ""
        for menu in self:
            host = menu.public_domain or default_host
            if host:
                menu.public_url = f"{default_scheme}://{host}/menu/{menu.slug}"
            else:
                menu.public_url = f"/menu/{menu.slug}"

    @api.depends("product_line_ids", "category_ids", "pos_config_ids")
    def _compute_counts(self):
        for menu in self:
            menu.product_count = len(menu.product_line_ids.filtered(lambda line: not line.pos_config_id))
            menu.category_count = len(menu.category_ids)
            menu.branch_count = len(menu.pos_config_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals["slug"] = _slugify(vals.get("slug") or vals.get("name"))
            if vals.get("public_domain"):
                vals["public_domain"] = self._normalize_domain(vals["public_domain"])
        return super().create(vals_list)

    def write(self, vals):
        if "slug" in vals:
            vals["slug"] = _slugify(vals["slug"])
        if "public_domain" in vals and vals["public_domain"]:
            vals["public_domain"] = self._normalize_domain(vals["public_domain"])
        return super().write(vals)

    @api.model
    def _normalize_domain(self, domain):
        domain = (domain or "").strip().lower()
        if "://" in domain:
            domain = urlparse(domain).netloc
        return domain.rstrip("/")

    @api.constrains("slug", "public_domain", "start_date", "end_date")
    def _check_public_identity(self):
        for menu in self:
            if not SLUG_RE.match(menu.slug or ""):
                raise ValidationError("Slug may only contain letters, numbers, underscores and hyphens.")
            if menu.public_domain and not DOMAIN_RE.match(menu.public_domain):
                raise ValidationError("Public Domain must be a hostname such as qtcafe.sa.")
            if menu.start_date and menu.end_date and menu.start_date > menu.end_date:
                raise ValidationError("Start date cannot be after end date.")

    @api.constrains("company_id", "pos_config_ids", "pricelist_id", "theme_id", "schedule_ids")
    def _check_company_consistency(self):
        for menu in self:
            if any(pos.company_id != menu.company_id for pos in menu.pos_config_ids):
                raise ValidationError("All selected POS configurations must belong to the menu company.")
            if menu.pricelist_id and menu.pricelist_id.company_id and menu.pricelist_id.company_id != menu.company_id:
                raise ValidationError("The pricelist must belong to the menu company or be shared.")
            if menu.theme_id.company_id and menu.theme_id.company_id != menu.company_id:
                raise ValidationError("The theme must belong to the menu company or be shared.")
            if any(schedule.company_id and schedule.company_id != menu.company_id for schedule in menu.schedule_ids):
                raise ValidationError("Schedules must belong to the menu company or be shared.")

    @api.depends("analytics_disabled")
    def _compute_analytics_enabled(self):
        for menu in self:
            menu.analytics_enabled = not menu.analytics_disabled

    def _inverse_analytics_enabled(self):
        for menu in self:
            menu.analytics_disabled = not menu.analytics_enabled

    @api.depends("analytics_retention_days_raw")
    def _compute_analytics_retention_days(self):
        for menu in self:
            menu.analytics_retention_days = menu.analytics_retention_days_raw or 90

    def _inverse_analytics_retention_days(self):
        for menu in self:
            days = int(menu.analytics_retention_days or 90)
            if days < 7 or days > 365:
                raise ValidationError(_("Analytics retention must be between 7 and 365 days."))
            menu.analytics_retention_days_raw = days

    def _compute_analytics_summary(self):
        Event = self.env["flexsys.menu.analytics.event"].sudo()
        for menu in self:
            if not menu.id:
                menu.analytics_views = 0
                menu.analytics_product_opens = 0
                menu.analytics_searches = 0
                menu.analytics_top_product = False
                menu.analytics_top_category = False
                menu.analytics_top_search = False
                menu.analytics_arabic_share = 0.0
                continue
            base = [("menu_id", "=", menu.id)]
            menu.analytics_views = Event.search_count(base + [("event_type", "=", "menu_view")])
            menu.analytics_product_opens = Event.search_count(base + [("event_type", "=", "product_open")])
            menu.analytics_searches = Event.search_count(base + [("event_type", "=", "search")])

            def top_label(event_type, field_name):
                records = Event.search(
                    base + [("event_type", "=", event_type), (field_name, "!=", False)],
                    order="event_at desc", limit=50000,
                )
                counts = Counter(value for value in records.mapped(field_name) if value)
                return counts.most_common(1)[0][0] if counts else False

            menu.analytics_top_product = top_label("product_open", "reference_label")
            menu.analytics_top_category = top_label("category_filter", "reference_label")
            menu.analytics_top_search = top_label("search", "search_term")
            ar_count = Event.search_count(base + [("event_type", "=", "menu_view"), ("language", "=", "ar")])
            menu.analytics_arabic_share = (ar_count / menu.analytics_views * 100.0) if menu.analytics_views else 0.0

    def action_open_analytics(self):
        self.ensure_one()
        action = self.env.ref("flexsys_digital_menu.action_menu_analytics_events").read()[0]
        action["domain"] = [("menu_id", "=", self.id)]
        action["context"] = {"default_menu_id": self.id, "search_default_group_event_type": 1}
        return action

    def action_create_branches_page(self):
        self.ensure_one()
        page = self.page_ids.filtered(lambda p: p.page_type == "branches")[:1]
        if not page:
            page = self.page_ids.filtered(lambda p: p.slug == "branches")[:1]
            if page and page.page_type != "branches":
                raise UserError(_("A different Brand Page already uses the 'branches' slug. Rename it first."))
        if not page:
            page = self.env["flexsys.brand.page"].create({
                "menu_id": self.id,
                "name": _("Branches"),
                "title": _("Our Branches"),
                "slug": "branches",
                "page_type": "branches",
                "show_in_navigation": True,
                "is_published": False,
            })
        return {"type": "ir.actions.act_window", "res_model": "flexsys.brand.page", "res_id": page.id, "view_mode": "form"}

    @staticmethod
    def _format_hour(value):
        value = float(value or 0.0) % 24
        hour = int(value)
        minute = int(round((value - hour) * 60))
        if minute == 60:
            hour = (hour + 1) % 24
            minute = 0
        return f"{hour:02d}:{minute:02d}"

    def _public_branches_payload(self, requested_lang=None):
        self.ensure_one()
        lang_code, language = self._language_code(requested_lang)
        menu = self.sudo().with_company(self.company_id).with_context(lang=lang_code)
        day_labels = {
            "ar": ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"],
            "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        }
        payload = []
        for pos in menu.pos_config_ids.sorted(lambda p: (p.name or "", p.id)):
            hours = []
            for line in pos.digital_menu_hour_ids.sorted(lambda h: (int(h.weekday), h.sequence, h.time_from)):
                day = day_labels.get(language, day_labels["en"])[int(line.weekday)]
                hours.append({
                    "day": day,
                    "closed": bool(line.closed),
                    "from": menu._format_hour(line.time_from),
                    "to": menu._format_hour(line.time_to),
                })
            key = menu.branch_public_key(pos)
            payload.append({
                "key": key,
                "name": pos._digital_menu_public_name(),
                "description": pos.digital_menu_description or "",
                "address": pos.digital_menu_address or (pos.operations_branch_address if "operations_branch_address" in pos._fields else "") or "",
                "phone": pos.digital_menu_phone or "",
                "whatsapp": re.sub(r"\D", "", pos.digital_menu_whatsapp or ""),
                "map_url": pos._digital_menu_map_link(),
                "image_url": f"/menu/{menu.slug}/branch/{key}/image" if pos.digital_menu_image else "",
                "hours": hours,
                "is_open": pos._digital_menu_open_status(menu.timezone),
            })
        return payload

    def branch_public_key(self, pos_config):
        self.ensure_one()
        seed = f"{self.id}:{pos_config.id}:{self.create_date or ''}:{self.company_id.id}"
        return hashlib.sha256(seed.encode()).hexdigest()[:16]

    def resolve_branch_key(self, branch_key):
        self.ensure_one()
        if not branch_key:
            return self.pos_config_ids if len(self.pos_config_ids) == 1 else self.env["pos.config"]
        for pos_config in self.pos_config_ids:
            if self.branch_public_key(pos_config) == branch_key:
                return pos_config
        return self.env["pos.config"]

    def is_active_now(self, include_draft=False):
        self.ensure_one()
        if self.state != "published" and not include_draft:
            return False
        tz = pytz.timezone(self.timezone or "UTC")
        today = datetime.now(tz).date()
        if self.start_date and today < self.start_date:
            return False
        if self.end_date and today > self.end_date:
            return False
        if self.schedule_ids and not any(schedule.is_active_at(tz_name=self.timezone) for schedule in self.schedule_ids):
            return False
        return True

    def action_publish(self):
        for menu in self:
            menu.state = "published"
            menu.action_generate_qr()
        return True

    def action_draft(self):
        self.write({"state": "draft"})
        return True

    def action_archive_menu(self):
        self.write({"state": "archived"})
        return True

    def action_preview_backend(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/digital-menu/preview/{self.id}",
            "target": "new",
        }

    def action_open_public(self):
        self.ensure_one()
        return {"type": "ir.actions.act_url", "url": self.public_url, "target": "new"}

    def action_generate_qr(self):
        for menu in self:
            url = menu.public_url
            if not url:
                continue
            png_buffer = io.BytesIO()
            qrcode.make(url).save(png_buffer, format="PNG")
            svg_buffer = io.BytesIO()
            qrcode.make(url, image_factory=SvgPathImage).save(svg_buffer)
            values = {
                "menu_id": menu.id,
                "url": url,
                "png": base64.b64encode(png_buffer.getvalue()),
                "svg": base64.b64encode(svg_buffer.getvalue()),
            }
            qr = menu.qr_ids[:1]
            if qr:
                qr.write(values)
            else:
                self.env["flexsys.menu.qr"].create(values)
        return True

    def _extract_logo_colors(self):
        self.ensure_one()
        if not self.logo:
            raise UserError(_("Upload a logo before generating the brand theme."))
        raw = base64.b64decode(self.logo)
        image = Image.open(io.BytesIO(raw)).convert("RGBA")
        image.thumbnail((160, 160))
        white = Image.new("RGBA", image.size, "white")
        composed = Image.alpha_composite(white, image).convert("RGB")
        quantized = composed.quantize(colors=10, method=Image.Quantize.MEDIANCUT)
        palette = quantized.getpalette() or []
        color_counts = sorted(quantized.getcolors() or [], reverse=True)
        candidates = []
        for count, idx in color_counts:
            rgb = tuple(palette[idx * 3:idx * 3 + 3])
            if len(rgb) != 3:
                continue
            h, s, v = colorsys.rgb_to_hsv(*(channel / 255.0 for channel in rgb))
            if v > 0.96 or v < 0.08:
                continue
            score = count * (0.35 + s)
            candidates.append((score, rgb))
        if not candidates:
            candidates = [
                (100, (23, 63, 53)),
                (90, (54, 92, 80)),
                (80, (201, 167, 98)),
            ]
        candidates.sort(reverse=True, key=lambda item: item[0])
        primary_rgb = candidates[0][1]
        remaining = [rgb for _, rgb in candidates[1:]]
        secondary_rgb = max(remaining, key=lambda rgb: _color_distance(primary_rgb, rgb), default=(54, 92, 80))
        remaining2 = [rgb for rgb in remaining if rgb != secondary_rgb]
        accent_rgb = max(remaining2, key=lambda rgb: _color_distance(primary_rgb, rgb), default=(201, 167, 98))
        return _hex(primary_rgb), _hex(secondary_rgb), _hex(accent_rgb)

    def action_generate_brand(self):
        for menu in self:
            primary, secondary, accent = menu._extract_logo_colors()
            background = _blend(primary, "#FFFFFF", 0.96)
            surface = "#FFFFFF"
            slab = _blend(primary, "#FFFFFF", 0.90)
            border = _blend(primary, "#FFFFFF", 0.78)
            primary_light = _blend(primary, "#FFFFFF", 0.86)
            primary_dark = _blend(primary, "#000000", 0.28)
            main_text = "#17201D" if _contrast(background, "#17201D") >= 4.5 else "#000000"
            muted = _blend(main_text, background, 0.38)
            button_text = _best_text(primary)
            badge_text = _best_text(accent)
            values = {
                "name": f"{menu.name} Auto Brand",
                "company_id": menu.company_id.id,
                "mode": "auto",
                "primary": primary,
                "primary_light": primary_light,
                "primary_dark": primary_dark,
                "secondary": secondary,
                "accent": accent,
                "background": background,
                "surface": surface,
                "slab": slab,
                "border": border,
                "text": main_text,
                "text_muted": muted,
                "button_background": primary,
                "button_text": button_text,
                "selected": primary,
                "badge_background": accent,
                "badge_text": badge_text,
            }
            default_theme = self.env.ref("flexsys_digital_menu.theme_auto_default", raise_if_not_found=False)
            if menu.theme_id and menu.theme_id != default_theme and menu.theme_id.company_id == menu.company_id:
                menu.theme_id.write(values)
            else:
                menu.theme_id = self.env["flexsys.menu.theme"].create(values)
        return True

    def css_variables(self):
        self.ensure_one()
        theme = self.theme_id or self._default_theme()
        if not theme:
            return ""
        hero_text = (self.header_text_color_override or "").strip() or _best_text(theme.background)
        footer_text = (self.footer_text_color_override or "").strip() or _best_text(theme.background)
        return ";".join(filter(None, [
            theme.css_variables(),
            f"--menu-hero-text:{hero_text}",
            f"--menu-footer-text:{footer_text}",
        ]))

    def _language_code(self, requested):
        self.ensure_one()
        requested = requested if requested in ("ar", "en") else self.default_language
        if requested == "ar" and not self.language_ar:
            requested = "en"
        if requested == "en" and not self.language_en:
            requested = "ar"
        lang = self.env["res.lang"].sudo().search([("active", "=", True), ("code", "=ilike", f"{requested}%")], limit=1)
        return (lang.code if lang else self.env.user.lang), requested

    def _badge_label(self, badge_type, custom_badge, language=None):
        labels = {
            "ar": {
                "featured": "مميز",
                "best_seller": "الأكثر مبيعًا",
                "new": "جديد",
                "chef": "توصية الشيف",
                "seasonal": "موسمي",
            },
            "en": {
                "featured": "Featured",
                "best_seller": "Best Seller",
                "new": "New",
                "chef": "Chef Recommendation",
                "seasonal": "Seasonal",
            },
        }
        if badge_type == "custom":
            return custom_badge or ""
        return labels.get(language or "en", labels["en"]).get(badge_type, "")

    def _public_navigation(self, requested_lang=None, active_key="menu", preview=False):
        self.ensure_one()
        lang_code, language = self._language_code(requested_lang)
        menu = self.sudo().with_company(self.company_id).with_context(lang=lang_code)
        suffix = f"?lang={language}" if language in ("ar", "en") else ""
        items = [{
            "key": "menu",
            "label": "المنيو" if language == "ar" else "Menu",
            "url": f"/menu/{menu.slug}{suffix}",
            "active": active_key == "menu",
        }]
        offer_records = self.env["flexsys.menu.offer"].sudo().with_company(menu.company_id).with_context(lang=lang_code).search(
            [("menu_id", "=", menu.id)], order="sequence, id"
        )
        if any(offer.is_active_now(preview=preview) for offer in offer_records):
            items.append({
                "key": "offers",
                "label": "العروض" if language == "ar" else "Offers",
                "url": f"/menu/{menu.slug}{suffix}#fsm-offers",
                "active": active_key == "offers",
                "type": "offers",
            })
        domain = [
            ("menu_id", "=", menu.id),
            ("show_in_navigation", "=", True),
            ("is_published", "=", True),
        ]
        pages = self.env["flexsys.brand.page"].sudo().with_company(menu.company_id).with_context(lang=lang_code).search(
            domain, order="sequence, id"
        )
        for page in pages:
            items.append({
                "key": f"page:{page.slug}",
                "label": page.name,
                "url": f"/menu/{menu.slug}/page/{page.slug}{suffix}",
                "active": active_key == f"page:{page.slug}",
                "type": page.page_type,
            })
        return items

    def _public_payload(self, requested_lang=None, branch_key=None, preview=False):
        self.ensure_one()
        lang_code, language = self._language_code(requested_lang)
        menu = self.sudo().with_company(self.company_id).with_context(lang=lang_code)
        branch = menu.resolve_branch_key(branch_key)
        active_now = menu.is_active_now(include_draft=preview)
        asset_base = f"/digital-menu/preview-asset/{menu.id}" if preview else f"/menu/{menu.slug}"

        all_lines = self.env["flexsys.menu.product"].sudo().with_company(menu.company_id).with_context(lang=lang_code).search(
            [("menu_id", "=", menu.id)], order="sequence, id"
        )
        base_lines = {line.product_tmpl_id.id: line for line in all_lines if not line.pos_config_id}
        branch_lines = {
            line.product_tmpl_id.id: line
            for line in all_lines
            if branch and line.pos_config_id == branch
        }
        product_ids = list(dict.fromkeys(list(base_lines) + list(branch_lines)))
        effective_lines = [branch_lines.get(pid) or base_lines.get(pid) for pid in product_ids]
        stock_qty_by_template = {}
        if menu.availability_source == "stock":
            variants = self.env["product.product"].sudo().with_company(menu.company_id).browse(
                list({variant.id for line in effective_lines if line for variant in line.product_tmpl_id.product_variant_ids})
            )
            for variant in variants:
                stock_qty_by_template.setdefault(variant.product_tmpl_id.id, 0.0)
                stock_qty_by_template[variant.product_tmpl_id.id] += variant.qty_available

        categories = self.env["flexsys.menu.category"].sudo().with_company(menu.company_id).with_context(lang=lang_code).search(
            [("menu_id", "=", menu.id), ("visible", "=", True)], order="sequence, id"
        )
        category_map = {
            category.id: {
                "key": category.public_key,
                "name": category.name,
                "icon": category.icon or "",
                "featured": category.featured,
                "slab_background": category.slab_background or "",
                "image_url": f"{asset_base}/category/{category.public_key}/image" if category.image else "",
                "sequence": category.sequence,
            }
            for category in categories
        }

        products = []
        public_product_by_template = {}
        used_category_ids = set()
        if active_now:
            for line in effective_lines:
                if not line or not line._effective_visibility_bool():
                    continue
                availability = line._get_effective_availability(stock_qty=stock_qty_by_template.get(line.product_tmpl_id.id))
                if availability == "hidden":
                    continue
                if availability == "sold_out" and menu.sold_out_behavior == "hide":
                    continue
                category = line._effective_category()
                if category and (category.menu_id != menu or not category.visible):
                    continue
                if category:
                    used_category_ids.add(category.id)
                badge_type, custom_badge = line._effective_badge(language=language)
                variants = []
                for variant in line.product_tmpl_id.product_variant_ids:
                    attrs = []
                    if "product_template_attribute_value_ids" in variant._fields:
                        attrs = variant.product_template_attribute_value_ids.mapped("name")
                    variants.append({
                        "key": hashlib.sha256(f"{line.public_key}:{variant.id}".encode()).hexdigest()[:12],
                        "name": " / ".join(attrs) or variant.display_name,
                        "price": line._get_effective_price(variant),
                    })
                price = min([item["price"] for item in variants], default=line._get_effective_price())
                product = line.product_tmpl_id
                product_data = {
                    "key": line.public_key,
                    "category_key": category.public_key if category else "uncategorized",
                    "name": line._effective_name(),
                    "description": line._effective_description() if menu.show_descriptions else "",
                    "image_url": f"{asset_base}/product/{line.public_key}/image" if menu.show_product_images and line._effective_image_source() else "",
                    "price": price,
                    "price_from": len(variants) > 1,
                    "variants": variants if menu.show_variants else [],
                    "featured": line._effective_featured_bool(),
                    "featured_sequence": line.featured_sequence,
                    "badge": menu._badge_label(badge_type, custom_badge, language=language) if menu.show_badges else "",
                    "badge_type": badge_type if menu.show_badges else "none",
                    "badge_pulse": bool(menu.show_badges and badge_type in {"featured", "best_seller", "new", "chef"}),
                    "availability": availability,
                    "calories": (product.digital_menu_calories or 0) if menu.show_calories else 0,
                    "ingredients": (product.digital_menu_ingredients or "") if menu.show_ingredients else "",
                    "allergens": (product.digital_menu_allergens or "") if menu.show_allergens else "",
                    "spicy_level": (product.digital_menu_spicy_level or "none") if menu.show_dietary else "none",
                    "vegetarian": bool(product.digital_menu_vegetarian) if menu.show_dietary else False,
                    "vegan": bool(product.digital_menu_vegan) if menu.show_dietary else False,
                    "gluten_info": product.digital_menu_gluten_info or "unknown",
                    "sequence": line.sequence,
                    "search_text": " ".join(filter(None, [line._effective_name(), line._effective_description(), product.default_code or ""])),
                }
                products.append(product_data)
                public_product_by_template[product.id] = product_data

        category_payload = [value for cid, value in category_map.items() if menu.empty_category_behavior == "show" or cid in used_category_ids]
        if any(product["category_key"] == "uncategorized" for product in products):
            category_payload.append({
                "key": "uncategorized",
                "name": _("Other"),
                "icon": "",
                "featured": False,
                "slab_background": "",
                "image_url": "",
                "sequence": 9999,
            })

        currency = menu.currency_id
        branches = [
            {"key": menu.branch_public_key(pos), "name": pos._digital_menu_public_name()}
            for pos in menu.pos_config_ids
        ]

        offers = []
        if active_now:
            offer_records = self.env["flexsys.menu.offer"].sudo().with_company(menu.company_id).with_context(lang=lang_code).search(
                [("menu_id", "=", menu.id)], order="sequence, id"
            )
            for offer in offer_records:
                if not offer.is_active_now(preview=preview):
                    continue
                linked_products = [public_product_by_template.get(pid) for pid in offer.product_ids.ids if public_product_by_template.get(pid)]
                linked_keys = [item["key"] for item in linked_products]
                if offer.product_ids and not linked_keys:
                    continue
                offer_product_prices = {}
                offer_variant_prices = {}
                if offer.pricelist_id:
                    for product_tmpl in offer.product_ids:
                        product_data = public_product_by_template.get(product_tmpl.id)
                        if not product_data:
                            continue
                        variant_prices = []
                        for variant in product_tmpl.product_variant_ids:
                            variant_key = hashlib.sha256(f"{product_data['key']}:{variant.id}".encode()).hexdigest()[:12]
                            variant_price = offer.pricelist_id._get_product_price(variant, 1.0)
                            offer_variant_prices[variant_key] = variant_price
                            variant_prices.append(variant_price)
                        if variant_prices:
                            offer_product_prices[product_data["key"]] = min(variant_prices)
                offer_price = offer_product_prices.get(linked_keys[0]) if len(linked_keys) == 1 else None
                original_price = linked_products[0]["price"] if len(linked_products) == 1 else None
                offers.append({
                    "key": offer.public_key,
                    "name": offer.name,
                    "subtitle": offer.subtitle or "",
                    "description": offer.description or "",
                    "image_url": f"{asset_base}/offer/{offer.public_key}/image" if offer.image else "",
                    "product_keys": linked_keys,
                    "product_prices": offer_product_prices,
                    "variant_prices": offer_variant_prices,
                    "price": offer_price,
                    "original_price": original_price,
                    "has_pricelist": bool(offer.pricelist_id),
                })
        return {
            "menu": {
                "name": menu.name,
                "brand_name": menu.brand_name or menu.company_id.name or menu.name,
                "company_name": menu.company_id.name or menu.name,
                "tagline": menu.tagline or "",
                "slug": menu.slug,
                "url": menu.public_url,
                "language": language,
                "languages": [code for code, enabled in (("ar", menu.language_ar), ("en", menu.language_en)) if enabled],
                "active_now": active_now,
                "logo_url": f"{asset_base}/logo" if menu.logo else "",
                "hero_url": f"{asset_base}/hero" if menu.hero_image else "",
                "branch": {"key": menu.branch_public_key(branch), "name": branch._digital_menu_public_name()} if branch else None,
                "branches": branches,
                "navigation": menu._public_navigation(language, active_key="menu", preview=preview),
                "layout": menu.layout_style,
                "analytics": bool(menu.analytics_enabled and not preview),
            },
            "display": {
                "product_images": menu.show_product_images,
                "descriptions": menu.show_descriptions,
                "prices": menu.show_prices,
                "calories": menu.show_calories,
                "badges": menu.show_badges,
                "dietary": menu.show_dietary,
                "variants": menu.show_variants,
                "ingredients": menu.show_ingredients,
                "allergens": menu.show_allergens,
            },
            "currency": {
                "code": currency.name if currency else "SAR",
                "symbol": currency.symbol if currency else "SAR",
                "position": currency.position if currency else "after",
                "decimal_places": currency.decimal_places if currency else 2,
            },
            "categories": category_payload,
            "products": products,
            "offers": offers,
        }
