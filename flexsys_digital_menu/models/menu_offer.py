import hashlib
import uuid
from datetime import datetime

import pytz

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class FlexSysMenuOffer(models.Model):
    _name = "flexsys.menu.offer"
    _description = "FlexSys Digital Menu Offer"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True, string="Offer Title")
    subtitle = fields.Char(translate=True)
    description = fields.Text(translate=True)
    sequence = fields.Integer(default=10)
    is_published = fields.Boolean(default=True, string="Published")
    image = fields.Image(max_width=1800, max_height=1200)

    menu_id = fields.Many2one("flexsys.menu", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="menu_id.company_id", store=True, readonly=True, index=True)
    product_ids = fields.Many2many(
        "product.template",
        "flexsys_menu_offer_product_rel",
        "offer_id",
        "product_tmpl_id",
        string="Products",
        domain="[('sale_ok', '=', True)]",
    )
    pricelist_id = fields.Many2one(
        "product.pricelist",
        string="Offer Pricelist",
        check_company=True,
        help="Optional Odoo pricelist used for the offer price. No separate pricing engine is created.",
    )
    start_date = fields.Date()
    end_date = fields.Date()
    schedule_ids = fields.Many2many(
        "flexsys.menu.schedule",
        "flexsys_menu_offer_schedule_rel",
        "offer_id",
        "schedule_id",
        string="Schedules",
    )
    public_key = fields.Char(default=lambda self: uuid.uuid4().hex[:16], required=True, copy=False, index=True)

    _sql_constraints = [
        ("public_key_unique", "unique(public_key)", "Offer public key must be unique."),
    ]

    @api.constrains("start_date", "end_date")
    def _check_dates(self):
        for offer in self:
            if offer.start_date and offer.end_date and offer.start_date > offer.end_date:
                raise ValidationError("Offer start date cannot be after end date.")

    @api.constrains("menu_id", "pricelist_id", "schedule_ids")
    def _check_company_consistency(self):
        for offer in self:
            if offer.pricelist_id and offer.pricelist_id.company_id and offer.pricelist_id.company_id != offer.company_id:
                raise ValidationError("The offer pricelist must belong to the menu company or be shared.")
            if offer.pricelist_id and offer.menu_id.currency_id and offer.pricelist_id.currency_id != offer.menu_id.currency_id:
                raise ValidationError("The offer pricelist currency must match the menu currency.")
            if any(schedule.company_id and schedule.company_id != offer.company_id for schedule in offer.schedule_ids):
                raise ValidationError("Offer schedules must belong to the menu company or be shared.")

    def is_active_now(self, preview=False):
        self.ensure_one()
        if not self.is_published and not preview:
            return False
        tz = pytz.timezone(self.menu_id.timezone or "UTC")
        today = datetime.now(tz).date()
        if self.start_date and today < self.start_date:
            return False
        if self.end_date and today > self.end_date:
            return False
        if self.schedule_ids and not any(schedule.is_active_at(tz_name=self.menu_id.timezone) for schedule in self.schedule_ids):
            return False
        return True

    def public_price(self):
        """Return an Odoo-native offer price only when one linked product makes it unambiguous."""
        self.ensure_one()
        if not self.pricelist_id or len(self.product_ids) != 1:
            return None
        product = self.product_ids[:1]
        prices = []
        for variant in product.product_variant_ids:
            prices.append(self.pricelist_id._get_product_price(variant, 1.0))
        return min(prices) if prices else self.pricelist_id._get_product_price(product.product_variant_id, 1.0)

    def public_key_for_product(self, product_tmpl):
        self.ensure_one()
        line = self.env["flexsys.menu.product"].sudo().search([
            ("menu_id", "=", self.menu_id.id),
            ("product_tmpl_id", "=", product_tmpl.id),
            ("pos_config_id", "=", False),
        ], limit=1)
        return line.public_key if line else ""
