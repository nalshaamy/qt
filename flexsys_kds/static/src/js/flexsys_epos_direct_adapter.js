/** @odoo-module */

// ---------------------------------------------------------------------
// FlexSys KDS - Internal KDS Direct ePOS Adapter (Production)
//
// "Station -> Direct ePOS Adapter". Deliberately kept as its own,
// separate module from the KDS card's own print-button interception
// logic - this file's only job is "given a printer IP, LNA
// preference, and a notification service, print this ticket via
// Odoo's own native backend ePOS flow" - so a future "Station -> Odoo
// IoT Adapter" can sit next to it later without touching this file or
// the KDS card code at all.
//
// Reuses Odoo's own native Backend ePOS test-print mechanism
// (point_of_sale/static/src/backend/test_epos/ and
// point_of_sale/static/src/app/utils/init_lna.js) - both already
// loaded in 'web.assets_backend' by point_of_sale's own manifest, per
// direct confirmation - nothing added to this module's own assets for
// this. No EpsonPrinter/BasePrinter/render_service/html-to-image, and
// no dependency on the point_of_sale.ePOSLayout QWeb template.
//
// CORRECTED (3 blocking fixes, verified directly against Odoo 19's
// own source):
//   1. initLNA(notificationService, callback) - not initLNA() alone -
//      driven by the global odoo.use_lna flag, set here from this
//      design's own station.flexsys_use_local_network_access before
//      calling it. The notification service itself is passed in by
//      the caller (KDS component), not obtained here.
//   2. The XML payload is now Odoo's own SOAP Envelope shape, not a
//      bare <PrintDocument> root.
//   3. No Content-Type header - AbortSignal.timeout(15000) instead,
//      matching Odoo's own native request shape exactly.
// ---------------------------------------------------------------------

import { initLNA, getLNATargetAddressSpace } from "@point_of_sale/app/utils/init_lna";

// ---------------------------------------------------------------------
// REAL TICKET RENDERING ROUND: the fixed test-XML builder that used to
// live here (buildTestEposXml) is REMOVED - ticket content now comes
// entirely from window.FlexSysTicketBuilder.buildKitchenTicketXml(),
// the ONE shared file also loaded by the Public Kiosk adapter (see
// static/src/shared/flexsys_ticket_builder.js's own top-of-file
// comment for why this is the actual guarantee that both screens
// print an identical layout). Nothing below this point in this file
// changed - Direct ePOS Transport itself (LNA, protocol, endpoint,
// timeout, response parsing) is untouched, exactly as directed.
// ---------------------------------------------------------------------

/**
 * Parses an Epson ePOS-Print XML CGI response, reading `success` and
 * an error code from the <response> element wherever it sits in the
 * (possibly SOAP-wrapped) reply - logged in full regardless, since
 * the exact response envelope shape was not independently confirmed.
 */
function parseEposResponse(responseText) {
    let doc;
    try {
        doc = new DOMParser().parseFromString(responseText, "text/xml");
    } catch (e) {
        return { successful: false, errorCode: null, parseError: String(e), raw: responseText };
    }
    const parserError = doc.querySelector("parsererror");
    if (parserError) {
        return {
            successful: false,
            errorCode: null,
            parseError: parserError.textContent,
            raw: responseText,
        };
    }
    const responseEl = doc.querySelector("response");
    if (!responseEl) {
        return {
            successful: false,
            errorCode: null,
            parseError: "No <response> element found in the printer's own reply.",
            raw: responseText,
        };
    }
    return {
        successful: responseEl.getAttribute("success") === "true",
        errorCode: responseEl.getAttribute("code") || null,
        status: responseEl.getAttribute("status") || null,
        raw: responseText,
    };
}

/**
 * The adapter's own public entry point.
 * @param {{ip: string, useLna: boolean, normalizedOrder: object, notificationService: any}} params
 * @returns {Promise<{successful: boolean, errorCode: string|null, raw?: string, error?: any}>}
 */
export async function flexsysPrintViaDirectEpos({
    ip,
    useLna,
    normalizedOrder,
    notificationService,
}) {
    console.log("=== FlexSys Direct ePOS Adapter: starting ===");
    console.log("FlexSys Adapter: ip ->", ip);
    console.log("FlexSys Adapter: useLna ->", useLna);

    // Fix 1: driven by the global odoo.use_lna flag, exactly as
    // Odoo's own native flow does - set here from this design's own
    // per-station decision, since there is no pos.printer record to
    // read it from.
    odoo.use_lna = useLna;
    console.log("FlexSys Adapter: odoo.use_lna set to ->", odoo.use_lna);

    if (odoo.use_lna) {
        let lnaStatus = "pending";
        try {
            await initLNA(notificationService, (status) => {
                lnaStatus = status;
                console.log("FlexSys Adapter: LNA status callback ->", status);
            });
        } catch (e) {
            console.error(
                "FlexSys Adapter: initLNA(notificationService, callback) " +
                    "threw - this is the single most likely import/API-" +
                    "shape mismatch to check first if this fails.",
                e
            );
            return { successful: false, errorCode: "LNA_INIT_ERROR", error: e };
        }
        console.log("FlexSys Adapter: final lnaStatus ->", lnaStatus);
        if (lnaStatus === "danger") {
            console.error(
                "FlexSys Adapter FAIL: LNA permission was denied " +
                    "(status === 'danger')."
            );
            return { successful: false, errorCode: "LNA_DENIED" };
        }
    }

    // Same protocol-selection logic as Odoo's own native flow.
    const protocol = odoo.use_lna ? "http:" : window.location.protocol;
    const address = `${protocol}//${ip}/cgi-bin/epos/service.cgi?devid=local_printer`;
    console.log("FlexSys Adapter: address ->", address);

    const xml = window.FlexSysTicketBuilder.buildKitchenTicketXml(normalizedOrder);
    console.log("FlexSys Adapter: XML payload ->", xml);

    // Fix 3: no Content-Type header, AbortSignal.timeout instead of
    // any manual timeout handling - matching Odoo's own native
    // request shape exactly, avoiding an unnecessary CORS preflight.
    const params = {
        method: "POST",
        body: xml,
        signal: AbortSignal.timeout(15000),
    };
    if (odoo.use_lna) {
        try {
            params.targetAddressSpace = getLNATargetAddressSpace(ip);
            console.log(
                "FlexSys Adapter: targetAddressSpace ->",
                params.targetAddressSpace
            );
        } catch (e) {
            console.error(
                "FlexSys Adapter: getLNATargetAddressSpace(ip) threw - " +
                    "continuing the fetch() without an explicit " +
                    "targetAddressSpace.",
                e
            );
        }
    }

    let result;
    try {
        result = await fetch(address, params);
    } catch (e) {
        console.error("FlexSys Adapter FAIL: fetch() itself threw.", e);
        return { successful: false, errorCode: null, error: e };
    }
    console.log("FlexSys Adapter: fetch() HTTP status ->", result.status);

    const responseText = await result.text();
    console.log("FlexSys Adapter: raw response text ->", responseText);

    const parsed = parseEposResponse(responseText);
    console.log("FlexSys Adapter: parsed response ->", parsed);
    console.log("FlexSys Adapter: successful ->", parsed.successful);
    console.log("FlexSys Adapter: errorCode ->", parsed.errorCode);
    console.log("=== FlexSys Direct ePOS Adapter: finished ===");

    return parsed;
}
