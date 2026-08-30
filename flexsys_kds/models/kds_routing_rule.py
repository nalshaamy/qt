# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


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
    # UX CLARIFICATION ("Station / Routing UX Clarification"), item 2:
    # "POS" -> "POS Filter (Optional)" - a routing rule's own POS
    # value is NOT a permission grant the way a station's own Allowed
    # POS is (see kds_station.py); it is only an additional, optional
    # match condition on top of whatever the destination station
    # already allows. Purely a string/help change - the field's own
    # name, type, and matching behavior (route_product()/_matches()
    # below) are completely unchanged; empty still means "applies to
    # all POS configurations already allowed by the destination
    # station," exactly as before.
    pos_config_ids = fields.Many2many(
        'pos.config', string='POS Filter (Optional)',
        help="Optional. Leave empty to apply this rule to any POS "
             "already allowed by the destination station.")

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

    # UX CLARIFICATION ("Station / Routing UX Clarification"), item 4:
    # a plain related field, read-only by construction (related fields
    # are read-only unless explicitly declared otherwise) - purely
    # informational, shown next to Destination Station so an
    # administrator can see at a glance which POS the selected
    # station already allows, without needing to open the station
    # record itself. Never writes back to the station, never seeds a
    # default value into pos_config_ids above - informational only,
    # exactly as specified.
    #
    # V69 FIX ("Fresh Repository Validation - Duplicate Field Label
    # Warning"): confirmed - this field shared the exact same
    # string='Allowed POS' as station_pos_config_display below (the
    # field genuinely shown in the view), which Odoo's own field-
    # loading flagged as a duplicate label warning on a fresh install.
    # Confirmed by direct search: this field is not actually read by
    # any view, any compute (_compute_pos_filter_domain_ids and
    # _compute_station_pos_config_display below both read
    # station_id.pos_config_ids directly, never this related field),
    # or any other logic anywhere in this module - reported here
    # rather than silently removed, per explicit direction, since a
    # future need or an as-yet-unseen external reference cannot be
    # ruled out with full certainty from static inspection alone. No
    # invisible=True kwarg is used here - that is a view-level
    # attribute, not a valid fields.Field() constructor argument; this
    # field is already never added to any view's own arch, which is
    # what actually keeps it out of the UI. Only the label itself is
    # changed, to a distinct, clearly-technical string - the field's
    # own name, type, and relation are completely unchanged.
    station_pos_config_ids = fields.Many2many(
        'pos.config', related='station_id.pos_config_ids',
        string='Station Allowed POS (Technical)',
        help="Internal/technical - the routing-rule form itself "
             "displays station_pos_config_display instead. The POS "
             "systems the selected destination station itself already "
             "allows; empty means the station allows all POS.")

    # V68 REVIEW ("Allowed POS Display When Station Allows All"):
    # confirmed gap - station_pos_config_ids above is an empty
    # Many2many when the station allows all POS, which the
    # many2many_tags widget then renders as visually blank in the
    # form - ambiguous, easily misread as "no POS allowed at all"
    # rather than its actual, opposite meaning. This plain Char
    # computed field is shown instead (see the view) specifically to
    # remove that ambiguity: "All POS" when station_pos_config_ids is
    # empty, a comma-joined list of names otherwise. Purely a display
    # convenience - station_pos_config_ids itself, and the station's
    # own actual pos_config_ids field/semantics, are completely
    # unchanged; this never feeds into pos_filter_domain_ids, the
    # contradiction constraint, or any other actual logic below.
    station_pos_config_display = fields.Char(
        compute='_compute_station_pos_config_display', string='Allowed POS')

    @api.depends('station_id', 'station_id.pos_config_ids')
    def _compute_station_pos_config_display(self):
        for rule in self:
            allowed = rule.station_id.pos_config_ids
            rule.station_pos_config_display = (
                ', '.join(allowed.mapped('name')) if allowed else _("All POS")
            )

    # UX CLARIFICATION, item 5 (contradictory-configuration
    # prevention): this is the UI-domain half of the fix - a
    # non-stored compute so it recalculates live in the form whenever
    # station_id changes, without needing an extra round-trip or
    # onchange wiring of its own. When the destination station itself
    # restricts to a specific set of POS, this becomes exactly that
    # set, so pos_config_ids' own dropdown can only ever offer
    # already-allowed choices. When the station allows all POS
    # (station_pos_config_ids is empty), this deliberately becomes
    # every existing pos.config instead of an empty set - an empty
    # domain list would otherwise make the dropdown appear to offer
    # nothing at all, which is the opposite of "station allows all."
    # This is the PREFERRED UX per the explicit request ("قائمة POS
    # Filter تعرض فقط POS Configs المسموح بها"), but is deliberately
    # NOT the only enforcement - see _check_pos_filter_matches_station
    # below for the real, unbypassable backend validation, since a UI
    # domain alone can be bypassed (an existing record loaded via
    # write(), an API call, developer mode, an already-selected value
    # before the station was changed, etc.).
    pos_filter_domain_ids = fields.Many2many(
        'pos.config', compute='_compute_pos_filter_domain_ids',
        help="Internal - used only to scope the POS Filter field's own "
             "dropdown to what the destination station actually allows.")

    # UX CLARIFICATION, item 8 (optional rule summary) - a small,
    # read-only, best-effort plain-language restatement of this rule's
    # own current configuration. Deliberately simple string
    # concatenation over the rule's own already-loaded fields, not a
    # new parser or rule-engine of any kind, per the explicit "لا
    # تدخل في parser أو rule engine جديد" direction - this has no
    # bearing whatsoever on actual routing evaluation
    # (_matches()/route_product() below are completely independent of
    # this field and never read it).
    rule_summary = fields.Char(compute='_compute_rule_summary', string='Rule Summary')

    @api.depends('station_id', 'station_id.pos_config_ids')
    def _compute_pos_filter_domain_ids(self):
        all_pos_configs = self.env['pos.config'].search([])
        for rule in self:
            allowed = rule.station_id.pos_config_ids
            rule.pos_filter_domain_ids = allowed if allowed else all_pos_configs

    @api.depends(
        'pos_categ_ids', 'order_type_ids', 'pos_config_ids', 'station_id',
        'product_ids', 'product_categ_ids')
    def _compute_rule_summary(self):
        """V68 REVIEW ("Complete Arabic Translation"): confirmed gap -
        the fixed English words this sentence is built from ("orders",
        "Orders", "POS", "any allowed POS") used to be plain Python
        string literals concatenated directly, never passed through
        _() individually - so an Arabic UI would show a mostly-Arabic
        sentence (the surrounding "Send ... from ... to ..." template
        below is translated) with stray hardcoded English words stuck
        in the middle of it. Every fixed fragment is now its own
        separate, independently translatable _() call - proper names
        (product/category/POS/station names the user themselves
        configured) are never passed through _() and correctly stay
        exactly as configured, in whatever language they were entered
        in, per the explicit requirement that only fixed phrases need
        translation, not user data."""
        for rule in self:
            if not rule.station_id:
                rule.rule_summary = False
                continue
            if rule.pos_categ_ids:
                subject = _("%(names)s orders") % {
                    'names': ' / '.join(rule.pos_categ_ids.mapped('name'))}
            elif rule.product_ids:
                subject = _("%(names)s orders") % {
                    'names': ' / '.join(rule.product_ids.mapped('name'))}
            elif rule.product_categ_ids:
                subject = _("%(names)s orders") % {
                    'names': ' / '.join(rule.product_categ_ids.mapped('name'))}
            else:
                subject = _("Orders")
            pos_part = (
                _("%(names)s POS") % {'names': ' / '.join(rule.pos_config_ids.mapped('name'))}
                if rule.pos_config_ids else _("any allowed POS")
            )
            rule.rule_summary = _(
                "Send %(subject)s from %(pos_part)s to %(station)s."
            ) % {'subject': subject, 'pos_part': pos_part, 'station': rule.station_id.name}

    @api.constrains('pos_config_ids', 'station_id')
    def _check_pos_filter_matches_station(self):
        """UX CLARIFICATION, item 5 - the real, unbypassable half of
        the contradictory-configuration fix (the UI domain above is a
        convenience, not a security/correctness boundary on its own).
        A routing rule's own POS Filter must never name a POS the
        destination station itself doesn't already allow - it is only
        ever an additional filter on top of the station's own
        permission, never a way to widen it. An empty station
        pos_config_ids means the station allows all POS, so there is
        nothing to reject in that case regardless of what the rule's
        own filter contains."""
        for rule in self:
            if not rule.pos_config_ids or not rule.station_id:
                continue
            station_allowed = rule.station_id.pos_config_ids
            if not station_allowed:
                continue
            disallowed = rule.pos_config_ids - station_allowed
            if disallowed:
                raise ValidationError(_(
                    "%(pos_names)s is not allowed by the selected destination station."
                ) % {'pos_names': ', '.join(disallowed.mapped('name'))})

    @api.onchange('pos_config_ids', 'station_id')
    def _onchange_pos_filter_redundant_warning(self):
        """UX CLARIFICATION, item 6: functionally valid but redundant
        configuration (the rule's own POS Filter names exactly what
        the station already allows, in full) - a soft, non-blocking
        warning only, never a ValidationError, per the explicit "لا
        تمنع الحفظ" direction. Deliberately checks for an EXACT match
        (rule.pos_config_ids == station_allowed), not merely overlap -
        a rule that further narrows down a multi-POS station's own
        allowed set (e.g. station allows A+B, rule filters to just A)
        is a genuinely meaningful filter, not a redundant restatement,
        and must not be warned about here."""
        if not self.pos_config_ids or not self.station_id:
            return
        station_allowed = self.station_id.pos_config_ids
        if station_allowed and set(self.pos_config_ids.ids) == set(station_allowed.ids):
            return {'warning': {
                'title': _("Redundant POS Filter"),
                'message': _(
                    "This POS filter is redundant because the destination "
                    "station already accepts only %(pos_names)s."
                ) % {'pos_names': ', '.join(station_allowed.mapped('name'))},
            }}

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
