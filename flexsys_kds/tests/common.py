# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase

# NOTE on the test framework import: written against
# `odoo.tests.common.TransactionCase`, which has been the stable location
# for many versions. `odoo.tests.TransactionCase` (re-exported at the
# package level) also works in recent Odoo and is the more commonly used
# shorthand in newer code - if the test runner on your Odoo 19 instance
# complains about this import, that's the first thing to try. I don't have
# a live Odoo 19 checkout to confirm which form is preferred there.


class FlexSysKdsTestCommon(TransactionCase):
    """Shared fixtures for FlexSys KDS tests.

    Deliberately independent of the point_of_sale module's own test
    helpers (see test_pos_sync.py, the one file that does need those) so
    the rest of the suite runs off only this module's own models and isn't
    sensitive to point_of_sale internals shifting between Odoo versions.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

        cls.station_kitchen = cls.env['kds.station'].create({
            'name': 'Test Kitchen', 'code': 'TESTKITCHEN', 'target_prep_time': 10,
        })
        cls.station_coffee = cls.env['kds.station'].create({
            'name': 'Test Coffee', 'code': 'TESTCOFFEE', 'target_prep_time': 4,
        })

        # Second company, for multi-company routing isolation tests
        # (audit finding 1, CRITICAL) - a station that legitimately
        # belongs to a *different* company than everything else in this
        # fixture set, so tests can assert it never gets selected for a
        # Company A order.
        cls.company_b = cls.env['res.company'].create({'name': 'Test Company B'})
        cls.station_kitchen_b = cls.env['kds.station'].create({
            'name': 'Test Kitchen B', 'code': 'TESTKITCHENB', 'target_prep_time': 10,
            'company_id': cls.company_b.id,
        })

        cls.categ_food = cls.env['product.category'].create({'name': 'Test Food'})
        cls.categ_drinks = cls.env['product.category'].create({'name': 'Test Drinks'})

        # Left with no explicit `type` - the exact allowed values for
        # product.template.type have shifted between Odoo versions
        # (storable/consumable handling changed around v17); the default
        # is 'consu' in every version I'm aware of, which is also always in
        # the allow-list this module's own sync code filters on
        # (models/pos_order.py, models/kds_order_line.py), so leaving it
        # unset here avoids hardcoding a value that might not exist in v19.
        cls.product_burger = cls.env['product.product'].create({
            'name': 'Test Chicken Burger',
            'categ_id': cls.categ_food.id,
        })
        cls.product_cappuccino = cls.env['product.product'].create({
            'name': 'Test Cappuccino',
            'categ_id': cls.categ_drinks.id,
        })

        cls.group_operator = cls.env.ref('flexsys_kds.group_kds_operator')
        cls.group_supervisor = cls.env.ref('flexsys_kds.group_kds_supervisor')
        cls.group_branch_manager = cls.env.ref('flexsys_kds.group_kds_branch_manager')
        cls.group_administrator = cls.env.ref('flexsys_kds.group_kds_administrator')

    @classmethod
    def _make_kds_user(cls, login, group, stations=None):
        # REAL BUG, confirmed live twice now (see hooks.py's own
        # docstring for the full history): the res.users <-> res.groups
        # many2many field name is not stable across installs of this
        # Odoo 19 build - 'groups_id' failed with a real install error
        # ("Invalid field 'groups_id' in 'res.users'"), following an
        # earlier failure on the res.groups side too. Detected at
        # runtime here rather than hardcoded a third time, matching the
        # same fix applied in hooks.py for the exact same relationship.
        groups_field = next(
            (name for name in ('group_ids', 'groups_id') if name in cls.env['res.users']._fields),
            'groups_id',  # last-resort fallback if this build uses a name not seen before - will
                          # raise the same clear "Invalid field" error rather than silently misbehaving
        )
        user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': login,
            'login': login,
            'email': '%s@example.com' % login,
            groups_field: [(6, 0, [group.id])],
        })
        if stations:
            user.kds_station_ids = [(6, 0, stations.ids)]
        return user

    def _make_order(self, lines_product_qty, order_type='dine_in', source='pos', company=None):
        order = self.env['kds.order'].create({
            'source': source,
            'order_type': order_type,
            'company_id': (company or self.company).id,
        })
        for product, qty in lines_product_qty:
            self.env['kds.order.line'].create({
                'order_id': order.id,
                'product_id': product.id,
                'qty': qty,
            })
        return order

    @classmethod
    def _route_line_to_station(cls, line, station):
        """REAL BUG FIX, confirmed live on Odoo.sh (the test suite
        stopped after 5 errors): dozens of tests across this suite used
        to directly `write({'station_id': ...})` on an already-created
        line to move it to a specific station for test setup - but
        station_id has been in KDS_LINE_PROTECTED_FIELDS for a long time
        (kds_order_line.py), so a raw write() without
        kds_workflow_write=True context correctly raises AccessError.
        This worked at some earlier point (before that protection
        existed or was tightened) and was never updated across the
        whole suite afterward - production-code protection itself was
        never the bug, these test fixtures were.

        Fixed here with a single, centralized, well-documented helper
        rather than scattering the fix ad-hoc across every file:
        kds_workflow_write=True is not a bypass of the production
        protection - it is the exact same trusted-internal-write context
        flag production code itself already uses for legitimate station
        assignment (kds_order_line.py's own create() auto-routing,
        pos_order.py's _flexsys_kds_reroute_line()). Using it here, from
        test setup code, applies that identical supported mechanism
        consistently instead of repeating the same incorrect raw
        write() pattern throughout the suite. (test_expeditor.py's own
        two order-building helpers take a different, also-supported
        approach - setting product.kds_station_id so create()'s own
        auto-routing assigns the station with no write() needed at all -
        which fits that file's own emphasis on "the supported creation/
        routing/setup mechanism"; either approach is legitimate, this
        one is simply the more practical fit for tests that need
        multiple different stations across many scenarios rather than a
        single fixed per-product default.)
        """
        line.with_context(kds_workflow_write=True).write({'station_id': station.id})

    # -----------------------------------------------------------------
    # TEST INFRASTRUCTURE ("CI Recovery Round 4"), added per the
    # client's own explicit request: a centralized helper for rendering
    # the kiosk's own _KIOSK_HTML_TEMPLATE in tests, so a future
    # placeholder added to that template only needs updating here once,
    # not in every test file that happens to render it directly.
    # Confirmed against the template's own actual current requirements
    # by extracting every %(...)s/%(...)r placeholder it contains
    # directly (controllers/kds_kiosk.py) - the exact defect this round
    # fixed (a stale test manually rebuilding this dict, missing
    # placeholders the template grew after Arabic Localization) is
    # exactly what this helper exists to prevent recurring.
    # -----------------------------------------------------------------
    def _render_kiosk_template(self, **overrides):
        """Renders controllers/kds_kiosk.py's own _KIOSK_HTML_TEMPLATE
        with every placeholder it currently requires, using reasonable
        defaults - pass keyword overrides for any value a specific test
        needs to control (e.g. kiosk_lang='ar', kiosk_dir='rtl').
        Returns the rendered HTML string."""
        from odoo.addons.flexsys_kds.controllers.kds_kiosk import _KIOSK_HTML_TEMPLATE
        vals = {
            'station_name': 'Test Station', 'branch_name': 'QT01', 'company_name': 'Test Co',
            'station_code': 'TESTSTN', 'token': 'test-token-abc',
            'kiosk_lang': 'en', 'kiosk_dir': 'ltr',
            'branch_label': 'Branch', 'time_label': 'Time',
            # PHASE 2 REGRESSION FIX: the template gained these three
            # placeholders when Direct Network printing was merged in -
            # every pre-existing call site of this helper across the
            # whole test suite would otherwise now raise KeyError on
            # render, confirmed by directly simulating the exact old
            # dict this helper used to build against the template's
            # own current, real placeholder set before adding these.
            'flexsys_printing_method': 'direct_network',
            'flexsys_printer_ip': '',
            'flexsys_use_local_network_access': 'true',
        }
        vals.update(overrides)
        return _KIOSK_HTML_TEMPLATE % vals

