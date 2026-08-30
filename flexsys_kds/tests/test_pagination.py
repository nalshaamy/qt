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
Density"): the approved COLUMN rule is:
  viewport width <  1600px -> 3 columns
  viewport width >= 1600px -> 4 columns
Never more than 4 columns at any width, however wide.

ADAPTIVE HEIGHT-AWARE ROWS ("Adaptive Height-Aware Pagination -
Internal KDS + Public Kiosk"): SUPERSEDES the prior round's own
"always 2 rows, purely width-driven" assumption - rows is now 2 ONLY
when the real, measured available grid height can fit two genuinely
readable card rows (MIN_TWO_ROW_HEIGHT below, derived transparently
from this project's own already-approved card dimensions - see
flexsys_pagination.js's own matching comment for the exact figures),
otherwise 1. Every pre-existing test below that isn't specifically
about height-awareness passes a deliberately large, fixed
available_grid_height (1000px - comfortably above MIN_TWO_ROW_HEIGHT)
so its own already-verified width/large-order/determinism behavior
keeps exercising the same rows=2 case it always did; the new
height-awareness-specific tests further down are what actually vary
this dimension.
"""
from odoo.tests import TransactionCase, tagged

import math
import re


# Mirrors flexsys_pagination.js's own top-of-file constants exactly.
NORMAL_COLUMNS = 3
WIDE_COLUMNS = 4
WIDE_MIN_VIEWPORT_WIDTH = 1600
LARGE_ORDER_LINE_THRESHOLD = 8
# Mirrors flexsys_pagination.js's own MIN_TWO_ROW_HEIGHT derivation
# exactly - see that file's own comment for the full, itemized
# accounting of every header/line/footer element a normal commercial
# card actually renders (~299px per card, rounded to the clean, safe
# 300px this project now uses - reviewed and corrected from an
# earlier, too-low 174px figure that only counted a bare header/line/
# footer skeleton, omitting order-reference/status/chips/employee rows
# and variant/note rows a normal card typically has).
MIN_READABLE_ROW_HEIGHT = 300
GRID_ROW_GAP = 24
MIN_TWO_ROW_HEIGHT = (MIN_READABLE_ROW_HEIGHT * 2) + GRID_ROW_GAP
# A safe, fixed stand-in for "a screen tall enough for 2 rows, no
# question about it" - used only by the pre-existing tests below that
# are not themselves testing height-awareness.
TALL_ENOUGH_HEIGHT = 1000


def compute_density(viewport_width, available_grid_height=None):
    """Mirrors flexsys_pagination.js's own computeDensity()."""
    columns = WIDE_COLUMNS if viewport_width >= WIDE_MIN_VIEWPORT_WIDTH else NORMAL_COLUMNS
    if isinstance(available_grid_height, (int, float)) and available_grid_height > 0:
        rows = 2 if available_grid_height >= MIN_TWO_ROW_HEIGHT else 1
    else:
        rows = 2
    return {'columns': columns, 'rows': rows, 'max_cards_per_page': columns * rows}


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


def paginate(orders, viewport_width, available_grid_height, requested_page):
    """Mirrors flexsys_pagination.js's own paginate()."""
    density = compute_density(viewport_width, available_grid_height)
    pages = build_pages(orders, density['max_cards_per_page'])
    total_pages = len(pages)
    clamped_page = min(max(1, requested_page or 1), total_pages)
    current_page_orders = pages[clamped_page - 1] if pages else []
    current_page_rows = (
        math.ceil(len(current_page_orders) / density['columns']) if current_page_orders else 0
    )
    return {
        'pages': pages,
        'total_pages': total_pages,
        'current_page': clamped_page,
        'current_page_orders': current_page_orders,
        'columns': density['columns'],
        'rows': density['rows'],
        'current_page_rows': current_page_rows,
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
        result = paginate(orders, 1920, TALL_ENOUGH_HEIGHT, 1)
        self.assertEqual(result['total_pages'], 1)
        self.assertEqual(len(result['current_page_orders']), 8)
        self.assertEqual(result['columns'], 4)

    def test_never_more_than_four_columns_or_eight_cards_at_any_width(self):
        orders = [_order(i) for i in range(1, 21)]
        for width in (3840, 5120, 7680):  # 4K, 5K, 8K
            result = paginate(orders, width, TALL_ENOUGH_HEIGHT, 1)
            self.assertEqual(result['columns'], 4, "width=%s" % width)
            self.assertLessEqual(len(result['current_page_orders']), 8, "width=%s" % width)

    def test_worked_example_14_orders_at_1920_gives_8_then_6(self):
        orders = [_order(i) for i in range(1, 15)]  # 14 orders
        result = paginate(orders, 1920, TALL_ENOUGH_HEIGHT, 1)
        page_sizes = [len(p) for p in result['pages']]
        self.assertEqual(page_sizes, [8, 6])

    def test_worked_example_14_orders_at_1440_gives_6_6_2(self):
        orders = [_order(i) for i in range(1, 15)]  # 14 orders
        result = paginate(orders, 1440, TALL_ENOUGH_HEIGHT, 1)
        page_sizes = [len(p) for p in result['pages']]
        self.assertEqual(page_sizes, [6, 6, 2])

    def test_large_order_reduces_density_for_its_own_page(self):
        orders = [
            _order(1), _order(2), _order(3),
            _order(4, line_count=10),  # large: > 8 lines
            _order(5), _order(6), _order(7),
        ]
        result = paginate(orders, 1920, TALL_ENOUGH_HEIGHT, 1)
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
        result = paginate(orders, 1280, TALL_ENOUGH_HEIGHT, 1)
        page_sizes = [len(p) for p in result['pages']]
        self.assertEqual(page_sizes, [3, 4])
        self.assertIn(orders[2], result['pages'][0])

    def test_deterministic_same_input_same_output(self):
        orders = [_order(i) for i in range(1, 10)]
        result_a = paginate(orders, 1920, TALL_ENOUGH_HEIGHT, 2)
        result_b = paginate(orders, 1920, TALL_ENOUGH_HEIGHT, 2)
        self.assertEqual(result_a['pages'], result_b['pages'])
        self.assertEqual(result_a['current_page_orders'], result_b['current_page_orders'])

    def test_requested_page_beyond_total_is_clamped(self):
        orders = [_order(i) for i in range(1, 10)]  # 9 orders -> 2 pages at 1920px (8+1)
        result = paginate(orders, 1920, TALL_ENOUGH_HEIGHT, 99)
        self.assertEqual(result['total_pages'], 2)
        self.assertEqual(result['current_page'], 2)

    def test_requested_page_below_one_is_clamped(self):
        orders = [_order(i) for i in range(1, 10)]
        result = paginate(orders, 1920, TALL_ENOUGH_HEIGHT, 0)
        self.assertEqual(result['current_page'], 1)

    def test_empty_orders_yields_one_empty_page_not_zero_pages(self):
        result = paginate([], 1920, TALL_ENOUGH_HEIGHT, 1)
        self.assertEqual(result['total_pages'], 1)
        self.assertEqual(result['current_page_orders'], [])

    def test_stable_created_time_order_is_preserved_across_pages(self):
        orders = [_order(i) for i in range(1, 15)]
        result = paginate(orders, 1920, TALL_ENOUGH_HEIGHT, 1)
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

    def test_normal_internal_kds_backend_mode_is_a_fixed_height_flex_column(self):
        """VIEWPORT FIX ("KDS Browser 100% Viewport Fix"): .fs-kds-app
        is now a fixed-height flex column - overflow-y itself lives on
        .fs-grid specifically (see
        test_fs_grid_is_the_flexible_scrolling_region below), never on
        this root element anymore. Renamed from this test's own prior
        name (...has_vertical_scroll), which asserted the OLD
        contract (overflow-y: auto directly on .fs-kds-app) - updated
        to validate the CURRENT architecture instead of reverting it."""
        content = self._read_module_file('static', 'src', 'scss', 'kds_style.scss')
        fs_kds_app_rule = re.search(r'\.fs-kds-app\s*\{(.*?)\n\}', content, re.DOTALL)
        self.assertIsNotNone(fs_kds_app_rule, ".fs-kds-app rule not found at all.")
        rule_body = fs_kds_app_rule.group(1)
        self.assertIn('height: 100%;', rule_body)
        self.assertIn('min-height: 0;', rule_body)
        self.assertIn('display: flex;', rule_body)
        self.assertIn('flex-direction: column;', rule_body)
        self.assertIn('overflow-x: hidden;', rule_body)
        # Item 2: .fs-kds-app must NOT require overflow-y: auto anymore
        # - that responsibility moved to .fs-grid, the one flexible,
        # scrolling region of the new flex column.
        self.assertNotIn('overflow-y: auto;', rule_body)
        # Item 6: the original regression this suite guards against -
        # a fixed viewport height, never a forced min-height: 100vh
        # that would push this element taller than its own real
        # parent's available space in the normal (non-kiosk) backend
        # action.
        self.assertNotIn('min-height: 100vh;', rule_body)

    def test_fs_grid_is_the_flexible_scrolling_region(self):
        """The one region that actually scrolls in the new flex-column
        architecture - claims exactly the leftover space between the
        fixed-size header/filters wrapper and the fixed-size
        pagination bar, and scrolls internally when a card grid
        genuinely doesn't fit."""
        content = self._read_module_file('static', 'src', 'scss', 'kds_style.scss')
        fs_grid_rule = re.search(r'\n\.fs-grid\s*\{(.*?)\n\}', content, re.DOTALL)
        self.assertIsNotNone(fs_grid_rule, ".fs-grid rule not found at all.")
        rule_body = fs_grid_rule.group(1)
        self.assertIn('flex: 1 1 auto;', rule_body)
        self.assertIn('min-height: 0;', rule_body)
        self.assertIn('overflow-y: auto;', rule_body)

    def test_fs_sticky_top_does_not_shrink_in_the_flex_column(self):
        """The header + status filters + dropdown filters wrapper must
        keep its own natural height in the new flex column, never
        compressed to make room for the grid below it."""
        content = self._read_module_file('static', 'src', 'scss', 'kds_style.scss')
        fs_sticky_top_rule = re.search(r'\.fs-sticky-top\s*\{(.*?)\n\}', content, re.DOTALL)
        self.assertIsNotNone(fs_sticky_top_rule, ".fs-sticky-top rule not found at all.")
        self.assertIn('flex-shrink: 0;', fs_sticky_top_rule.group(1))

    def test_fs_pagination_does_not_shrink_in_the_flex_column(self):
        """The pagination bar must keep its own natural height in the
        new flex column, staying visible at the bottom of the
        available area without needing to overlap the grid above it."""
        content = self._read_module_file('static', 'src', 'scss', 'kds_style.scss')
        fs_pagination_rule = re.search(r'\n\.fs-pagination\s*\{(.*?)\n\}', content, re.DOTALL)
        self.assertIsNotNone(fs_pagination_rule, ".fs-pagination rule not found at all.")
        self.assertIn('flex-shrink: 0;', fs_pagination_rule.group(1))

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

    def test_public_kiosk_is_a_fixed_height_flex_column(self):
        """RENAMED from test_public_kiosk_keeps_vertical_scrolling
        (stale, from before the "Public Kiosk - Full Viewport Flex
        Layout Fix" architecture) - confirmed by direct inspection of
        controllers/kds_kiosk.py's own real HTML/CSS that there is no
        body.o_flexsys_kiosk (or any other kiosk-specific body class)
        anywhere in this standalone page - it uses plain body/html
        directly, since this page has no Odoo backend chrome to share
        a class-scoped selector with at all. body is now the flex
        column that owns the whole vertical layout (mirroring the
        same fix already applied to Internal KDS's own .fs-kds-app) -
        overflow-y itself moved from body to .grid specifically, the
        one region that actually scrolls; body itself keeps only
        overflow-x:hidden (the explicit "no horizontal scroll"
        requirement) and must never regain a hard overflow:hidden,
        which would silently re-block genuine scrolling for a
        many-orders page."""
        content = self._read_module_file('controllers', 'kds_kiosk.py')
        body_rule = re.search(r'\n  body\{(.*?)\n  \}', content, re.DOTALL)
        self.assertIsNotNone(body_rule)
        body_text = body_rule.group(1)
        self.assertIn('display:flex; flex-direction:column;', body_text)
        self.assertIn('overflow-x:hidden;', body_text)
        self.assertNotIn('overflow-y:auto;', body_text,
                          "overflow-y must have moved to .grid, not remain on body itself.")
        self.assertNotIn('overflow:hidden;', body_text)

        grid_rule = re.search(r'\n  \.grid\{(.*?)\n  \}', content, re.DOTALL)
        self.assertIsNotNone(grid_rule, ".grid rule not found at all.")
        grid_text = grid_rule.group(1)
        self.assertIn('flex:1 1 auto; min-height:0; overflow-y:auto;', grid_text)

        for selector in ('header', 'filters', 'pagination', 'statbar'):
            rule = re.search(r'\n  \.%s\{(.*?)\n  \}' % selector, content, re.DOTALL)
            self.assertIsNotNone(rule, ".%s rule not found at all." % selector)
            self.assertIn('flex-shrink:0;', rule.group(1),
                           ".%s must not shrink in the flex column." % selector)

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


@tagged('post_install', '-at_install')
class TestAdaptiveHeightAwarePagination(TransactionCase):
    """"Adaptive Height-Aware Pagination - Internal KDS + Public
    Kiosk" - the shared engine's own row count is now height-aware,
    not purely width-driven. Same Python Parity Mirror approach as
    TestPagination above (see this file's own top-of-file HONEST
    SCOPE NOTE) - these tests exercise compute_density()/paginate()'s
    own newly-added available_grid_height dimension specifically."""

    @staticmethod
    def _read_module_file(*relative_parts):
        """Same helper as TestPagination's own copy above - duplicated
        here (not shared) since this is a separate TransactionCase
        class; a plain file read, not worth extracting into shared
        infrastructure for two classes in one file."""
        import os
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(module_dir, *relative_parts)
        with open(path, encoding='utf-8') as f:
            return f.read()

    def test_1_wide_and_tall_gives_4x2(self):
        density = compute_density(1920, MIN_TWO_ROW_HEIGHT)
        self.assertEqual(density['columns'], 4)
        self.assertEqual(density['rows'], 2)
        self.assertEqual(density['max_cards_per_page'], 8)

    def test_2_wide_and_short_gives_4x1(self):
        density = compute_density(1920, MIN_TWO_ROW_HEIGHT - 1)
        self.assertEqual(density['columns'], 4)
        self.assertEqual(density['rows'], 1)
        self.assertEqual(density['max_cards_per_page'], 4)

    def test_3_normal_and_tall_gives_3x2(self):
        density = compute_density(1280, MIN_TWO_ROW_HEIGHT)
        self.assertEqual(density['columns'], 3)
        self.assertEqual(density['rows'], 2)
        self.assertEqual(density['max_cards_per_page'], 6)

    def test_4_normal_and_short_gives_3x1(self):
        density = compute_density(1280, MIN_TWO_ROW_HEIGHT - 1)
        self.assertEqual(density['columns'], 3)
        self.assertEqual(density['rows'], 1)
        self.assertEqual(density['max_cards_per_page'], 3)

    def test_5_six_orders_on_wide_short_viewport_needs_two_pages(self):
        """The exact scenario reported: 6 orders, wide-but-short
        viewport - 4 columns is correct, but a short grid must NOT
        force 2 rows (8/page); it must be 4x1 (4/page), splitting the
        6 orders across 2 pages (4 then 2) instead of clipping/
        overlapping a forced second row."""
        orders = [_order(i) for i in range(1, 7)]  # 6 orders
        result = paginate(orders, 1920, MIN_TWO_ROW_HEIGHT - 1, 1)
        self.assertEqual(result['columns'], 4)
        self.assertEqual(result['rows'], 1)
        self.assertEqual(result['total_pages'], 2)
        page_sizes = [len(p) for p in result['pages']]
        self.assertEqual(page_sizes, [4, 2])
        self.assertEqual(len(result['current_page_orders']), 4)
        # GRID ROWS: page 1 has 4 orders across 4 columns -> exactly 1
        # row, never an implicit/empty second row reserved.
        self.assertEqual(result['current_page_rows'], 1)

    def test_6_fullscreen_height_increase_recalculates_capacity(self):
        """Simulates a resize/fullscreen-entry event that increases
        the real available grid height mid-session - the SAME paginate()
        call, given the new taller height on its next invocation, must
        recompute to the higher-capacity 4x2 - no reload, no separate
        code path, exactly the existing resize-recalculation pattern
        this shared engine has always used for width."""
        orders = [_order(i) for i in range(1, 7)]  # 6 orders
        # Before: normal browser window, short grid -> 4x1, 2 pages.
        before = paginate(orders, 1920, MIN_TWO_ROW_HEIGHT - 1, 1)
        self.assertEqual(before['rows'], 1)
        self.assertEqual(before['total_pages'], 2)
        # After: fullscreen entered, grid now tall enough -> 4x2, all
        # 6 orders fit on the one page.
        after = paginate(orders, 1920, MIN_TWO_ROW_HEIGHT, before['current_page'])
        self.assertEqual(after['rows'], 2)
        self.assertEqual(after['total_pages'], 1)
        self.assertEqual(len(after['current_page_orders']), 6)

    def test_7_large_order_reduced_capacity_still_valid_with_height_awareness(self):
        """Existing large-order protection (LARGE_ORDER_LINE_THRESHOLD)
        remains a valid, ADDITIONAL constraint on top of height-aware
        density, not replaced by it - confirmed at a short-grid tier
        (4x1 = 4/page, reduced to 2 for a page containing a large
        order) as well as the original tall-grid tier already covered
        by TestPagination.test_large_order_reduces_density_for_its_own_page
        above."""
        orders = [
            _order(1), _order(2, line_count=10),  # large: > 8 lines
            _order(3), _order(4), _order(5),
        ]
        result = paginate(orders, 1920, MIN_TWO_ROW_HEIGHT - 1, 1)
        self.assertEqual(result['columns'], 4)
        self.assertEqual(result['rows'], 1)
        # max_cards_per_page = 4x1 = 4; reduced (large-order) cap = 2.
        page_sizes = [len(p) for p in result['pages']]
        self.assertEqual(page_sizes, [2, 3])
        self.assertIn(orders[1], result['pages'][0])

    def test_min_two_row_height_reflects_a_genuinely_readable_normal_card(self):
        """"Adaptive Pagination Review - Correct Readable Row Height +
        Card Safety": the earlier 174px-per-card figure only counted
        a bare header/one-line/footer skeleton, omitting several
        elements a normal commercial card's own header actually
        renders (order reference, status row, chips row, employee
        row) and the variant/note rows a normal order's own line item
        typically has - producing an unrealistically low threshold
        that would let 2-row mode trigger well before two genuinely
        readable rows could actually fit. The reviewed figure (300px
        per row, itemized in this file's own top-of-file comment) is
        within the 250-320px range confirmed by static review against
        the actual current CSS."""
        self.assertEqual(MIN_READABLE_ROW_HEIGHT, 300)
        self.assertGreaterEqual(MIN_READABLE_ROW_HEIGHT, 250)
        self.assertLessEqual(MIN_READABLE_ROW_HEIGHT, 320)
        self.assertEqual(MIN_TWO_ROW_HEIGHT, 624)

    @staticmethod
    def _read_shared_js_file():
        import os
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(module_dir, 'static', 'src', 'shared', 'flexsys_pagination.js')
        with open(path, encoding='utf-8') as f:
            return f.read()

    def test_fs_card_cannot_exceed_its_explicit_grid_row(self):
        """CARD MUST NEVER OVERFLOW ITS GRID ROW: .fs-card's own
        max-height must combine BOTH the existing fixed 640px ceiling
        (for a genuinely oversized order) AND the card's own real
        grid row height (min(640px, 100%)) - never just the fixed
        pixel value alone, which would let a card grow past its own
        row's real available height on a screen where that row is
        shorter than 640px."""
        content = self._read_module_file('static', 'src', 'scss', 'kds_style.scss')
        fs_card_rule = re.search(r'\n\.fs-card \{(.*?)\n\}', content, re.DOTALL)
        self.assertIsNotNone(fs_card_rule, ".fs-card rule not found.")
        rule_body = fs_card_rule.group(1)
        self.assertIn('max-height: min(640px, 100%);', rule_body)
        self.assertIn('min-height: 0;', rule_body)

    def test_card_cannot_exceed_its_explicit_grid_row_in_kiosk(self):
        """Same CARD MUST NEVER OVERFLOW ITS GRID ROW contract, Public
        Kiosk's own .card rule."""
        content = self._read_module_file('controllers', 'kds_kiosk.py')
        card_rule = re.search(r'\n  \.card\{(.*?)\n  \}', content, re.DOTALL)
        self.assertIsNotNone(card_rule, ".card rule not found in controllers/kds_kiosk.py.")
        rule_body = card_rule.group(1)
        # NOTE: this reads the raw Python source file directly - the
        # literal % in "100%" must be doubled (%%) in that source to
        # survive this file's own `template % values` rendering step
        # (see render_kiosk() further down this same file), so the
        # SOURCE text is genuinely "100%%" here, only ever becoming a
        # single "%" in the actual rendered HTML output.
        self.assertIn('max-height:min(640px, 100%%);', rule_body)
        self.assertIn('min-height:0;', rule_body)

    def test_short_cards_remain_natural_height_no_forced_height_100_percent(self):
        """Short cards must keep their own natural height, never be
        force-stretched to fill their row - .fs-card/.card must NOT
        declare height: 100% anywhere (only max-height, a ceiling, not
        a forced size)."""
        scss_content = self._read_module_file('static', 'src', 'scss', 'kds_style.scss')
        fs_card_rule = re.search(r'\n\.fs-card \{(.*?)\n\}', scss_content, re.DOTALL)
        self.assertNotIn('height: 100%;', fs_card_rule.group(1))

        kiosk_content = self._read_module_file('controllers', 'kds_kiosk.py')
        card_rule = re.search(r'\n  \.card\{(.*?)\n  \}', kiosk_content, re.DOTALL)
        self.assertNotIn('height:100%%;', card_rule.group(1))

    def test_align_items_stretch_workaround_is_not_restored(self):
        """The V66/V67 align-items:stretch workaround must remain
        removed - .fs-grid/.grid must keep their own default
        align-items:start everywhere, never stretch, which would
        force every card in a row (including genuinely short ones) to
        fill the row's full height regardless of its own real
        content. Comments are stripped before searching - this file's
        own historical comments legitimately MENTION the removed
        rule's own former text as context for why it was removed;
        only actual, uncommented CSS matters here."""
        scss_content = self._read_module_file('static', 'src', 'scss', 'kds_style.scss')
        scss_code_only = re.sub(r'//[^\n]*', '', scss_content)
        self.assertNotIn('align-items: stretch', scss_code_only)

        kiosk_content = self._read_module_file('controllers', 'kds_kiosk.py')
        kiosk_code_only = re.sub(r'/\*.*?\*/', '', kiosk_content, flags=re.DOTALL)
        self.assertNotIn('align-items:stretch', kiosk_code_only)
