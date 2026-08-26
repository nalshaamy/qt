/**
 * FlexSys KDS - POC-1D ONLY (TEMPORARY, NOT COMMERCIAL CODE)
 *
 * "Public Kiosk Direct ePOS Adapter" - the standalone-page equivalent
 * of the Internal KDS's own Direct ePOS Adapter
 * (flexsys_epos_direct_adapter.js). Same XML, same endpoint, same
 * timeout, same LNA semantics, same response parsing, same
 * success/error contract - deliberately kept behaviorally identical,
 * but implemented in plain (non-module) JavaScript, since the Public
 * Kiosk page is standalone HTML with a classic <script> tag and no
 * Odoo Web Client / OWL / module loader at all - "@point_of_sale/..."
 * imports cannot resolve there.
 *
 * Exposes exactly one namespace, as directed:
 *   window.FlexSysKDSPrint.printDirectEpos(options)
 *
 * This is intentional and accepted here specifically because this is
 * a standalone public page, not an Odoo Web Client context - no other
 * globals are introduced.
 */
(function () {
    "use strict";

    function escapeXml(s) {
        return String(s == null ? "" : s).replace(/[&<>]/g, function (c) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c];
        });
    }

    // -------------------------------------------------------------
    // REAL TICKET RENDERING ROUND: the fixed test-XML builder that
    // used to live here (buildTestEposXml) is REMOVED - ticket
    // content now comes entirely from
    // window.FlexSysTicketBuilder.buildKitchenTicketXml(), the ONE
    // shared file also loaded by the Internal KDS adapter (see
    // static/src/shared/flexsys_ticket_builder.js's own top-of-file
    // comment for why this is the actual guarantee that both screens
    // print an identical layout). Everything else in this file is
    // unchanged - Direct ePOS Transport itself (LNA, protocol,
    // endpoint, timeout, response parsing) is untouched, exactly as
    // directed.
    // -------------------------------------------------------------

    /**
     * Vanilla equivalent of Odoo's own getLNATargetAddressSpace(),
     * per the approved spec exactly.
     */
    function getTargetAddressSpace(url) {
        var hostname;
        try {
            hostname = new URL(url).hostname;
        } catch (e) {
            hostname = url;
        }
        if (hostname === "localhost" || hostname === "127.0.0.1") {
            return "loopback";
        }
        return "local";
    }

    /**
     * Vanilla equivalent of Odoo's own initLNA(), using the browser's
     * own Permissions API directly, per the approved spec exactly.
     * Mutates nothing global - returns the resulting status string:
     * "success", "warning", "danger", or "unsupported".
     */
    async function checkLnaPermission() {
        try {
            var permission = await navigator.permissions.query({
                name: "local-network-access",
            });
            if (permission.state === "granted") {
                return "success";
            } else if (permission.state === "prompt") {
                return "warning";
            } else {
                return "danger";
            }
        } catch (e) {
            // Browser does not support the LNA permission API.
            console.log(
                "FlexSys Public Adapter: navigator.permissions.query " +
                    "for 'local-network-access' is not supported by " +
                    "this browser - continuing without an explicit " +
                    "LNA permission check.",
                e
            );
            return "unsupported";
        }
    }

    function parseEposResponse(responseText) {
        var doc;
        try {
            doc = new DOMParser().parseFromString(responseText, "application/xml");
        } catch (e) {
            return {
                successful: false,
                errorCode: "",
                parseError: String(e),
                raw: responseText,
            };
        }
        var parserError = doc.querySelector("parsererror");
        if (parserError) {
            return {
                successful: false,
                errorCode: "",
                parseError: parserError.textContent,
                raw: responseText,
            };
        }
        var responseEl = doc.querySelector("response");
        var success = responseEl && responseEl.getAttribute("success") === "true";
        var errorCode = (responseEl && responseEl.getAttribute("code")) || "";
        return {
            successful: Boolean(success) && !errorCode,
            errorCode: errorCode,
            raw: responseText,
        };
    }

    /**
     * Public entry point.
     * @param {{ip: string, useLocalNetworkAccess: boolean, normalizedOrder: object}} options
     * @returns {Promise<{successful: boolean, errorCode: string, raw?: string, error?: any}>}
     */
    async function printDirectEpos(options) {
        var ip = options.ip;
        var useLocalNetworkAccess = Boolean(options.useLocalNetworkAccess);
        var normalizedOrder = options.normalizedOrder;

        console.log("=== FlexSys Public Adapter: starting ===");
        console.log("FlexSys Public Adapter: ip ->", ip);
        console.log("FlexSys Public Adapter: useLocalNetworkAccess ->", useLocalNetworkAccess);

        if (useLocalNetworkAccess) {
            var lnaStatus = "pending";
            try {
                lnaStatus = await checkLnaPermission();
            } catch (e) {
                // checkLnaPermission() itself only throws if something
                // outside its own try/catch went wrong - treat as
                // "unsupported" and continue, matching the approved
                // spec's own catch-block behavior (disable LNA rather
                // than block printing outright).
                console.error("FlexSys Public Adapter: LNA check threw unexpectedly.", e);
                useLocalNetworkAccess = false;
                lnaStatus = "unsupported";
            }
            console.log("FlexSys Public Adapter: lnaStatus ->", lnaStatus);

            if (lnaStatus === "danger") {
                console.error(
                    "FlexSys Public Adapter FAIL: LNA permission was " +
                        "denied (state 'denied')."
                );
                return { successful: false, errorCode: "LNA_DENIED" };
            }
            if (lnaStatus === "unsupported") {
                // Per the approved spec: browser does not support the
                // LNA permission API -> continue without LNA.
                useLocalNetworkAccess = false;
            }
            // "success" or "warning" (prompt) -> continue, matching
            // Odoo's own behavior.
        }

        var protocol = useLocalNetworkAccess ? "http:" : window.location.protocol;
        var address = protocol + "//" + ip + "/cgi-bin/epos/service.cgi?devid=local_printer";
        console.log("FlexSys Public Adapter: address ->", address);

        var xml = window.FlexSysTicketBuilder.buildKitchenTicketXml(normalizedOrder);
        console.log("FlexSys Public Adapter: XML payload ->", xml);

        var params = {
            method: "POST",
            body: xml,
            signal: AbortSignal.timeout(15000),
        };
        if (useLocalNetworkAccess) {
            params.targetAddressSpace = getTargetAddressSpace(address);
            console.log(
                "FlexSys Public Adapter: targetAddressSpace ->",
                params.targetAddressSpace
            );
        }
        // No Content-Type, no custom headers - matching the proven
        // Internal KDS adapter exactly.

        var result;
        try {
            result = await fetch(address, params);
        } catch (e) {
            var isTimeout = e && e.name === "TimeoutError";
            console.error(
                "FlexSys Public Adapter FAIL: fetch() itself threw" +
                    (isTimeout ? " (timeout after 15s)." : "."),
                e
            );
            return {
                successful: false,
                errorCode: isTimeout ? "TIMEOUT" : "NETWORK_ERROR",
                error: e,
            };
        }
        console.log("FlexSys Public Adapter: fetch() HTTP status ->", result.status);

        var responseText = await result.text();
        console.log("FlexSys Public Adapter: raw response text ->", responseText);

        var parsed = parseEposResponse(responseText);
        console.log("FlexSys Public Adapter: parsed response ->", parsed);
        console.log("FlexSys Public Adapter: successful ->", parsed.successful);
        console.log("FlexSys Public Adapter: errorCode ->", parsed.errorCode);
        console.log("=== FlexSys Public Adapter: finished ===");

        return parsed;
    }

    window.FlexSysKDSPrint = {
        printDirectEpos: printDirectEpos,
    };
})();
