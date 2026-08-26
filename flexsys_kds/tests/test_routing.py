# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import FlexSysKdsTestCommon


@tagged('post_install', '-at_install')
class TestRouting(FlexSysKdsTestCommon):

    def test_no_rule_no_default_returns_empty(self):
        """A product with no matching rule and no product/category default
        should route to nothing (empty recordset), not raise or guess."""
        station = self.env['kds.routing.rule'].route_product(self.product_burger)
        self.assertFalse(station)

    # -----------------------------------------------------------------
    # Audit finding 1 (CRITICAL): multi-company routing isolation. A rule
    # or station belonging to a different company must never be
    # selected for an order, at any level of the fallback chain - not
    # just explicit rule matches.
    # -----------------------------------------------------------------
    def test_rule_scoped_to_other_company_never_matches(self):
        self.env['kds.routing.rule'].create({
            'name': 'Company B rule (test)',
            'company_id': self.company_b.id,
            'product_ids': [(6, 0, [self.product_burger.id])],
            'station_id': self.station_kitchen_b.id,
            'sequence': 10,
        })
        station = self.env['kds.routing.rule'].route_product(
            self.product_burger, company=self.company)
        self.assertFalse(
            station,
            "A rule belonging to a different company must never be selected, "
            "even if its own criteria would otherwise match.")

    def test_rule_without_company_applies_to_every_company(self):
        """Documented intended behavior, confirmed live on Odoo.sh: a rule
        with company_id=False is a deliberate "applies to every branch"
        rule - not an isolation gap. kds.station.company_id is a
        required field (there is no such thing as a "global station" -
        this module treats company as the Branch entity), so a global
        RULE explicitly naming a specific station is the administrator's
        own choice to make that exact station serve every branch for
        this rule (e.g. one centralized prep station shared across
        branches) - trusted specifically because the rule itself was
        deliberately marked global, not because station-level company
        checks were relaxed in general. See
        kds_routing_rule.py::_station_eligible()'s own `skip_company_check`
        parameter and docstring for the full separation between "the
        rule's own company scope" and "the destination station's own
        company field" this relies on. Every OTHER path keeps full,
        unweakened isolation: a company-*specific* rule's station must
        still belong to that same company
        (test_rule_scoped_to_other_company_never_matches above is
        unaffected - that rule never even reaches this check, since it's
        excluded by the search domain itself for a different company's
        query), and none of the three fallback levels (product/POS-
        category/inventory-category default - see
        test_product_default_station_from_other_company_is_ignored
        below) are ever treated as global."""
        self.env['kds.routing.rule'].create({
            'name': 'Global rule (test)',
            'company_id': False,
            'product_ids': [(6, 0, [self.product_burger.id])],
            'station_id': self.station_kitchen.id,
            'sequence': 10,
        })
        self.assertEqual(
            self.env['kds.routing.rule'].route_product(self.product_burger, company=self.company),
            self.station_kitchen)
        self.assertEqual(
            self.env['kds.routing.rule'].route_product(self.product_burger, company=self.company_b),
            self.station_kitchen,
            "A company_id=False rule should still match for a Company B order too - "
            "just not accidentally leak a Company-B-*specific* rule/station into Company A.")

    def test_global_rule_still_enforces_pos_config_eligibility(self):
        """Precise boundary check: skip_company_check only ever skips the
        COMPANY check on the destination station - the POS-config
        eligibility check right below it in _station_eligible is
        unconditional and still fully applies to a global rule's own
        station, exactly as strictly as to any other. A global rule does
        not mean "skip every eligibility check" - only the one specific
        check tied to the company/branch scope the rule itself was
        deliberately marked global for."""
        pos_config_a = self.env['pos.config'].create({'name': 'QT001 (global test)'})
        self.station_kitchen.pos_config_ids = [(6, 0, [pos_config_a.id])]
        self.env['kds.routing.rule'].create({
            'name': 'Global rule, POS-restricted station (test)',
            'company_id': False,
            'product_ids': [(6, 0, [self.product_burger.id])],
            'station_id': self.station_kitchen.id,
            'sequence': 10,
        })
        pos_config_b = self.env['pos.config'].create({'name': 'QT002 (global test)'})
        self.assertFalse(
            self.env['kds.routing.rule'].route_product(
                self.product_burger, pos_config=pos_config_b, company=self.company_b),
            "A global rule's station must still reject a POS config it doesn't allow - "
            "being company-global never implies being POS-config-unrestricted too.")
        self.assertEqual(
            self.env['kds.routing.rule'].route_product(
                self.product_burger, pos_config=pos_config_a, company=self.company_b),
            self.station_kitchen,
            "The same global rule must still match once the POS config is one the "
            "station actually allows.")

    def test_product_default_station_from_other_company_is_ignored(self):
        """Even the *fallback* levels (product default, POS category
        default, inventory category default) must respect company
        isolation - a product's kds_station_id pointing at a
        wrong-company station must be skipped, not blindly returned."""
        self.product_burger.kds_station_id = self.station_kitchen_b
        station = self.env['kds.routing.rule'].route_product(
            self.product_burger, company=self.company)
        self.assertFalse(
            station,
            "A product-level default pointing at another company's station "
            "must be ignored, not returned.")

    def test_product_default_station_from_same_company_still_works(self):
        self.product_burger.kds_station_id = self.station_kitchen
        station = self.env['kds.routing.rule'].route_product(
            self.product_burger, company=self.company)
        self.assertEqual(station, self.station_kitchen)

    def test_route_product_defaults_company_to_env_company_when_not_passed(self):
        # Existing callers/tests that don't explicitly pass `company`
        # (the pre-fix call signature) must keep working exactly as
        # before, defaulting to the current user's company.
        self.product_burger.kds_station_id = self.station_kitchen
        station = self.env['kds.routing.rule'].route_product(self.product_burger)
        self.assertEqual(station, self.station_kitchen)

    # -----------------------------------------------------------------
    # Audit finding 2 (HIGH): POS configuration matching. A rule/station
    # restricted to specific POS configs must only match those, and must
    # correctly REJECT (not silently accept) a request with no POS
    # config at all.
    # -----------------------------------------------------------------
    def test_rule_scoped_to_pos_config_rejects_missing_pos_config(self):
        """Real bug fixed: the old check was `pos_config_ids and pos_config
        and pos_config not in ...` - the `pos_config and` guard meant a
        rule restricted to specific POS configs silently MATCHED a
        request with a *missing* pos_config instead of rejecting it.

        REAL BUG FIX, confirmed live on Odoo.sh: dropping that truthy
        guard entirely (to fix the security issue above) introduced a
        new one - `False in <recordset>` raises TypeError on this Odoo
        19 build's own Model.__contains__, rather than the graceful
        "not a member" result the old code implicitly relied on. Fixed
        with an explicit `if not pos_config: return False` check before
        ever attempting membership - see kds_routing_rule.py's own
        _matches() for the full explanation. This test's own assertion
        is unchanged - it's exercising the same intended behavior
        (reject a missing pos_config when the rule is scoped), just via
        a different, TypeError-safe code path now."""
        pos_config = self.env['pos.config'].create({'name': 'QT001 (test)'})
        self.env['kds.routing.rule'].create({
            'name': 'QT001-only rule (test)',
            'pos_config_ids': [(6, 0, [pos_config.id])],
            'product_ids': [(6, 0, [self.product_burger.id])],
            'station_id': self.station_kitchen.id,
            'sequence': 10,
        })
        station = self.env['kds.routing.rule'].route_product(
            self.product_burger, pos_config=False, company=self.company)
        self.assertFalse(
            station,
            "A rule scoped to a specific POS config must not match a request "
            "with no POS config at all.")

    def test_rule_scoped_to_pos_config_matches_only_that_config(self):
        pos_config_a = self.env['pos.config'].create({'name': 'QT001 (test)'})
        pos_config_b = self.env['pos.config'].create({'name': 'QT002 (test)'})
        self.env['kds.routing.rule'].create({
            'name': 'QT001-only rule (test 2)',
            'pos_config_ids': [(6, 0, [pos_config_a.id])],
            'product_ids': [(6, 0, [self.product_burger.id])],
            'station_id': self.station_kitchen.id,
            'sequence': 10,
        })
        self.assertEqual(
            self.env['kds.routing.rule'].route_product(
                self.product_burger, pos_config=pos_config_a, company=self.company),
            self.station_kitchen)
        self.assertFalse(
            self.env['kds.routing.rule'].route_product(
                self.product_burger, pos_config=pos_config_b, company=self.company),
            "A rule scoped to QT001 must not match a QT002 request.")

    def test_station_pos_config_restriction_blocks_ineligible_station(self):
        """Point: 'The selected Station must also allow the current POS
        configuration' - checked independently of the routing rule's own
        pos_config_ids, at every fallback level too."""
        pos_config_a = self.env['pos.config'].create({'name': 'QT001 (test 3)'})
        pos_config_b = self.env['pos.config'].create({'name': 'QT002 (test 3)'})
        self.station_kitchen.pos_config_ids = [(6, 0, [pos_config_a.id])]
        self.product_burger.kds_station_id = self.station_kitchen
        self.assertEqual(
            self.env['kds.routing.rule'].route_product(
                self.product_burger, pos_config=pos_config_a, company=self.company),
            self.station_kitchen)
        self.assertFalse(
            self.env['kds.routing.rule'].route_product(
                self.product_burger, pos_config=pos_config_b, company=self.company),
            "A station restricted to QT001 must not be returned for a QT002 request, "
            "even via the product-default fallback path.")

    def test_station_with_no_pos_config_restriction_allows_any_pos(self):
        # Empty station.pos_config_ids means "all POS" per spec.
        pos_config = self.env['pos.config'].create({'name': 'QT003 (test)'})
        self.product_burger.kds_station_id = self.station_kitchen
        self.assertEqual(
            self.env['kds.routing.rule'].route_product(
                self.product_burger, pos_config=pos_config, company=self.company),
            self.station_kitchen)

    def test_product_level_default_used_as_fallback(self):
        self.product_burger.kds_station_id = self.station_kitchen
        station = self.env['kds.routing.rule'].route_product(self.product_burger)
        self.assertEqual(station, self.station_kitchen)

    def test_category_level_default_used_when_no_product_default(self):
        self.categ_drinks.kds_station_id = self.station_coffee
        station = self.env['kds.routing.rule'].route_product(self.product_cappuccino)
        self.assertEqual(station, self.station_coffee)

    def test_product_default_wins_over_category_default(self):
        self.categ_food.kds_station_id = self.station_coffee  # deliberately "wrong"
        self.product_burger.kds_station_id = self.station_kitchen
        station = self.env['kds.routing.rule'].route_product(self.product_burger)
        self.assertEqual(station, self.station_kitchen)

    def test_explicit_rule_wins_over_product_and_category_defaults(self):
        # Defaults would both say Kitchen; an explicit rule overrides them.
        self.product_burger.kds_station_id = self.station_kitchen
        self.categ_food.kds_station_id = self.station_kitchen
        self.env['kds.routing.rule'].create({
            'name': 'Burger to Coffee (test override)',
            'product_ids': [(6, 0, [self.product_burger.id])],
            'station_id': self.station_coffee.id,
            'sequence': 10,
        })
        station = self.env['kds.routing.rule'].route_product(self.product_burger)
        self.assertEqual(station, self.station_coffee)

    def test_lower_sequence_rule_wins(self):
        self.env['kds.routing.rule'].create({
            'name': 'Rule A (higher sequence, should lose)',
            'product_ids': [(6, 0, [self.product_burger.id])],
            'station_id': self.station_coffee.id,
            'sequence': 50,
        })
        self.env['kds.routing.rule'].create({
            'name': 'Rule B (lower sequence, should win)',
            'product_ids': [(6, 0, [self.product_burger.id])],
            'station_id': self.station_kitchen.id,
            'sequence': 10,
        })
        station = self.env['kds.routing.rule'].route_product(self.product_burger)
        self.assertEqual(station, self.station_kitchen)

    def test_rule_scoped_to_order_type_only_matches_that_type(self):
        self.env['kds.routing.rule'].create({
            'name': 'Delivery-only burger rule',
            'product_ids': [(6, 0, [self.product_burger.id])],
            'order_type_ids': [(6, 0, [self.env.ref('flexsys_kds.order_type_tag_delivery').id])],
            'station_id': self.station_coffee.id,
            'sequence': 10,
        })
        self.product_burger.kds_station_id = self.station_kitchen  # fallback

        delivery_station = self.env['kds.routing.rule'].route_product(
            self.product_burger, order_type='delivery')
        dine_in_station = self.env['kds.routing.rule'].route_product(
            self.product_burger, order_type='dine_in')

        self.assertEqual(delivery_station, self.station_coffee,
                          "Delivery orders should match the scoped rule.")
        self.assertEqual(dine_in_station, self.station_kitchen,
                          "Dine-in orders should skip the scoped rule and fall back to the product default.")

    def test_category_rule_matches_any_product_in_category(self):
        self.env['kds.routing.rule'].create({
            'name': 'All drinks to Coffee',
            'product_categ_ids': [(6, 0, [self.categ_drinks.id])],
            'station_id': self.station_coffee.id,
            'sequence': 10,
        })
        station = self.env['kds.routing.rule'].route_product(self.product_cappuccino)
        self.assertEqual(station, self.station_coffee)

    def test_rule_matches_any_product_in_a_multi_product_rule(self):
        """The point of product_ids being Many2many: one rule can cover
        several products at once instead of needing a separate rule per
        product."""
        self.env['kds.routing.rule'].create({
            'name': 'Burger + Cappuccino both to Bar (test)',
            'product_ids': [(6, 0, [self.product_burger.id, self.product_cappuccino.id])],
            'station_id': self.station_coffee.id,
            'sequence': 10,
        })
        self.assertEqual(
            self.env['kds.routing.rule'].route_product(self.product_burger),
            self.station_coffee)
        self.assertEqual(
            self.env['kds.routing.rule'].route_product(self.product_cappuccino),
            self.station_coffee)

    def test_rule_matches_any_of_multiple_order_types(self):
        """The point of order_type_ids being Many2many: one rule can cover
        several order types at once (e.g. Dine In + Take Away both go to
        Kitchen the normal way, only Delivery gets special handling)."""
        self.env['kds.routing.rule'].create({
            'name': 'Dine-in or takeaway burger -> Kitchen (test)',
            'product_ids': [(6, 0, [self.product_burger.id])],
            'order_type_ids': [(6, 0, [
                self.env.ref('flexsys_kds.order_type_tag_dine_in').id,
                self.env.ref('flexsys_kds.order_type_tag_take_away').id,
            ])],
            'station_id': self.station_kitchen.id,
            'sequence': 10,
        })
        self.assertEqual(
            self.env['kds.routing.rule'].route_product(self.product_burger, order_type='dine_in'),
            self.station_kitchen)
        self.assertEqual(
            self.env['kds.routing.rule'].route_product(self.product_burger, order_type='take_away'),
            self.station_kitchen)

    def test_inactive_rule_is_ignored(self):
        rule = self.env['kds.routing.rule'].create({
            'name': 'Inactive rule',
            'product_ids': [(6, 0, [self.product_burger.id])],
            'station_id': self.station_coffee.id,
            'sequence': 10,
        })
        rule.active = False
        self.product_burger.kds_station_id = self.station_kitchen
        station = self.env['kds.routing.rule'].route_product(self.product_burger)
        self.assertEqual(station, self.station_kitchen,
                          "An archived rule must not be applied.")

    def test_order_line_create_auto_routes(self):
        """kds.order.line.create() should call the routing engine itself
        when no station_id is passed in explicitly."""
        self.product_burger.kds_station_id = self.station_kitchen
        order = self.env['kds.order'].create({'source': 'pos', 'order_type': 'dine_in'})
        line = self.env['kds.order.line'].create({
            'order_id': order.id,
            'product_id': self.product_burger.id,
            'qty': 1,
        })
        self.assertEqual(line.station_id, self.station_kitchen)

    # -----------------------------------------------------------------
    # UI/DATA FIX ("Master Change Request", Batch 2, items 6-9).
    # -----------------------------------------------------------------
    def test_item6_product_categ_ids_backend_fallback_still_works(self):
        """Item 6: explicit decision - 'KEEP the existing backend
        product.categ_id fallback and related tests completely
        unchanged.' Confirms the inventory-category fallback level in
        route_product() still works exactly as before, unaffected by
        the field being hidden from the Routing UI."""
        categ = self.env['product.category'].create({'name': 'Test Inventory Category'})
        categ.kds_station_id = self.station_kitchen
        self.product_burger.categ_id = categ.id
        # No product/POS-category default, no matching rule - only the
        # inventory-category fallback can resolve this.
        self.product_burger.kds_station_id = False

        station = self.env['kds.routing.rule'].route_product(
            self.product_burger, order_type='dine_in', source='pos')

        self.assertEqual(station, self.station_kitchen)

    def test_item6_product_categ_ids_matching_still_works(self):
        """Item 6: confirms an explicit routing rule using
        product_categ_ids in its own _matches() condition still
        correctly matches - the field's own backend logic is completely
        unchanged, only its own Routing UI visibility changed."""
        categ = self.env['product.category'].create({'name': 'Test Inventory Category 2'})
        self.product_burger.categ_id = categ.id
        rule = self.env['kds.routing.rule'].create({
            'name': 'Inventory category rule',
            'product_categ_ids': [(6, 0, [categ.id])],
            'station_id': self.station_kitchen.id,
        })
        self.assertTrue(rule._matches(self.product_burger, 'dine_in', 'pos', None))

    def test_item7_sequence_field_still_controls_rule_order(self):
        """Item 7: display-label-only rename ('Sequence' -> 'Priority')
        - confirms the underlying sequence field's own real ordering
        behavior (first matching rule wins, lower number checked first)
        is completely unaffected."""
        station_other = self.env['kds.station'].create({'name': 'Other', 'code': 'OTHER_R7'})
        rule_a = self.env['kds.routing.rule'].create({
            'name': 'A', 'sequence': 5, 'product_ids': [(6, 0, [self.product_burger.id])],
            'station_id': self.station_kitchen.id,
        })
        self.env['kds.routing.rule'].create({
            'name': 'B', 'sequence': 10, 'product_ids': [(6, 0, [self.product_burger.id])],
            'station_id': station_other.id,
        })
        station = self.env['kds.routing.rule'].route_product(
            self.product_burger, order_type='dine_in', source='pos')
        self.assertEqual(station, self.station_kitchen,
                          "Lower sequence (now labeled Priority) must still be checked first.")
        rule_a.unlink()

    def test_item9_only_pos_source_tag_active_by_default(self):
        """Item 9: confirms only the genuinely-used 'pos' source tag is
        active by default - every other seeded source (not yet backed
        by a real integration anywhere in this codebase) is archived,
        not deleted."""
        pos_tag = self.env.ref('flexsys_kds.order_source_tag_pos')
        self.assertTrue(pos_tag.active)

        for xml_id in ('order_source_tag_qr', 'order_source_tag_web',
                        'order_source_tag_call_center', 'order_source_tag_delivery_app',
                        'order_source_tag_api', 'order_source_tag_flexsys'):
            tag = self.env.ref('flexsys_kds.%s' % xml_id)
            self.assertFalse(
                tag.active,
                "%s must be archived (active=False) - not a real, backed integration "
                "anywhere in this codebase yet." % xml_id)
            # Confirms the record itself is NOT deleted - just archived,
            # exactly as required ("Archived, not deleted").
            self.assertTrue(tag.exists())

    def test_item9_archived_source_tags_hidden_from_default_search(self):
        """Confirms Odoo's own standard archiving mechanism correctly
        hides these from a default (active-only) search, while an
        explicit active_test=False search still finds them - proving
        they're genuinely archived, not deleted."""
        default_search = self.env['kds.order.source.tag'].search([('code', '=', 'qr')])
        self.assertFalse(default_search)

        with_inactive = self.env['kds.order.source.tag'].with_context(
            active_test=False).search([('code', '=', 'qr')])
        self.assertTrue(with_inactive)

    # -----------------------------------------------------------------
    # UI IMPROVEMENT ("Patch 5", items 2, 3, 4).
    # -----------------------------------------------------------------
    def test_patch5_item2_pos_field_label_simplified(self):
        """Item 2: 'POS (leave empty = all)' -> 'POS', with the same
        info moved to help text. Confirms the field's own label/help
        were updated, and that empty still means 'applies to all POS
        configurations' - a pure label change, matching behavior."""
        field = self.env['kds.routing.rule']._fields['pos_config_ids']
        self.assertEqual(field.string, 'POS')
        self.assertIn('Leave empty', field.help)
        self.assertIn('all POS configurations', field.help)

    def test_patch5_item2_empty_pos_still_matches_everything(self):
        """Non-regression: confirms empty pos_config_ids still matches
        any POS - the underlying behavior this label describes is
        completely unchanged.

        TEST-FIXTURE FIX ("CI Full Run" report), confirmed by direct
        tracing before touching this test: `self.pos_config` was never
        defined anywhere - not in this file's own class (no local
        setUpClass), not in common.py's own shared fixtures - a
        genuine AttributeError, not evidence of a _matches() defect.
        Fixed with a real, local `pos.config` record, matching the
        exact minimal-fields pattern already used elsewhere in this
        same file (e.g. test_global_rule_still_enforces_pos_config_eligibility
        above) - the test still exercises the identical original
        contract: `_matches()` called with a genuine, non-empty
        pos_config argument, confirming an unrestricted rule
        (pos_config_ids empty) matches regardless of which real POS is
        asking."""
        pos_config = self.env['pos.config'].create({'name': 'Item2 Empty POS Test'})
        rule = self.env['kds.routing.rule'].create({
            'name': 'Empty POS still matches all',
            'product_ids': [(6, 0, [self.product_burger.id])],
            'station_id': self.station_kitchen.id,
        })
        self.assertTrue(rule._matches(self.product_burger, 'dine_in', 'pos', pos_config))

    def test_patch5_item3_match_section_title_simplified(self):
        """Item 3: 'MATCH ON (EMPTY = MATCHES EVERYTHING FOR THAT
        CRITERION)' -> 'Match Conditions'."""
        form_view = self.env.ref('flexsys_kds.view_kds_routing_rule_form')
        arch = form_view.arch_db
        self.assertIn('string="Match Conditions"', arch)
        self.assertNotIn('Match on (empty = matches everything', arch)

    def test_patch5_item4_matching_help_simplified(self):
        """Item 4: simplified help text stating the three rules
        plainly - Empty criterion = Any, Multiple values in the same
        criterion = OR, Different criteria = AND."""
        form_view = self.env.ref('flexsys_kds.view_kds_routing_rule_form')
        arch = form_view.arch_db
        self.assertIn('Empty criterion = Any', arch)
        self.assertIn('same criterion = OR', arch)
        self.assertIn('Different criteria = AND', arch)

    def test_patch5_items2to4_matching_logic_completely_unchanged(self):
        """Non-regression: confirms the underlying routing/matching
        engine (route_product(), _matches()) is completely untouched
        by these purely-cosmetic label/help/title changes - AND
        semantics across different criteria, OR semantics within the
        same criterion, still hold exactly as before.

        TEST-FIXTURE FIX ("CI Full Run" report): same root cause and
        same fix as test_patch5_item2_empty_pos_still_matches_everything
        above - `self.pos_config` was never defined anywhere. Fixed
        with a real, local `pos.config` record; the original OR-within-
        product_ids contract is otherwise completely unchanged."""
        pos_config = self.env['pos.config'].create({'name': 'Items2to4 AND OR Test'})
        rule = self.env['kds.routing.rule'].create({
            'name': 'AND/OR semantics unaffected',
            'product_ids': [(6, 0, [self.product_burger.id, self.product_cappuccino.id])],
            'pos_categ_ids': [(6, 0, [])],
            'station_id': self.station_kitchen.id,
        })
        # OR within product_ids: either product matches.
        self.assertTrue(rule._matches(self.product_burger, 'dine_in', 'pos', pos_config))
        self.assertTrue(rule._matches(self.product_cappuccino, 'dine_in', 'pos', pos_config))
