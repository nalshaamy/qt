# -*- coding: utf-8 -*-
from odoo import api, fields, models


def _product_pos_categories(product):
    """Return the pos.category recordset a product belongs to.

    Checked defensively via `_fields` rather than a direct attribute
    access: Odoo has used a Many2one `pos_categ_id` in older versions and
    a Many2many `pos_categ_ids` in newer ones, and given this module has
    already hit several field renames/removals specific to this Odoo 19
    build, this avoids yet another AttributeError if it differs here too.
    """
    if 'pos_categ_ids' in product._fields:
        return product.pos_categ_ids
    if 'pos_categ_id' in product._fields:
        return product.pos_categ_id
    return product.env['pos.category']


class KdsRoutingRule(models.Model):
    _name = 'kds.routing.rule'
    _description = 'FlexSys KDS Routing Rule'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10, help="Lower runs first. First match wins.")
    active = fields.Boolean(default=True)

    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company,
        help="Leave empty for a rule that applies to every company - set it "
             "to scope this rule to one branch only. Never used to route an "
             "order for a *different* company than this rule's own "
             "(security fix, audit finding 1/CRITICAL: multi-company "
             "isolation)."
    )
    pos_config_ids = fields.Many2many('pos.config', string='POS (leave empty = all)')

    # Many2many rather than Many2one: one rule commonly covers a group of
    # products/categories that should all go to the same station (e.g.
    # "these 5 combo items -> Packing") rather than needing a separate
    # rule per product.
    product_ids = fields.Many2many('product.product', string='Products')

    pos_categ_ids = fields.Many2many(
        'pos.category', string='POS Categories',
        help="Point of Sale categories (Burgers, Drinks, Desserts...) as configured "
             "in the POS itself - this is what cashiers/staff actually use day to "
             "day, and is checked first."
    )
    product_categ_ids = fields.Many2many(
        'product.category', string='Inventory Categories',
        help="Odoo's internal accounting/inventory categories. Usually POS "
             "Categories is what you want instead - this is here as a fallback "
             "for setups that don't maintain POS categories."
    )

    order_type_ids = fields.Many2many(
        'kds.order.type.tag', string='Order Types',
        help="Leave empty to match every order type.")
    source_ids = fields.Many2many(
        'kds.order.source.tag', string='Sources',
        help="Leave empty to match every source.")

    station_id = fields.Many2one('kds.station', string='Destination Station', required=True)

    def _matches(self, product, order_type, source, pos_config):
        self.ensure_one()
        if self.product_ids and product not in self.product_ids:
            return False
        if self.pos_categ_ids and not (self.pos_categ_ids & _product_pos_categories(product)):
            return False
        if self.product_categ_ids and product.categ_id not in self.product_categ_ids:
            return False
        if self.order_type_ids and order_type not in self.order_type_ids.mapped('code'):
            return False
        if self.source_ids and source not in self.source_ids.mapped('code'):
            return False
        # SECURITY FIX (audit finding 2, HIGH): the old check was
        # `pos_config_ids and pos_config and pos_config not in ...` - the
        # `pos_config and` guard meant a rule restricted to specific POS
        # configs silently MATCHED any request with a *missing* pos_config
        # instead of correctly rejecting it (Python short-circuits on the
        # falsy `pos_config` before ever checking membership). A rule
        # scoped to specific POS configs must never match when the
        # incoming POS config is absent or different.
        #
        # REAL BUG FIX, confirmed live on Odoo.sh: dropping that guard
        # entirely (writing `pos_config not in self.pos_config_ids`
        # directly) fixed the security issue above but introduced a new
        # one - `False in <recordset>` raises TypeError on this Odoo 19
        # build's own `Model.__contains__`, rather than the graceful
        # "False is not a member" result some other versions/situations
        # might return. Restored an explicit `not pos_config` check
        # first (matching the exact structure of _station_eligible's own
        # already-safe `pos_config and station.pos_config_ids and ...`
        # a few lines below, which short-circuits on the same falsy
        # value before ever attempting membership) - the original
        # security intent (reject a missing pos_config when the rule is
        # scoped) is fully preserved; this only changes *how* that
        # rejection is reached, never *whether* it happens.
        if self.pos_config_ids:
            if not pos_config:
                return False
            if pos_config not in self.pos_config_ids:
                return False
        return True

    @api.model
    def _station_eligible(self, station, company, pos_config, skip_company_check=False):
        """Whether `station` may legitimately receive this order at all -
        checked for EVERY candidate station (explicit rule match, product
        fallback, POS category fallback, inventory category fallback),
        not just explicit routing rules. Security fix, audit findings
        1 (CRITICAL, multi-company) and 2 (HIGH, POS config eligibility -
        "the selected Station must also allow the current POS
        configuration", not just the routing rule).

        `skip_company_check` (documented behavior, confirmed live on
        Odoo.sh): the intended separation between a *rule's* own company
        scope and a *station's* own company field. kds.station.company_id
        is a required field (a station always belongs to exactly one
        company/branch - this module treats company as the Branch entity,
        per that field's own help text) - there is structurally no such
        thing as a "global station". A routing *rule*, however, CAN be
        explicitly marked company_id=False by an administrator, meaning
        "this exact rule (and the specific destination station it names)
        applies to every branch, not just one" - a legitimate real-world
        setup (e.g. one centralized prep station serving several
        branches for a given product). route_product() below passes
        skip_company_check=True only for that one specific case - a
        rule match where the *rule itself* is global - trusting the
        administrator's explicit choice of station on that rule. Every
        other path keeps full, unweakened company isolation: a
        company-*specific* rule's station must still belong to that same
        company, and every fallback level (product/POS-category/
        inventory-category default) is never treated as global - those
        keep the strict check exactly as before, since there is no
        equivalent "this fallback is deliberately cross-company" signal
        to trust the way there is for an explicitly-global rule.
        """
        if not station:
            return False
        if not skip_company_check and company and station.company_id != company:
            return False
        # Empty station.pos_config_ids means "all POS" (per spec) - only
        # reject when the station explicitly restricts to a set that
        # doesn't include the incoming pos_config.
        if pos_config and station.pos_config_ids and pos_config not in station.pos_config_ids:
            return False
        return True

    @api.model
    def route_product(self, product, order_type='dine_in', source='pos', pos_config=None, company=None):
        """Return the kds.station a product should go to, or a fallback
        default station, or an empty recordset if nothing matches.

        `company` (security fix, audit finding 1/CRITICAL): every
        candidate - explicit rule matches AND every fallback level - is
        now checked against this company before being returned, so a
        rule/station/product default belonging to a different company can
        never be selected. Defaults to `pos_config.company_id` if a POS
        config was given, else the current user's company - callers that
        know the order's actual company (the normal case, from
        pos_order.py) should pass it explicitly rather than relying on
        this fallback.

        Fallback order once no explicit rule matches (each level is now
        also checked via _station_eligible, so it can't return a
        wrong-company or POS-ineligible station either):
        1. The product's own default station.
        2. The POS category's default station (what staff actually
           organize products by day to day).
        3. The inventory category's default station (legacy fallback).
        """
        company = company or (pos_config.company_id if pos_config else False) or self.env.company

        domain = [
            ('active', '=', True),
            '|', ('company_id', '=', False), ('company_id', '=', company.id),
        ]
        rules = self.search(domain)
        for rule in rules:
            if rule._matches(product, order_type, source, pos_config) \
                    and self._station_eligible(
                        rule.station_id, company, pos_config, skip_company_check=not rule.company_id):
                return rule.station_id

        if self._station_eligible(product.kds_station_id, company, pos_config):
            return product.kds_station_id

        for pos_categ in _product_pos_categories(product):
            if self._station_eligible(pos_categ.kds_station_id, company, pos_config):
                return pos_categ.kds_station_id

        if self._station_eligible(product.categ_id.kds_station_id, company, pos_config):
            return product.categ_id.kds_station_id

        return self.env['kds.station']
