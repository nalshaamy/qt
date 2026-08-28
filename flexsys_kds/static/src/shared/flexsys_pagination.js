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

    // Normal Full-HD reference layout: 3 x 2 = 6 cards/page.
    var NORMAL_COLUMNS = 3;
    var NORMAL_ROWS = 2;
    // Compact/Fullscreen: 4 x 2 = 8 cards/page - the approved
    // "High Density Pagination Requirement" layout for wide/fullscreen
    // viewports.
    var COMPACT_COLUMNS = 4;
    var COMPACT_ROWS = 2;
    // A viewport at or above this width is treated as wide enough for
    // the compact 4-column layout - matches a typical Full HD (1920px)
    // display's own usable width once fullscreen chrome/sidebars are
    // accounted for, not a guess tied to the word "fullscreen" alone
    // (per the explicit "don't rely on the word Fullscreen; use
    // viewport width too" requirement).
    var COMPACT_MIN_VIEWPORT_WIDTH = 1600;

    // A card is considered "unusually large" past this many product
    // lines - a page containing one is given a reduced effective
    // capacity (rather than forcing every card on that page to
    // compress to illegibility to fit the normal count).
    var LARGE_ORDER_LINE_THRESHOLD = 8;

    /**
     * @param {number} viewportWidth
     * @returns {{columns: number, rows: number, maxCardsPerPage: number}}
     */
    function computeDensity(viewportWidth) {
        if (viewportWidth >= COMPACT_MIN_VIEWPORT_WIDTH) {
            return {
                columns: COMPACT_COLUMNS,
                rows: COMPACT_ROWS,
                maxCardsPerPage: COMPACT_COLUMNS * COMPACT_ROWS,
            };
        }
        return {
            columns: NORMAL_COLUMNS,
            rows: NORMAL_ROWS,
            maxCardsPerPage: NORMAL_COLUMNS * NORMAL_ROWS,
        };
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
     * Full pagination pass: computes density from viewport width,
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
        COMPACT_COLUMNS: COMPACT_COLUMNS,
        COMPACT_ROWS: COMPACT_ROWS,
        COMPACT_MIN_VIEWPORT_WIDTH: COMPACT_MIN_VIEWPORT_WIDTH,
        LARGE_ORDER_LINE_THRESHOLD: LARGE_ORDER_LINE_THRESHOLD,
    };
})();
