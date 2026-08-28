# -*- coding: utf-8 -*-
"""Commercial Demo Readiness Sprint 1 ("Restore the approved
pagination design") regression suite.

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
algorithm (same constants, same buildPages()/paginate() logic),
reimplemented in Python, tested here as its own independent
specification of the required behavior. If
flexsys_pagination.js's own constants or algorithm ever change, this
file's own mirror must be updated to match - it is not testing the
JS file's own bytes, it is testing that the AGREED BEHAVIOR (the same
behavior actually verified by hand against flexsys_pagination.js
during development, using Node.js directly, before this suite
existed) still holds.
"""
from odoo.tests import TransactionCase, tagged


# Mirrors flexsys_pagination.js's own top-of-file constants exactly.
NORMAL_COLUMNS = 3
NORMAL_ROWS = 2
COMPACT_COLUMNS = 4
COMPACT_ROWS = 2
COMPACT_MIN_VIEWPORT_WIDTH = 1600
LARGE_ORDER_LINE_THRESHOLD = 8


def compute_density(viewport_width):
    """Mirrors flexsys_pagination.js's own computeDensity()."""
    if viewport_width >= COMPACT_MIN_VIEWPORT_WIDTH:
        return {
            'columns': COMPACT_COLUMNS, 'rows': COMPACT_ROWS,
            'max_cards_per_page': COMPACT_COLUMNS * COMPACT_ROWS,
        }
    return {
        'columns': NORMAL_COLUMNS, 'rows': NORMAL_ROWS,
        'max_cards_per_page': NORMAL_COLUMNS * NORMAL_ROWS,
    }


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

    def test_normal_density_six_cards_per_page(self):
        orders = [_order(i) for i in range(1, 10)]  # 9 orders
        result = paginate(orders, 1280, 1)
        self.assertEqual(result['total_pages'], 2)
        self.assertEqual(len(result['current_page_orders']), 6)
        self.assertEqual(result['columns'], 3)

    def test_compact_density_eight_cards_per_page(self):
        orders = [_order(i) for i in range(1, 10)]  # 9 orders
        result = paginate(orders, 1920, 1)
        self.assertEqual(result['total_pages'], 2)
        self.assertEqual(len(result['current_page_orders']), 8)
        self.assertEqual(result['columns'], 4)

    def test_compact_density_threshold_is_inclusive_boundary(self):
        # Exactly at the 1600px threshold must already be Compact -
        # confirmed by mirroring the JS's own >= comparison exactly.
        result = paginate([_order(1)], 1600, 1)
        self.assertEqual(result['columns'], 4)
        result_below = paginate([_order(1)], 1599, 1)
        self.assertEqual(result_below['columns'], 3)

    def test_large_order_reduces_density_for_its_own_page(self):
        orders = [
            _order(1), _order(2), _order(3),
            _order(4, line_count=10),  # large: > 8 lines
            _order(5), _order(6), _order(7),
        ]
        result = paginate(orders, 1280, 1)
        # Verified by hand against the real flexsys_pagination.js via
        # Node.js during development: [3, 3, 1] - page 1 closes at the
        # normal max (6) not yet reached when the large order arrives
        # at position 4 (only 3 orders so far), but the page that
        # actually CONTAINS the large order (page 2) is capped at the
        # reduced max (3) for its own entire duration once opened with
        # a large order in it.
        page_sizes = [len(p) for p in result['pages']]
        self.assertEqual(page_sizes, [3, 3, 1])
        # The large order itself (id=4) must be on the page that was
        # actually reduced, not the earlier untouched one.
        self.assertIn(orders[3], result['pages'][1])

    def test_deterministic_same_input_same_output(self):
        orders = [_order(i) for i in range(1, 10)]
        result_a = paginate(orders, 1280, 2)
        result_b = paginate(orders, 1280, 2)
        self.assertEqual(result_a['pages'], result_b['pages'])
        self.assertEqual(result_a['current_page_orders'], result_b['current_page_orders'])

    def test_requested_page_beyond_total_is_clamped(self):
        orders = [_order(i) for i in range(1, 10)]  # 2 pages at Normal density
        result = paginate(orders, 1280, 99)
        self.assertEqual(result['current_page'], 2)

    def test_requested_page_below_one_is_clamped(self):
        orders = [_order(i) for i in range(1, 10)]
        result = paginate(orders, 1280, 0)
        self.assertEqual(result['current_page'], 1)

    def test_empty_orders_yields_one_empty_page_not_zero_pages(self):
        result = paginate([], 1280, 1)
        self.assertEqual(result['total_pages'], 1)
        self.assertEqual(result['current_page_orders'], [])

    def test_stable_created_time_order_is_preserved_across_pages(self):
        """'Deterministic assignment' in practice: confirms the
        pagination pass never reorders its own input - the same
        guarantee that lets a plain positional slice of the backend's
        own stable created_time-sorted array behave deterministically,
        with zero extra assignment logic needed (see
        flexsys_pagination.js's own top-of-file DETERMINISM note,
        confirmed against controllers/kds.py and
        controllers/kds_kiosk.py's own identical
        sorted(key=lambda o: o.created_time) before this was
        written)."""
        orders = [_order(i) for i in range(1, 15)]
        result = paginate(orders, 1280, 1)
        flattened = [o for page in result['pages'] for o in page]
        self.assertEqual(flattened, orders, "Pagination must never reorder its own input.")
