/**
 * FlexSys KDS - Shared Kitchen Ticket Renderer (Production)
 *
 * "FlexSys Ticket Renderer" - the ONE shared file both the Internal
 * KDS adapter (loaded via 'web.assets_backend', a plain non-module
 * script sitting alongside that bundle's own ES modules) and the
 * Public Kiosk adapter (loaded via a plain <script src="..."> tag)
 * both load and call identically - the architectural guarantee that
 * "Same Order Data -> Same FlexSys Ticket Layout" actually holds.
 *
 * ARCHITECTURAL SHIFT FROM THE PRIOR ROUND: Odoo's own real Epson
 * printing path does not send ePOS-Print <text> elements at all - it
 * draws the receipt to an offscreen <canvas> (browser text
 * rendering - real font shaping, real Arabic/RTL, real wrapping),
 * converts that canvas to a monochrome raster bitmap using
 * Floyd-Steinberg error-diffusion dithering (matching Odoo's own
 * EpsonPrinter.canvasToRaster() approach, not a flat per-pixel
 * threshold), and sends that as a base64 ePOS-Print <image> element.
 * This file reimplements that same Canvas -> Dither -> Raster ->
 * <image> pipeline as FlexSys's own isolated code - NOT a copy of
 * Odoo's own EpsonPrinter/BasePrinter classes, which this file has no
 * dependency on at all.
 *
 * Deliberately does NOT touch Direct ePOS Transport (endpoint, LNA,
 * timeout, response parsing, station IP flow) - this file only
 * produces the XML STRING each adapter already passes as `body: xml`
 * to its own unchanged fetch() call. buildKitchenTicketXml() is kept
 * as the same function name both adapters already call, so NEITHER
 * adapter file needed any change this round - it now internally runs
 * the full Canvas pipeline instead of building <text> XML directly.
 *
 * Exposes:
 *   window.FlexSysTicketBuilder.normalizeOrderForTicket(rawOrder, stationName, ticketStatus, branchName)
 *   window.FlexSysTicketBuilder.renderKitchenTicketToCanvas(normalizedOrder)
 *   window.FlexSysTicketBuilder.canvasToRaster(canvas)
 *   window.FlexSysTicketBuilder.encodeRaster(rasterBytes)
 *   window.FlexSysTicketBuilder.buildRasterEposXml(normalizedOrder)
 *   window.FlexSysTicketBuilder.buildKitchenTicketXml(normalizedOrder)  // = buildRasterEposXml, same name adapters already call
 */
(function () {
    "use strict";

    // 576px = 80mm printable width at 203 DPI - the standard,
    // widely-documented resolution/width pairing for 80mm thermal
    // receipt printers (including Epson's own TM-series), and
    // therefore the correct target raster width for the <image>
    // element's own `width` attribute.
    var CANVAS_WIDTH = 576;
    var MARGIN = 16;
    var CONTENT_WIDTH = CANVAS_WIDTH - MARGIN * 2;

    var FONT_FAMILY = "Tahoma, Arial, sans-serif";
    var ARABIC_RE = /[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]/;

    function isArabicText(s) {
        return ARABIC_RE.test(String(s || ""));
    }

    // ---------------------------------------------------------------
    // Normalization
    // ---------------------------------------------------------------

    /**
     * @param {object} rawOrder - the SAME order object shape already
     *   held by both screens locally (this.state.orders on Internal
     *   KDS, the ORDERS array on Public Kiosk) - id, name,
     *   pos_reference, table_label, created_time, order_type_label,
     *   lines: [{product_name, qty, variant_info, note, state,
     *   line_change}]. Confirmed identical field names in both
     *   contexts by reading kds_templates.xml/kds_order_card.js and
     *   controllers/kds_kiosk.py's own kiosk_orders() response before
     *   writing this.
     * @param {string} stationName
     * @param {string} ticketStatus - 'NEW' | 'ADDED' | 'UPDATED' |
     *   'CANCELLED' | 'REPRINT' (printed exactly as given, never
     *   translated here). NOT hardcoded by this function - the real
     *   caller decides; this round's own test uses 'NEW' for the
     *   actual print action being tested (a real first print), with
     *   'REPRINT' reserved for when a genuine reprint lifecycle
     *   (Direct Printing <-> kds.print.job integration, a later
     *   Baseline phase) determines it.
     * @param {string} [branchName] - passed in explicitly by the
     *   caller (each integration file's own comment explains its own
     *   source - both now resolve it from the station's own
     *   company_id, per the Internal/Public parity fix).
     * @param {function(object): boolean} [lineFilter] - optional;
     *   defaults to "exclude cancelled lines", correct for a NEW
     *   ticket, but NOT hardcoded as the only possible behavior - a
     *   future CANCELLED ticket (or any other status needing
     *   different line selection) can pass its own filter instead of
     *   this function ever being changed again.
     * @returns {object} normalized ticket data
     */
    function normalizeOrderForTicket(rawOrder, stationName, ticketStatus, branchName, lineFilter) {
        var filterFn =
            typeof lineFilter === "function"
                ? lineFilter
                : function (l) {
                      return l.state !== "cancelled";
                  };

        // Lines are passed through exactly as received, in order,
        // with NO merging of same-named lines - two separate lines
        // that happen to share a product name print as two separate
        // lines. They may differ in history/modifiers/delta even when
        // the visible name matches, and there is no explicit contract
        // yet for when merging would be correct - this is a
        // deliberate pass-through, not an oversight.
        var lines = (rawOrder.lines || []).filter(filterFn).map(function (l) {
            return {
                qty: l.qty,
                productName: l.product_name || "",
                modifiers: l.variant_info ? [l.variant_info] : [],
                note: l.note || "",
                lineChange: l.line_change || "none",
                qtyDelta: l.qty_delta || 0,
            };
        });

        var orderTime = "";
        if (rawOrder.created_time) {
            // FIX (CR-07, "Use 24-Hour Time"): explicit hour12:false -
            // the prior round's own default-locale format produced
            // AM/PM (and, combined with RTL paragraph context on the
            // printed page, an Arabic "م" glyph appearing in an
            // unstable position next to the Latin "Time:" label).
            // 24-hour format has no AM/PM marker at all, sidestepping
            // that RTL/LTR mixing problem entirely, not just
            // formatting it differently.
            orderTime = new Date(rawOrder.created_time).toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
                hour12: false,
            });
        }

        return {
            // FIX: the big number on the printed ticket must match the
            // big number the kitchen worker actually sees on the KDS
            // card - confirmed from kds_templates.xml directly:
            // <div class="fs-order-number" t-esc="props.order.pos_reference or props.order.name"/>
            // - not order.name alone (that field is the smaller,
            // secondary reference shown next to it on the card, e.g.
            // "#KDS/26/0010" - never the card's own main heading).
            orderNumber: rawOrder.pos_reference || rawOrder.name || String(rawOrder.id || ""),
            ticketStatus: ticketStatus || "NEW",
            stationName: stationName || "",
            orderTypeLabel: rawOrder.order_type_label || rawOrder.order_type || "",
            branchName: branchName || "",
            // Table/Floor - printed only when present (no blank line
            // otherwise), same source as the card's own display.
            tableLabel: rawOrder.table_label || "",
            orderTime: orderTime,
            // Kept available in the normalized payload per the
            // explicit direction ("احتفظ به كحقل اختياري... لا نحتاج
            // طباعته في هذه الجولة") - present in the data model, not
            // drawn by the renderer below.
            employeeName: rawOrder.employee_name || "",
            lines: lines,
        };
    }

    // ---------------------------------------------------------------
    // Canvas rendering
    // ---------------------------------------------------------------

    /**
     * Word-wraps `text` (space-separated tokens - works structurally
     * for both Latin and Arabic text, which is also space-separated
     * between words) to fit within `maxWidth` at the ctx's own
     * CURRENTLY-SET font, returning an array of line strings. Uses
     * real ctx.measureText() - actual browser font metrics, not a
     * fixed character-count guess.
     */
    function wrapText(ctx, text, maxWidth) {
        var words = String(text).split(/\s+/).filter(Boolean);
        if (!words.length) return [""];
        var lines = [];
        var current = words[0];
        for (var i = 1; i < words.length; i++) {
            var candidate = current + " " + words[i];
            if (ctx.measureText(candidate).width <= maxWidth) {
                current = candidate;
            } else {
                lines.push(current);
                current = words[i];
            }
        }
        lines.push(current);
        return lines;
    }

    /**
     * Draws one logical ticket line (with automatic wrapping and
     * automatic RTL/LTR text shaping per the text's own script),
     * advancing and returning the new cursor y.
     *
     * FIX (CR-03/CR-04/CR-05, "Product Alignment for Arabic / Mixed
     * Text"): a left-aligned line now ALWAYS anchors its own left
     * edge at the same fixed x position (margin + indent) regardless
     * of the text's own script - it no longer switches to a
     * right-edge anchor for Arabic text. ctx.direction still controls
     * correct internal RTL shaping/character-ordering (including
     * genuinely mixed Arabic/English content within one line), but
     * textAlign/anchor point is now independent of that - this is
     * standard, well-supported Canvas 2D behavior (direction affects
     * shaping only, textAlign affects only which edge anchors to x).
     * The prior right-edge-anchor-for-RTL behavior was the actual
     * cause of short Arabic lines appearing to "float centered" far
     * from the qty prefix/indent column instead of sitting directly
     * in it, per the explicit visual complaint this fixes.
     */
    function drawTextBlock(ctx, text, y, opts) {
        opts = opts || {};
        var size = opts.size || 24;
        var bold = opts.bold ? "bold " : "";
        var align = opts.align || "left";
        var indent = opts.indent || 0;
        var lineHeight = opts.lineHeight || Math.round(size * 1.35);

        ctx.font = bold + size + "px " + FONT_FAMILY;
        ctx.direction = isArabicText(text) ? "rtl" : "ltr";

        var maxWidth = CONTENT_WIDTH - indent;
        var wrapped = wrapText(ctx, text, maxWidth);

        for (var i = 0; i < wrapped.length; i++) {
            var x;
            if (align === "center") {
                ctx.textAlign = "center";
                x = CANVAS_WIDTH / 2;
            } else if (align === "right") {
                ctx.textAlign = "right";
                x = CANVAS_WIDTH - MARGIN;
            } else {
                // Always left-anchored now, for both LTR and RTL text.
                ctx.textAlign = "left";
                x = MARGIN + indent;
            }
            ctx.fillText(wrapped[i], x, y);
            y += lineHeight;
        }
        return y;
    }

    function drawDivider(ctx, y) {
        ctx.fillRect(MARGIN, y, CONTENT_WIDTH, 2);
        return y + 2;
    }

    /**
     * Draws the Ticket Status Header with a distinct visual weight per
     * status - the "Style Contract" requested: NEW is clear but not an
     * overstated warning; ADDED is clearly emphasized (bold + an
     * outline box, a real but lighter-weight distinction than a full
     * reverse fill); UPDATED is clearly bold/larger than NEW; REPRINT
     * is full reverse-video (unmistakably not a new order); CANCELLED
     * is the strongest visual warning of all (reverse-video, larger
     * still than REPRINT). No print lifecycle logic lives here - this
     * only renders whatever ticketStatus string it is given.
     */
    function drawStatusHeader(ctx, order, y) {
        var status = order.ticketStatus;
        var statusText = status === "NEW" ? "NEW" : "*** " + status + " ***";

        if (status === "REPRINT" || status === "CANCELLED") {
            var size = status === "CANCELLED" ? 38 : 34;
            ctx.font = "bold " + size + "px " + FONT_FAMILY;
            var barHeight = size + 16;
            ctx.fillStyle = "#000000";
            ctx.fillRect(MARGIN, y - size + 4, CONTENT_WIDTH, barHeight);
            ctx.fillStyle = "#ffffff";
            ctx.direction = "ltr";
            ctx.textAlign = "center";
            ctx.fillText(statusText, CANVAS_WIDTH / 2, y + 10);
            ctx.fillStyle = "#000000";
            return y + barHeight + 10;
        }

        if (status === "ADDED") {
            var addedSize = 32;
            ctx.font = "bold " + addedSize + "px " + FONT_FAMILY;
            ctx.direction = "ltr";
            ctx.textAlign = "center";
            var textWidth = ctx.measureText(statusText).width;
            var boxHeight = addedSize + 16;
            var boxWidth = textWidth + 30;
            var boxX = CANVAS_WIDTH / 2 - boxWidth / 2;
            var boxY = y - addedSize + 2;
            // Outline box (not filled) - a real but lighter-weight
            // emphasis than REPRINT/CANCELLED's own full reverse fill.
            ctx.lineWidth = 3;
            ctx.strokeStyle = "#000000";
            ctx.strokeRect(boxX, boxY, boxWidth, boxHeight);
            ctx.fillStyle = "#000000";
            ctx.fillText(statusText, CANVAS_WIDTH / 2, y + 10);
            return y + boxHeight + 12;
        }

        // NEW and UPDATED: plain bold text, UPDATED one size larger
        // than NEW as its own distinguishing weight.
        var plainSize = status === "UPDATED" ? 32 : 28;
        var newY = drawTextBlock(ctx, statusText, y, {
            size: plainSize,
            bold: true,
            align: "center",
            lineHeight: plainSize + 10,
        });
        return newY + 6;
    }

    /**
     * Draws the qty-prominent product line: a bold "Nx" prefix and the
     * product name on the same visual line, wrapping the name alone
     * if it's long (the qty prefix itself never wraps).
     *
     * FIX (CR-03, "Product Alignment for Arabic / Mixed Text"): the
     * product name now ALWAYS starts immediately after the qty
     * prefix (left-anchored at that fixed x), for both English and
     * Arabic/mixed names - it no longer floats to the far right edge
     * for Arabic text, which was the actual cause of the "centered"
     * look the client's own example showed. ctx.direction is still
     * set from the text's own script so genuinely mixed
     * Arabic/English content (e.g. "TUNA - ساندوتش تونه SANDWICH")
     * shapes/orders correctly via the browser's own real bidi
     * handling - only the anchor point changed, not the shaping.
     */
    function drawProductLine(ctx, qty, productName, y, size) {
        var qtyText = qty + "x";
        ctx.font = "bold " + size + "px " + FONT_FAMILY;
        ctx.direction = "ltr";
        ctx.textAlign = "left";
        ctx.fillText(qtyText, MARGIN, y);
        var qtyWidth = ctx.measureText(qtyText).width + 10;

        var nameSize = size;
        ctx.font = "bold " + nameSize + "px " + FONT_FAMILY;
        var nameDirection = isArabicText(productName) ? "rtl" : "ltr";
        ctx.direction = nameDirection;
        ctx.textAlign = "left";
        var nameMaxWidth = CONTENT_WIDTH - qtyWidth;
        var wrapped = wrapText(ctx, productName, nameMaxWidth);
        var lineHeight = Math.round(nameSize * 1.35);
        var lineY = y;
        for (var i = 0; i < wrapped.length; i++) {
            ctx.fillText(wrapped[i], MARGIN + qtyWidth, lineY);
            lineY += lineHeight;
        }
        return lineY;
    }

    /**
     * Draws a distinct, clearer-than-a-modifier Note line: a bold
     * "NOTE:"/"ملاحظة:" label (chosen by the note's OWN script, not a
     * fixed language) immediately followed by the wrapped note text
     * at normal weight - same one-line-then-wrap technique as
     * drawProductLine's own qty prefix, so the label never gets
     * separated from the start of the note text it belongs to.
     *
     * FIX (CR-05): the note text now always starts immediately after
     * the label (left-anchored), for both English and Arabic notes -
     * same anchor-point fix as drawProductLine above, for the same
     * reason.
     */
    function drawNoteLine(ctx, noteText, y, size, indent) {
        var isArabicNote = isArabicText(noteText);
        var label = isArabicNote ? "ملاحظة: " : "NOTE: ";

        ctx.font = "bold " + size + "px " + FONT_FAMILY;
        ctx.direction = "ltr";
        ctx.textAlign = "left";
        ctx.fillText(label, MARGIN + indent, y);
        var labelWidth = ctx.measureText(label).width;

        ctx.font = size + "px " + FONT_FAMILY;
        var noteDirection = isArabicNote ? "rtl" : "ltr";
        ctx.direction = noteDirection;
        ctx.textAlign = "left";
        var maxWidth = CONTENT_WIDTH - indent - labelWidth;
        var wrapped = wrapText(ctx, noteText, maxWidth);
        var lineHeight = Math.round(size * 1.35);
        var lineY = y;
        for (var i = 0; i < wrapped.length; i++) {
            ctx.fillText(wrapped[i], MARGIN + indent + labelWidth, lineY);
            lineY += lineHeight;
        }
        return lineY;
    }

    /**
     * Draws a "Label: Value" footer-style line as ONE continuous,
     * left-anchored, correctly-shaped run - fixing CR-08 ("Table /
     * Floor RTL"): the label and value are now treated as structured
     * fields drawn with the same one-line-then-wrap technique as
     * drawNoteLine above (bold label, then value immediately
     * following, left-anchored throughout), instead of naively
     * concatenating "Label: " + value into one string and letting the
     * browser's own bidi algorithm guess the paragraph direction of
     * the combined result - which is what previously produced
     * unstable/reversed-looking ordering for an Arabic value after an
     * English label (e.g. "Table: <Arabic branch/table text>").
     */
    function drawLabelValueLine(ctx, label, value, y, size) {
        ctx.font = "bold " + size + "px " + FONT_FAMILY;
        ctx.direction = "ltr";
        ctx.textAlign = "left";
        ctx.fillText(label, MARGIN, y);
        var labelWidth = ctx.measureText(label).width;

        ctx.font = size + "px " + FONT_FAMILY;
        var valueDirection = isArabicText(value) ? "rtl" : "ltr";
        ctx.direction = valueDirection;
        ctx.textAlign = "left";
        var maxWidth = CONTENT_WIDTH - labelWidth;
        var wrapped = wrapText(ctx, value, maxWidth);
        var lineHeight = Math.round(size * 1.35);
        var lineY = y;
        for (var i = 0; i < wrapped.length; i++) {
            ctx.fillText(wrapped[i], MARGIN + labelWidth, lineY);
            lineY += lineHeight;
        }
        return lineY;
    }

    /**
     * Renders the full ticket to an offscreen canvas, sized exactly
     * to its own real content height (a first, generously-tall
     * measuring pass draws everything and tracks the cursor; a second
     * pass draws onto a canvas cropped to that exact final height, so
     * the printed ticket has no wasted blank paper and nothing is
     * ever clipped).
     * @param {object} order - output of normalizeOrderForTicket()
     * @returns {HTMLCanvasElement}
     */
    function renderKitchenTicketToCanvas(order) {
        function paint(ctx) {
            ctx.fillStyle = "#ffffff";
            ctx.fillRect(0, 0, CANVAS_WIDTH, ctx.canvas.height);
            ctx.fillStyle = "#000000";

            var y = 30;

            // --- Header hierarchy fix: branch name bigger/bolder
            // (closer to Odoo's own weight), a small "ORDER" label,
            // then the operational order number as the single
            // strongest visual element on the whole ticket, with
            // Status immediately beneath it - matching the requested
            // eye path "Order Number -> Status" exactly.
            if (order.branchName) {
                y = drawTextBlock(ctx, order.branchName, y, {
                    size: 28,
                    bold: true,
                    align: "center",
                });
                y += 8;
            }

            y = drawTextBlock(ctx, "ORDER", y, {
                size: 20,
                align: "center",
                lineHeight: 24,
            });
            // FIX (CR-01, "Header Spacing / ORDER Overlap"): the prior
            // round's own small "+2" gap did not account for the big
            // order-number font's own real ascent - fillText's own y
            // is the text BASELINE, and a 56px bold digit's own
            // ascent reaches roughly 40+ px ABOVE that baseline,
            // meaning the big number's own top edge was landing
            // above/into "ORDER"'s own descender, producing the
            // reported overlap. Measured here with the browser's own
            // real actualBoundingBoxAscent (not a fixed guess) for
            // the exact order-number text about to be drawn, so the
            // gap is always genuinely sufficient regardless of font
            // rendering specifics.
            var bigNumberSize = 56;
            ctx.font = "bold " + bigNumberSize + "px " + FONT_FAMILY;
            var numberMetrics = ctx.measureText(String(order.orderNumber));
            var numberAscent =
                numberMetrics.actualBoundingBoxAscent != null
                    ? numberMetrics.actualBoundingBoxAscent
                    : bigNumberSize * 0.8;
            y += Math.ceil(numberAscent) + 12;
            y = drawTextBlock(ctx, String(order.orderNumber), y, {
                size: bigNumberSize,
                bold: true,
                align: "center",
                lineHeight: 60,
            });
            y += 10;

            y = drawStatusHeader(ctx, order, y);

            y = drawDivider(ctx, y);
            // FIX: the first product used to visually touch the
            // divider above it on the real printed paper - the prior
            // round's own +18 was not enough real visual clearance at
            // this font size, since fillText's own y coordinate is
            // the text BASELINE, not its top edge, so a chunk of that
            // 18px was already consumed by the character's own
            // ascent. Increased to give a genuinely visible gap on
            // paper - applies identically regardless of ticketStatus
            // (NEW/REPRINT/ADDED/UPDATED/CANCELLED all share this same
            // spacing, per the explicit requirement).
            y += 30;

            for (var i = 0; i < order.lines.length; i++) {
                var line = order.lines[i];
                y = drawProductLine(ctx, line.qty, line.productName, y, 30) + 6;

                for (var m = 0; m < line.modifiers.length; m++) {
                    // Modifiers enlarged (20 -> 24) per the explicit
                    // "readability" feedback - still visibly lighter
                    // than the bold product line above it (normal
                    // weight, not bold), just no longer too faint to
                    // read comfortably.
                    y = drawTextBlock(ctx, line.modifiers[m], y, {
                        size: 24,
                        align: "left",
                        indent: 28,
                    });
                }
                if (line.note) {
                    // Notes get their own distinct, bolder label
                    // ("NOTE:"/"ملاحظة:" - printed exactly as given in
                    // the note text if it already carries an Arabic
                    // label, otherwise prefixed here) so a note never
                    // gets lost among modifiers, per the explicit
                    // "clearer than a normal modifier" requirement.
                    // Drawn as two runs (bold label, normal wrapped
                    // text) using the same on-one-line-then-wrap
                    // technique as the product line's own qty prefix.
                    y = drawNoteLine(ctx, line.note, y, 24, 28);
                }
                y += 16;
            }

            y = drawDivider(ctx, y);
            y += 18;

            // --- Footer: vertical, one field per line (CR-06),
            // enlarged for readability, Table/Floor and Order Time
            // added when present (never a blank line when absent).
            // FIX (CR-08, "Table / Floor RTL"): Station/Order Type/
            // Table/Time are now drawn via drawLabelValueLine() -
            // label and value as one structured, left-anchored run
            // (same technique as Notes above) - instead of naively
            // concatenating "Label: " + value into a single string
            // and letting the browser guess the combined paragraph's
            // own bidi direction, which is what produced the unstable
            // ordering for an Arabic Table value after the English
            // "Table:" label. Employee/cashier name deliberately NOT
            // printed this round, per the explicit direction - it
            // remains available in the normalized payload only.
            if (order.stationName) {
                y = drawLabelValueLine(ctx, "Station: ", order.stationName, y, 26);
            }
            if (order.orderTypeLabel) {
                y = drawLabelValueLine(ctx, "Order Type: ", order.orderTypeLabel, y, 26);
            }
            if (order.tableLabel) {
                y = drawLabelValueLine(ctx, "Table: ", order.tableLabel, y, 26);
            }
            if (order.orderTime) {
                y = drawLabelValueLine(ctx, "Time: ", order.orderTime, y, 26);
            }
            // FIX (CR-10, "Remove FLEX KDS Footer Branding"): removed
            // entirely - no operational value, and its own line was
            // part of the excess bottom white space.
            // FIX (CR-11, "Reduce Bottom White Space"): short, fixed
            // gap only before the cut - enough to clear the last
            // footer line's own descenders, no more.
            y += 14;

            return y;
        }

        // Pass 1: measure. A tall scratch canvas exists purely so
        // ctx.measureText()/wrapText() above have a real 2D context to
        // call - its own height is irrelevant since nothing drawn on
        // it is kept.
        var measure = document.createElement("canvas");
        measure.width = CANVAS_WIDTH;
        measure.height = 4000;
        var measureCtx = measure.getContext("2d");
        var contentHeight = paint(measureCtx);

        // Pass 2: real draw, on a canvas cropped to the exact content
        // height measured above.
        var finalCanvas = document.createElement("canvas");
        finalCanvas.width = CANVAS_WIDTH;
        finalCanvas.height = Math.ceil(contentHeight);
        var finalCtx = finalCanvas.getContext("2d");
        paint(finalCtx);

        return finalCanvas;
    }

    // ---------------------------------------------------------------
    // Canvas -> monochrome raster -> base64 -> ePOS <image>
    // ---------------------------------------------------------------

    /**
     * Converts a canvas to a packed 1-bit-per-pixel monochrome raster
     * (the standard ESC/POS-style raster format ePOS-Print's own
     * <image> element expects: row-major, MSB-first, 1 = print/black,
     * 0 = blank/white, width padded up to a multiple of 8 so each row
     * packs into a whole number of bytes).
     *
     * CORRECTED to use Floyd-Steinberg error-diffusion dithering
     * before thresholding, matching Odoo's own
     * EpsonPrinter.canvasToRaster() approach, rather than a plain
     * per-pixel cutoff - error diffusion preserves perceived detail
     * (anti-aliased text edges, thin strokes) far better on a 1-bit
     * target than a flat threshold does, which is the actual quality
     * difference this fixes.
     * @param {HTMLCanvasElement} canvas
     * @returns {{bytes: Uint8Array, width: number, height: number}}
     */
    function canvasToRaster(canvas) {
        var width = canvas.width;
        var height = canvas.height;
        var paddedWidth = Math.ceil(width / 8) * 8;
        var bytesPerRow = paddedWidth / 8;

        var ctx = canvas.getContext("2d");
        var imageData = ctx.getImageData(0, 0, width, height).data;

        // Working grayscale buffer, one float per pixel, mutable in
        // place as error is diffused forward - kept separate from the
        // source imageData (a Uint8ClampedArray, which would clamp
        // and lose precision on every accumulated write) so the
        // diffusion itself is numerically accurate row after row.
        var gray = new Float32Array(width * height);
        for (var yy0 = 0; yy0 < height; yy0++) {
            for (var xx0 = 0; xx0 < width; xx0++) {
                var idx0 = (yy0 * width + xx0) * 4;
                var r0 = imageData[idx0];
                var g0 = imageData[idx0 + 1];
                var b0 = imageData[idx0 + 2];
                var a0 = imageData[idx0 + 3];
                // Fully transparent pixels are treated as white
                // (never printed), same as before this fix.
                gray[yy0 * width + xx0] =
                    a0 === 0 ? 255 : 0.299 * r0 + 0.587 * g0 + 0.114 * b0;
            }
        }

        var raster = new Uint8Array(bytesPerRow * height);

        for (var yy = 0; yy < height; yy++) {
            for (var xx = 0; xx < width; xx++) {
                var i = yy * width + xx;
                var oldPixel = gray[i];
                var newPixel = oldPixel < 128 ? 0 : 255;
                var error = oldPixel - newPixel;

                if (newPixel === 0) {
                    var byteIndex = yy * bytesPerRow + (xx >> 3);
                    var bitIndex = 7 - (xx % 8);
                    raster[byteIndex] |= 1 << bitIndex;
                }

                // Floyd-Steinberg error diffusion to the four
                // neighboring not-yet-processed pixels, each bounds-
                // checked individually since edge/corner pixels are
                // missing one or more neighbors.
                if (xx + 1 < width) {
                    gray[i + 1] += error * (7 / 16);
                }
                if (yy + 1 < height) {
                    if (xx - 1 >= 0) {
                        gray[i - 1 + width] += error * (3 / 16);
                    }
                    gray[i + width] += error * (5 / 16);
                    if (xx + 1 < width) {
                        gray[i + 1 + width] += error * (1 / 16);
                    }
                }
            }
        }

        return { bytes: raster, width: paddedWidth, height: height };
    }

    /**
     * Base64-encodes raw bytes, chunked to avoid a call-stack overflow
     * from spreading a very large Uint8Array through
     * String.fromCharCode at once (a well-known real limitation of
     * that naive one-shot pattern for large images).
     */
    function encodeRaster(bytes) {
        var CHUNK = 8192;
        var binary = "";
        for (var i = 0; i < bytes.length; i += CHUNK) {
            var slice = bytes.subarray(i, i + CHUNK);
            binary += String.fromCharCode.apply(null, slice);
        }
        return btoa(binary);
    }

    /**
     * @param {object} order - output of normalizeOrderForTicket()
     * @returns {string} the full SOAP-enveloped ePOS-Print XML with a
     *   raster <image> element, ready to pass directly as `body:` to
     *   either adapter's own unchanged fetch() call.
     */
    function buildRasterEposXml(order) {
        var canvas = renderKitchenTicketToCanvas(order);
        var raster = canvasToRaster(canvas);
        var base64 = encodeRaster(raster.bytes);

        return (
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">\n' +
            "    <s:Body>\n" +
            '        <epos-print xmlns="http://www.epson-pos.com/schemas/2011/03/epos-print">\n' +
            '            <image width="' +
            raster.width +
            '" height="' +
            raster.height +
            '" align="center" color="color_1" mode="mono">' +
            base64 +
            "</image>\n" +
            '            <feed line="3" />\n' +
            '            <cut type="feed" />\n' +
            "        </epos-print>\n" +
            "    </s:Body>\n" +
            "</s:Envelope>"
        );
    }

    window.FlexSysTicketBuilder = {
        normalizeOrderForTicket: normalizeOrderForTicket,
        renderKitchenTicketToCanvas: renderKitchenTicketToCanvas,
        canvasToRaster: canvasToRaster,
        encodeRaster: encodeRaster,
        buildRasterEposXml: buildRasterEposXml,
        // Same function name both adapters already call - neither
        // adapter file needed any change this round.
        buildKitchenTicketXml: buildRasterEposXml,
    };
})();
