/**
 * FlexSys KDS - Shared High-Density Pagination Logic (Production)
 *
 * The ONE shared file both Internal KDS (loaded via 'web.assets_backend',
 * a plain non-module script) and Public Kiosk (loaded via a plain
 * <script src="..."> tag) both load and call identically - the same
 * architectural guarantee already used for the Shared Ticket Renderer:
 * "Same Order Data -> Same Pagination Behavior" is a structural fact,
 * not a promise kept by hand-syncing two separate implementations.
 *
 * APPROVED DENSITY ("Commercial Demo Layout Adjustment - Adaptive 4x2
 * Density"): SUPERSEDES the prior round's own "fixed 3x2 always,
 * including Full HD" decision - a real Visual Runtime Review on
 * Odoo.sh showed the fixed-3x2 card was still wider than it needed to
 * be on a Full HD display, with room for a genuine 4th column instead
 * of being stretched to fill 3 wide ones. The approved rule now is:
 *   viewport width <  1600px -> 3 columns x 2 rows = 6 cards/page
 *   viewport width >= 1600px -> 4 columns x 2 rows = 8 cards/page
 * Never more than 4 columns or 8 cards/page at any width, however
 * wide. The ONLY thing that ever further reduces the page's own
 * effective card count below whichever of those two maximums applies
 * is an unusually large individual order (see
 * LARGE_ORDER_LINE_THRESHOLD below) - not screen width itself beyond
 * the two-tier rule above.
 *
 * DETERMINISM: both controllers/kds.py and controllers/kds_kiosk.py
 * already sort orders identically (`sorted(key=lambda o:
 * o.created_time)`, confirmed by direct read before writing this) -
 * so a plain, position-preserving slice of that same, stable-ordered
 * array is deterministic by construction. This module never re-sorts
 * or shuffles the array it's given - only paginate() below performs a
 * position-preserving pass over the same order.
 *
 * DOES NOT touch order workflow/state/filter semantics at all - takes
 * an already-filtered array as its only input, knows nothing about
 * what a "filter" means.
 */
(function () {
    "use strict";

    // Smaller-desktop density.
    var NORMAL_COLUMNS = 3;
    var NORMAL_ROWS = 2;
    // Large/Full-HD-and-above density.
    var WIDE_COLUMNS = 4;
    var WIDE_ROWS = 2;
    // The single boundary between the two tiers - a viewport at or
    // above this width uses WIDE_*, below it uses NORMAL_*. Matches a
    // typical Full HD (1920px) display's own usable width comfortably,
    // while still applying to some smaller-but-still-wide desktop
    // displays right at the boundary, per the explicit worked
    // examples (1599px -> 3x2, 1600px -> 4x2).
    var WIDE_MIN_VIEWPORT_WIDTH = 1600;

    // A card is considered "unusually large" past this many product
    // lines - a page containing one is given a reduced effective
    // capacity (rather than forcing every card on that page to
    // compress to illegibility to fit the normal count). This applies
    // on top of whichever of the two density tiers above is active -
    // it never itself raises the count past that tier's own maximum.
    var LARGE_ORDER_LINE_THRESHOLD = 8;

    /**
     * @param {number} viewportWidth
     * @returns {{columns: number, rows: number, maxCardsPerPage: number}}
     */
    function computeDensity(viewportWidth) {
        if (viewportWidth >= WIDE_MIN_VIEWPORT_WIDTH) {
            return { columns: WIDE_COLUMNS, rows: WIDE_ROWS, maxCardsPerPage: WIDE_COLUMNS * WIDE_ROWS };
        }
        return { columns: NORMAL_COLUMNS, rows: NORMAL_ROWS, maxCardsPerPage: NORMAL_COLUMNS * NORMAL_ROWS };
    }

    /**
     * Splits an already-ordered, already-filtered array of orders into
     * pages, each normally sized at maxCardsPerPage - except a page
     * that would otherwise contain an "unusually large" order (more
     * than LARGE_ORDER_LINE_THRESHOLD lines), which is closed early at
     * half that capacity instead, so a big order's own full content
     * stays readable rather than being squeezed to fit alongside a
     * full page of normal-sized neighbors.
     *
     * Deterministic: a single forward pass over the input array in the
     * order given - never sorts, never shuffles. The exact same input
     * array always produces the exact same set of pages.
     *
     * @param {Array<{lines?: Array}>} orders - already filtered, in
     *   the same stable created_time order the backend itself returns.
     * @param {number} maxCardsPerPage
     * @returns {Array<Array>} pages - an array of order arrays.
     */
    function buildPages(orders, maxCardsPerPage) {
        var pages = [];
        var current = [];
        var currentHasLarge = false;
        var reducedMax = Math.max(2, Math.floor(maxCardsPerPage / 2));

        for (var i = 0; i < orders.length; i++) {
            var order = orders[i];
            var lineCount = (order.lines && order.lines.length) || 0;
            var isLarge = lineCount > LARGE_ORDER_LINE_THRESHOLD;
            var effectiveMax = currentHasLarge || isLarge ? reducedMax : maxCardsPerPage;

            if (current.length >= effectiveMax) {
                pages.push(current);
                current = [];
                currentHasLarge = false;
            }
            current.push(order);
            if (isLarge) {
                currentHasLarge = true;
            }
        }
        if (current.length > 0) {
            pages.push(current);
        }
        // An empty input still yields exactly one (empty) page, so
        // callers always have a valid "page 1 of 1" to render rather
        // than needing a separate zero-orders special case.
        if (pages.length === 0) {
            pages.push([]);
        }
        return pages;
    }

    /**
     * Full pagination pass: computes density from viewport width
     * (Adaptive - see the two-tier rule at the top of this file),
     * builds pages, and clamps the requested page number into the
     * valid range - the one function callers actually need.
     *
     * @param {Array} orders - already filtered, in stable order.
     * @param {number} viewportWidth
     * @param {number} requestedPage - 1-based; typically "the page the
     *   user/screen was already on" - clamped here rather than reset,
     *   so a realtime refresh that doesn't change the page count keeps
     *   the operator on the same page they were reading.
     * @returns {{pages: Array<Array>, totalPages: number, currentPage: number, currentPageOrders: Array, columns: number, rows: number}}
     */
    function paginate(orders, viewportWidth, requestedPage) {
        var density = computeDensity(viewportWidth);
        var pages = buildPages(orders, density.maxCardsPerPage);
        var totalPages = pages.length;
        var clampedPage = Math.min(Math.max(1, requestedPage || 1), totalPages);
        return {
            pages: pages,
            totalPages: totalPages,
            currentPage: clampedPage,
            currentPageOrders: pages[clampedPage - 1] || [],
            columns: density.columns,
            rows: density.rows,
        };
    }

    window.FlexSysPagination = {
        computeDensity: computeDensity,
        buildPages: buildPages,
        paginate: paginate,
        NORMAL_COLUMNS: NORMAL_COLUMNS,
        NORMAL_ROWS: NORMAL_ROWS,
        WIDE_COLUMNS: WIDE_COLUMNS,
        WIDE_ROWS: WIDE_ROWS,
        WIDE_MIN_VIEWPORT_WIDTH: WIDE_MIN_VIEWPORT_WIDTH,
        LARGE_ORDER_LINE_THRESHOLD: LARGE_ORDER_LINE_THRESHOLD,
    };
})();
