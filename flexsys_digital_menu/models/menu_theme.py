import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError


HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class FlexSysMenuTheme(models.Model):
    _name = "flexsys.menu.theme"
    _description = "FlexSys Digital Menu Theme"
    _order = "name"

    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", index=True)
    mode = fields.Selection(
        [("auto", "Auto Brand"), ("custom", "Custom Brand")],
        default="auto",
        required=True,
    )
    style = fields.Selection(
        [
            ("modern", "Modern"),
            ("elegant", "Elegant"),
            ("minimal", "Minimal"),
            ("warm", "Warm"),
            ("dark", "Dark"),
        ],
        default="modern",
        required=True,
    )

    primary = fields.Char(default="#173F35", required=True)
    primary_light = fields.Char(default="#EAF1EE", required=True)
    primary_dark = fields.Char(default="#102D26", required=True)
    secondary = fields.Char(default="#365C50", required=True)
    accent = fields.Char(default="#C9A762", required=True)
    background = fields.Char(default="#F6F7F4", required=True)
    surface = fields.Char(default="#FFFFFF", required=True)
    slab = fields.Char(default="#EDF3F0", required=True)
    border = fields.Char(default="#D8E2DD", required=True)
    text = fields.Char(default="#17201D", required=True)
    text_muted = fields.Char(default="#67716D", required=True)
    button_background = fields.Char(default="#173F35", required=True)
    button_text = fields.Char(default="#FFFFFF", required=True)
    selected = fields.Char(default="#173F35", required=True)
    badge_background = fields.Char(default="#C9A762", required=True)
    badge_text = fields.Char(default="#17201D", required=True)

    radius_sm = fields.Integer(default=10)
    radius_md = fields.Integer(default=16)
    radius_lg = fields.Integer(default=24)
    shadow_sm = fields.Char(default="0 4px 14px rgba(0,0,0,.06)")
    shadow_md = fields.Char(default="0 14px 34px rgba(0,0,0,.10)")

    @api.constrains(
        "primary", "primary_light", "primary_dark", "secondary", "accent",
        "background", "surface", "slab", "border", "text", "text_muted",
        "button_background", "button_text", "selected", "badge_background", "badge_text",
    )
    def _check_colors(self):
        color_fields = [
            "primary", "primary_light", "primary_dark", "secondary", "accent",
            "background", "surface", "slab", "border", "text", "text_muted",
            "button_background", "button_text", "selected", "badge_background", "badge_text",
        ]
        for record in self:
            for field_name in color_fields:
                value = record[field_name]
                if value and not HEX_RE.match(value):
                    raise ValidationError("Theme colors must use #RRGGBB format.")

    def css_variables(self):
        self.ensure_one()
        values = {
            "--menu-primary": self.primary,
            "--menu-primary-light": self.primary_light,
            "--menu-primary-dark": self.primary_dark,
            "--menu-secondary": self.secondary,
            "--menu-accent": self.accent,
            "--menu-bg": self.background,
            "--menu-surface": self.surface,
            "--menu-slab": self.slab,
            "--menu-border": self.border,
            "--menu-text": self.text,
            "--menu-text-muted": self.text_muted,
            "--menu-button-bg": self.button_background,
            "--menu-button-text": self.button_text,
            "--menu-selected": self.selected,
            "--menu-badge-bg": self.badge_background,
            "--menu-badge-text": self.badge_text,
            "--menu-radius-sm": f"{self.radius_sm}px",
            "--menu-radius-md": f"{self.radius_md}px",
            "--menu-radius-lg": f"{self.radius_lg}px",
            "--menu-shadow-sm": self.shadow_sm,
            "--menu-shadow-md": self.shadow_md,
        }
        return ";".join(f"{key}:{value}" for key, value in values.items())
