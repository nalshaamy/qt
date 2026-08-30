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
 * of being stretched to fill 3 wide ones. The approved COLUMN rule is:
 *   viewport width <  1600px -> 3 columns
 *   viewport width >= 1600px -> 4 columns
 * Never more than 4 columns at any width, however wide.
 *
 * ADAPTIVE HEIGHT-AWARE ROWS ("Adaptive Height-Aware Pagination -
 * Internal KDS + Public Kiosk"): SUPERSEDES the prior round's own
 * "always 2 rows, purely width-driven" assumption - a real Runtime
 * validation showed 6 orders on a wide-but-vertically-short viewport
 * still forced 2 rows (8/page at 4 columns), even though the actual
 * .fs-grid/.grid clientHeight available at that moment could not fit
 * two genuinely readable card rows - the second row was clipped/
 * overlapping the first. ROOT CAUSE: computeDensity() only ever
 * considered viewport WIDTH, never the real available vertical space
 * of the grid it was actually paginating for. Fixed by passing the
 * real, measured `.fs-grid`/`.grid` clientHeight in as a second
 * dimension - rows is now 2 ONLY when that real height can fit two
 * readable rows (see MIN_TWO_ROW_HEIGHT below, derived transparently
 * from this project's own already-approved card dimensions, never an
 * arbitrary guess), otherwise 1. Never shrinks card/text size to
 * preserve 2 rows - the row count itself adapts instead, per the
 * explicit "Never shrink cards/text merely to preserve two rows"
 * requirement.
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
    // Large/Full-HD-and-above density.
    var WIDE_COLUMNS = 4;
    // The single boundary between the two tiers - a viewport at or
    // above this width uses WIDE_*, below it uses NORMAL_*. Matches a
    // typical Full HD (1920px) display's own usable width comfortably,
    // while still applying to some smaller-but-still-wide desktop
    // displays right at the boundary, per the explicit worked
    // examples (1599px -> 3 columns, 1600px -> 4 columns).
    var WIDE_MIN_VIEWPORT_WIDTH = 1600;

    // ADAPTIVE HEIGHT-AWARE ROWS: the minimum genuinely readable
    // height for TWO card rows, derived transparently from this
    // project's own real, current CSS - a full accounting of every
    // element a normal commercial card actually renders (both
    // screens share the same visual dimensions here -
    // static/src/scss/kds_style.scss's own .fs-card-head/.fs-
    // line-item/.fs-card-footer and controllers/kds_kiosk.py's own
    // matching .card-head/.line-item/.card-footer rules), NOT an
    // arbitrary blind guess, per the explicit requirement.
    //
    // ADAPTIVE PAGINATION REVIEW ("Adaptive Pagination Review -
    // Correct Readable Row Height + Card Safety"): confirmed by
    // static review - the earlier 174px-per-card figure only counted
    // an order number plus one bare product line plus a footer,
    // omitting several elements every normal card's own header
    // actually renders (order reference, status row, chips row,
    // employee row) and the variant/note rows a normal commercial
    // order's own line item typically has. A full accounting below
    // (every one of THOSE elements' own real padding/margin/font
    // metrics, not just a header/line/footer skeleton) comes to
    // ~299px per card, confirming the reviewed, CSS-justified
    // MIN_READABLE_ROW_HEIGHT of 300px - not the earlier, too-low
    // 174px:
    //   header: 16px*2 padding (32) + order-number's own 26px
    //     line-height:1 text (26) + ordered-ref's own 4px margin-top
    //     + ~14px text (18) + status-blink's own 10px margin-top +
    //     ~15px text (25) + chips-row's own 12px margin-top + one
    //     chip's own 6px*2 padding + ~14px text (38) + employee-row's
    //     own 10px margin-top + ~15px text (25) = ~164px
    //   one body line (product + variant + note): 13px*2 padding
    //     (26) + the title row's own ~18-20px (title text and/or a
    //     variant pill) + the note row's own 4px margin-top +
    //     ~15px text (19) = ~65px
    //   footer: 14px*2 padding (28) + the action button's own height
    //     (~42px) = ~70px
    //   164 + 65 + 70 = ~299px, rounded to the clean, safe 300px this
    //   project now uses.
    var MIN_READABLE_ROW_HEIGHT = 300;
    // Matches .fs-grid/.grid's own gap:24px exactly - the real space
    // consumed between two stacked rows in this project's own grid,
    // not an assumption.
    var GRID_ROW_GAP = 24;
    var MIN_TWO_ROW_HEIGHT = (MIN_READABLE_ROW_HEIGHT * 2) + GRID_ROW_GAP;

    // A card is considered "unusually large" past this many product
    // lines - a page containing one is given a reduced effective
    // capacity (rather than forcing every card on that page to
    // compress to illegibility to fit the normal count). This applies
    // on top of whichever density is active - it never itself raises
    // the count past that density's own maxCardsPerPage.
    var LARGE_ORDER_LINE_THRESHOLD = 8;

    /**
     * @param {number} viewportWidth
     * @param {number} [availableGridHeight] - the real, measured
     *   clientHeight (in px) of the actual `.fs-grid`/`.grid` element
     *   currently being paginated for - NOT window.innerHeight, which
     *   includes the header/filters/pagination framing this grid does
     *   not itself occupy (see this file's own top-of-file comment).
     *   If omitted/not a positive number (a caller that hasn't been
     *   updated to measure and pass it yet), rows defaults to 2 - the
     *   same behavior this function always had before height-
     *   awareness existed, so an as-yet-unupdated caller never
     *   silently loses capacity it didn't ask to lose.
     * @returns {{columns: number, rows: number, maxCardsPerPage: number}}
     */
    function computeDensity(viewportWidth, availableGridHeight) {
        var columns = viewportWidth >= WIDE_MIN_VIEWPORT_WIDTH ? WIDE_COLUMNS : NORMAL_COLUMNS;
        var rows;
        if (typeof availableGridHeight === "number" && availableGridHeight > 0) {
            rows = availableGridHeight >= MIN_TWO_ROW_HEIGHT ? 2 : 1;
        } else {
            rows = 2;
        }
        return { columns: columns, rows: rows, maxCardsPerPage: columns * rows };
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
     * Full pagination pass: computes density from viewport width AND
     * the real available grid height (Adaptive Height-Aware Rows -
     * see the file-level comment above), builds pages, and clamps the
     * requested page number into the valid range - the one function
     * callers actually need.
     *
     * @param {Array} orders - already filtered, in stable order.
     * @param {number} viewportWidth
     * @param {number} [availableGridHeight] - see computeDensity's own
     *   doc comment above for exactly what this must be (the grid
     *   element's own real clientHeight, not window.innerHeight).
     * @param {number} requestedPage - 1-based; typically "the page the
     *   user/screen was already on" - clamped here rather than reset,
     *   so a realtime refresh that doesn't change the page count keeps
     *   the operator on the same page they were reading.
     * @returns {{pages: Array<Array>, totalPages: number, currentPage: number, currentPageOrders: Array, columns: number, rows: number, currentPageRows: number}}
     */
    function paginate(orders, viewportWidth, availableGridHeight, requestedPage) {
        var density = computeDensity(viewportWidth, availableGridHeight);
        var pages = buildPages(orders, density.maxCardsPerPage);
        var totalPages = pages.length;
        var clampedPage = Math.min(Math.max(1, requestedPage || 1), totalPages);
        var currentPageOrders = pages[clampedPage - 1] || [];
        // GRID ROWS: the actual row count the CURRENT page's own order
        // count needs - never the density tier's own maximum (rows
        // above) if the current page happens to hold fewer orders than
        // a full page would. A caller uses this for an explicit
        // grid-template-rows, so an implicit auto-sized empty second
        // row is never reserved on a page that only has one row's
        // worth of orders.
        var currentPageRows = currentPageOrders.length > 0
            ? Math.ceil(currentPageOrders.length / density.columns)
            : 0;
        return {
            pages: pages,
            totalPages: totalPages,
            currentPage: clampedPage,
            currentPageOrders: currentPageOrders,
            columns: density.columns,
            rows: density.rows,
            currentPageRows: currentPageRows,
        };
    }

    window.FlexSysPagination = {
        computeDensity: computeDensity,
        buildPages: buildPages,
        paginate: paginate,
        NORMAL_COLUMNS: NORMAL_COLUMNS,
        WIDE_COLUMNS: WIDE_COLUMNS,
        WIDE_MIN_VIEWPORT_WIDTH: WIDE_MIN_VIEWPORT_WIDTH,
        LARGE_ORDER_LINE_THRESHOLD: LARGE_ORDER_LINE_THRESHOLD,
        MIN_TWO_ROW_HEIGHT: MIN_TWO_ROW_HEIGHT,
        MIN_READABLE_ROW_HEIGHT: MIN_READABLE_ROW_HEIGHT,
        GRID_ROW_GAP: GRID_ROW_GAP,
    };
})();
