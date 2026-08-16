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
        # A rule with no company_id is a deliberate "applies everywhere"
        # rule, not an isolation gap - confirms the fix doesn't
        # overcorrect into blocking legitimate global rules.
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
        request with a *missing* pos_config instead of rejecting it."""
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
