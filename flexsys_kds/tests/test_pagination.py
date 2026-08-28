# -*- coding: utf-8 -*-
"""Commercial Demo Readiness regression suite for the Shared
Pagination Engine and related Internal KDS / Public Kiosk layout
fixes.

HONEST SCOPE NOTE: the actual pagination logic lives entirely in
static/src/shared/flexsys_pagination.js - plain JavaScript, loaded
identically by both Internal KDS and Public Kiosk (the same "one
shared file" guarantee already used for the Ticket Renderer). Odoo's
own Python test runner cannot execute that file directly, and this
suite deliberately does NOT shell out to a Node.js binary to run it
(Node.js availability on the client's own Odoo.sh/production
environment is not something this codebase can assume or depend on
for a regression gate).

Instead, this file is a Python PARITY MIRROR: the exact same
algorithm (same constants, same computeDensity()/buildPages()/
paginate() logic), reimplemented in Python, tested here as its own
independent specification of the required behavior. If
flexsys_pagination.js's own constants or algorithm ever change, this
file's own mirror must be updated to match - it is not testing the
JS file's own bytes, it is testing that the AGREED BEHAVIOR still
holds.

APPROVED DENSITY ("Commercial Demo Layout Adjustment - Adaptive 4x2
Density"): SUPERSEDES the prior round's own "fixed 3x2 always,
including Full HD" decision, per explicit direction after a real
Visual Runtime Review on Odoo.sh. The approved rule is now:
  viewport width <  1600px -> 3 columns x 2 rows = 6 cards/page
  viewport width >= 1600px -> 4 columns x 2 rows = 8 cards/page
Never more than 4 columns or 8 cards/page at any width, however wide.
"""
from odoo.tests import TransactionCase, tagged

import re


# Mirrors flexsys_pagination.js's own top-of-file constants exactly.
NORMAL_COLUMNS = 3
NORMAL_ROWS = 2
WIDE_COLUMNS = 4
WIDE_ROWS = 2
WIDE_MIN_VIEWPORT_WIDTH = 1600
LARGE_ORDER_LINE_THRESHOLD = 8


def compute_density(viewport_width):
    """Mirrors flexsys_pagination.js's own computeDensity()."""
    if viewport_width >= WIDE_MIN_VIEWPORT_WIDTH:
        return {'columns': WIDE_COLUMNS, 'rows': WIDE_ROWS, 'max_cards_per_page': WIDE_COLUMNS * WIDE_ROWS}
    return {'columns': NORMAL_COLUMNS, 'rows': NORMAL_ROWS, 'max_cards_per_page': NORMAL_COLUMNS * NORMAL_ROWS}


def build_pages(orders, max_cards_per_page):
    """Mirrors flexsys_pagination.js's own buildPages() - a single
    forward pass over the input in the order given, deterministic,
    never sorts/shuffles. A page containing an 'unusually large'
    order (more than LARGE_ORDER_LINE_THRESHOLD lines) closes early at
    half capacity instead of the normal max."""
    pages = []
    current = []
    current_has_large = False
    reduced_max = max(2, max_cards_per_page // 2)

    for order in orders:
        line_count = len(order.get('lines', []))
        is_large = line_count > LARGE_ORDER_LINE_THRESHOLD
        effective_max = reduced_max if (current_has_large or is_large) else max_cards_per_page

        if len(current) >= effective_max:
            pages.append(current)
            current = []
            current_has_large = False
        current.append(order)
        if is_large:
            current_has_large = True

    if current:
        pages.append(current)
    if not pages:
        pages.append([])
    return pages


def paginate(orders, viewport_width, requested_page):
    """Mirrors flexsys_pagination.js's own paginate()."""
    density = compute_density(viewport_width)
    pages = build_pages(orders, density['max_cards_per_page'])
    total_pages = len(pages)
    clamped_page = min(max(1, requested_page or 1), total_pages)
    return {
        'pages': pages,
        'total_pages': total_pages,
        'current_page': clamped_page,
        'current_page_orders': pages[clamped_page - 1] if pages else [],
        'columns': density['columns'],
        'rows': density['rows'],
    }


def _order(order_id, line_count=1):
    return {'id': order_id, 'lines': [{}] * line_count}


@tagged('post_install', '-at_install')
class TestPagination(TransactionCase):
    """No database fixtures needed at all - this is pure calculation
    logic, tested as a standalone specification. Uses TransactionCase
    (not plain unittest.TestCase) only for consistency with the rest
    of this suite's own tagging/discovery convention."""

    def test_below_boundary_is_normal_3x2_6(self):
        for width in (400, 1280, 1366, 1440, 1599):
            density = compute_density(width)
            self.assertEqual(density['columns'], 3, "width=%s" % width)
            self.assertEqual(density['rows'], 2, "width=%s" % width)
            self.assertEqual(density['max_cards_per_page'], 6, "width=%s" % width)

    def test_at_and_above_boundary_is_wide_4x2_8(self):
        for width in (1600, 1920, 2560, 3840):
            density = compute_density(width)
            self.assertEqual(density['columns'], 4, "width=%s" % width)
            self.assertEqual(density['rows'], 2, "width=%s" % width)
            self.assertEqual(density['max_cards_per_page'], 8, "width=%s" % width)

    def test_1599_vs_1600_exact_boundary(self):
        self.assertEqual(compute_density(1599)['columns'], 3)
        self.assertEqual(compute_density(1599)['max_cards_per_page'], 6)
        self.assertEqual(compute_density(1600)['columns'], 4)
        self.assertEqual(compute_density(1600)['max_cards_per_page'], 8)

    def test_1920_first_page_with_eight_normal_orders_is_eight_cards(self):
        orders = [_order(i) for i in range(1, 9)]  # exactly 8 orders
        result = paginate(orders, 1920, 1)
        self.assertEqual(result['total_pages'], 1)
        self.assertEqual(len(result['current_page_orders']), 8)
        self.assertEqual(result['columns'], 4)

    def test_never_more_than_four_columns_or_eight_cards_at_any_width(self):
        orders = [_order(i) for i in range(1, 21)]
        for width in (3840, 5120, 7680):  # 4K, 5K, 8K
            result = paginate(orders, width, 1)
            self.assertEqual(result['columns'], 4, "width=%s" % width)
            self.assertLessEqual(len(result['current_page_orders']), 8, "width=%s" % width)

    def test_worked_example_14_orders_at_1920_gives_8_then_6(self):
        orders = [_order(i) for i in range(1, 15)]  # 14 orders
        result = paginate(orders, 1920, 1)
        page_sizes = [len(p) for p in result['pages']]
        self.assertEqual(page_sizes, [8, 6])

    def test_worked_example_14_orders_at_1440_gives_6_6_2(self):
        orders = [_order(i) for i in range(1, 15)]  # 14 orders
        result = paginate(orders, 1440, 1)
        page_sizes = [len(p) for p in result['pages']]
        self.assertEqual(page_sizes, [6, 6, 2])

    def test_large_order_reduces_density_for_its_own_page(self):
        orders = [
            _order(1), _order(2), _order(3),
            _order(4, line_count=10),  # large: > 8 lines
            _order(5), _order(6), _order(7),
        ]
        result = paginate(orders, 1920, 1)
        # At 1920px (Wide: max=8, reduced=4): the large order (id=4)
        # arrives as the 4th item, while the page is still under both
        # the normal (8) AND reduced (4) caps (3 orders so far) - it
        # joins the SAME page as the 3 before it, immediately dropping
        # that page's own effective cap to 4 for everything after -
        # the page closes right there, at exactly 4.
        page_sizes = [len(p) for p in result['pages']]
        self.assertEqual(page_sizes, [4, 3])
        self.assertIn(orders[3], result['pages'][0])

    def test_large_order_reduction_also_applies_at_normal_density(self):
        """Same large-order mechanism, confirmed independently at the
        Normal (< 1600px) tier too - not just the Wide tier above."""
        orders = [
            _order(1), _order(2),
            _order(3, line_count=10),  # large
            _order(4), _order(5), _order(6), _order(7),
        ]
        result = paginate(orders, 1280, 1)
        page_sizes = [len(p) for p in result['pages']]
        self.assertEqual(page_sizes, [3, 4])
        self.assertIn(orders[2], result['pages'][0])

    def test_deterministic_same_input_same_output(self):
        orders = [_order(i) for i in range(1, 10)]
        result_a = paginate(orders, 1920, 2)
        result_b = paginate(orders, 1920, 2)
        self.assertEqual(result_a['pages'], result_b['pages'])
        self.assertEqual(result_a['current_page_orders'], result_b['current_page_orders'])

    def test_requested_page_beyond_total_is_clamped(self):
        orders = [_order(i) for i in range(1, 10)]  # 9 orders -> 2 pages at 1920px (8+1)
        result = paginate(orders, 1920, 99)
        self.assertEqual(result['total_pages'], 2)
        self.assertEqual(result['current_page'], 2)

    def test_requested_page_below_one_is_clamped(self):
        orders = [_order(i) for i in range(1, 10)]
        result = paginate(orders, 1920, 0)
        self.assertEqual(result['current_page'], 1)

    def test_empty_orders_yields_one_empty_page_not_zero_pages(self):
        result = paginate([], 1920, 1)
        self.assertEqual(result['total_pages'], 1)
        self.assertEqual(result['current_page_orders'], [])

    def test_stable_created_time_order_is_preserved_across_pages(self):
        orders = [_order(i) for i in range(1, 15)]
        result = paginate(orders, 1920, 1)
        flattened = [o for page in result['pages'] for o in page]
        self.assertEqual(flattened, orders, "Pagination must never reorder its own input.")

    @staticmethod
    def _read_module_file(*relative_parts):
        import os
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(module_dir, *relative_parts)
        with open(path, encoding='utf-8') as f:
            return f.read()

    def test_internal_kds_calls_shared_pagination_paginate(self):
        content = self._read_module_file('static', 'src', 'js', 'kds_app.js')
        self.assertIn('window.FlexSysPagination.paginate(', content)
        self.assertNotRegex(content, r'\bmaxCardsPerPage\s*=\s*\d')

    def test_public_kiosk_calls_shared_pagination_paginate(self):
        content = self._read_module_file('controllers', 'kds_kiosk.py')
        self.assertIn('window.FlexSysPagination.paginate(', content)
        self.assertNotRegex(content, r'\bmaxCardsPerPage\s*=\s*\d')

    def test_internal_kds_template_reads_pagination_columns(self):
        content = self._read_module_file('static', 'src', 'xml', 'kds_templates.xml')
        self.assertIn('pagination.columns', content)

    def test_public_kiosk_reads_pageresult_columns(self):
        content = self._read_module_file('controllers', 'kds_kiosk.py')
        self.assertIn('pageResult.columns', content)

    def test_internal_kds_pagination_buttons_use_t_att_disabled(self):
        content = self._read_module_file('static', 'src', 'xml', 'kds_templates.xml')
        literal_disabled_pattern = re.compile(r'(?<!t-att-)disabled="pag')
        matches = literal_disabled_pattern.findall(content)
        self.assertFalse(matches)
        self.assertIn('t-att-disabled="pagState.page', content)
        self.assertIn('t-att-disabled="pagState.page &gt;= pagination.totalPages', content)

    def test_normal_internal_kds_backend_mode_has_vertical_scroll(self):
        content = self._read_module_file('static', 'src', 'scss', 'kds_style.scss')
        fs_kds_app_rule = re.search(r'\.fs-kds-app\s*\{(.*?)\n\}', content, re.DOTALL)
        self.assertIsNotNone(fs_kds_app_rule, ".fs-kds-app rule not found at all.")
        rule_body = fs_kds_app_rule.group(1)
        self.assertIn('overflow-y: auto;', rule_body)
        self.assertIn('height: 100%;', rule_body)
        self.assertIn('min-height: 0;', rule_body)
        self.assertNotIn('min-height: 100vh;', rule_body)

    def test_normal_internal_kds_backend_mode_horizontal_scroll_stays_hidden(self):
        content = self._read_module_file('static', 'src', 'scss', 'kds_style.scss')
        fs_kds_app_rule = re.search(r'\.fs-kds-app\s*\{(.*?)\n\}', content, re.DOTALL)
        self.assertIn('overflow-x: hidden;', fs_kds_app_rule.group(1))
        self.assertIn(':has(.fs-kds-app)', content)
        self.assertNotRegex(content, r'\n\.o_action_manager\s*\{')

    def test_kiosk_mode_body_still_scrolls_vertically(self):
        content = self._read_module_file('static', 'src', 'scss', 'kds_style.scss')
        kiosk_body_rule = re.search(r'body\.o_flexsys_kiosk\s*\{(.*)', content, re.DOTALL)
        self.assertIsNotNone(kiosk_body_rule)
        tail = kiosk_body_rule.group(1).split('\n}', 1)[0]
        self.assertIn('overflow-y: auto;', tail)
        self.assertIn('overflow-x: hidden;', tail)

    def test_public_kiosk_keeps_vertical_scrolling(self):
        content = self._read_module_file('controllers', 'kds_kiosk.py')
        body_rule = re.search(r'\n  body\{(.*?)\n  \}', content, re.DOTALL)
        self.assertIsNotNone(body_rule)
        self.assertIn('overflow-y:auto; overflow-x:hidden;', body_rule.group(1))
        self.assertNotIn('overflow:hidden;', body_rule.group(1))

    def test_card_width_remains_95_percent_centered(self):
        scss_content = self._read_module_file('static', 'src', 'scss', 'kds_style.scss')
        kiosk_content = self._read_module_file('controllers', 'kds_kiosk.py')

        fs_card_rule = re.search(r'\.fs-card\s*\{(.*?)\n\}', scss_content, re.DOTALL)
        self.assertIn('width: 95%;', fs_card_rule.group(1))
        self.assertIn('justify-self: center;', fs_card_rule.group(1))
        self.assertNotIn('width: 100%;', fs_card_rule.group(1))
        self.assertNotIn('width: 90%;', fs_card_rule.group(1))

        card_rule = re.search(r'\n  \.card\{(.*?)\n  \}', kiosk_content, re.DOTALL)
        self.assertIsNotNone(card_rule)
        self.assertIn('width:95%%; justify-self:center;', card_rule.group(1))
        self.assertNotIn('width:100%%;', card_rule.group(1))
        self.assertNotIn('width:90%%;', card_rule.group(1))

    def test_internal_kds_pagination_is_sticky_bottom(self):
        """UI ADJUSTMENT ("Internal KDS Sticky Pagination"): confirmed
        live - with two full rows of cards, Previous/Next/page
        indicator sat below the fold, only reachable by scrolling
        down. .fs-pagination must be position: sticky; bottom: 0 with
        a solid background (so scrolling card content doesn't show
        through underneath it) - Internal KDS ONLY, per explicit
        direction that Public Kiosk's own pagination bar is visually
        fine as-is and must not be touched."""
        content = self._read_module_file('static', 'src', 'scss', 'kds_style.scss')
        fs_pagination_rule = re.search(r'\.fs-pagination\s*\{(.*?)\n\}', content, re.DOTALL)
        self.assertIsNotNone(fs_pagination_rule, ".fs-pagination rule not found.")
        rule_body = fs_pagination_rule.group(1)

        self.assertIn('position: sticky;', rule_body)
        self.assertIn('bottom: 0;', rule_body)
        self.assertRegex(
            rule_body, r'background:\s*\$fs-bg\s*;',
            ".fs-pagination needs a solid background so card content scrolling "
            "underneath it doesn't visually show through."
        )
        self.assertIn('z-index: 20;', rule_body)

    def test_fs_grid_has_bottom_padding_for_sticky_pagination_clearance(self):
        """Reserves room below the last card row so it can never end
        up hidden behind .fs-pagination's own now-sticky bar."""
        content = self._read_module_file('static', 'src', 'scss', 'kds_style.scss')
        fs_grid_rule = re.search(r'\.fs-grid\s*\{(.*?)\n\}', content, re.DOTALL)
        self.assertIsNotNone(fs_grid_rule, ".fs-grid rule not found.")
        self.assertRegex(fs_grid_rule.group(1), r'padding-bottom:\s*\d+px\s*;')

    def test_public_kiosk_pagination_bar_is_unchanged(self):
        """Explicit requirement: Public Kiosk's own pagination bar is
        visually fine as confirmed live and must NOT be made sticky -
        this test guards against that ever happening by mistake."""
        content = self._read_module_file('controllers', 'kds_kiosk.py')
        pagination_rule = re.search(r'\n  \.pagination\{(.*?)\n  \}', content, re.DOTALL)
        self.assertIsNotNone(pagination_rule, ".pagination rule not found in controllers/kds_kiosk.py.")
        self.assertNotIn('position:sticky', pagination_rule.group(1))
        self.assertNotIn('position: sticky', pagination_rule.group(1))
