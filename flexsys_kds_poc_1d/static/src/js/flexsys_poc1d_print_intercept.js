/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { FlexSysKdsScreen } from "@flexsys_kds/js/kds_app";
import { flexsysPrintViaDirectEpos } from "./flexsys_epos_direct_adapter";

// ---------------------------------------------------------------------
// FlexSys KDS - POC-1D ONLY (TEMPORARY, NOT COMMERCIAL CODE)
//
// This file's only job: read the current Station's own printing
// config and hand off to the correct Adapter -
// flexsysPrintViaDirectEpos() for 'direct_network' this round. It
// does NOT itself know anything about EpsonPrinter, ePOS-Print XML,
// or LNA - all of that lives in flexsys_epos_direct_adapter.js, kept
// deliberately separate so a future 'iot' branch can call a
// different, equally separate adapter without touching this file.
//
// SAME CLASS-FIELD CONSTRAINT AS THE PRIOR ROUNDS, CONFIRMED AGAIN BY
// INSPECTING flexsys_kds's OWN CODE FIRST:
// FlexSysKdsScreen.onPrintClick (in kds_app.js) is a class-field arrow
// function, not a prototype method - patch() cannot intercept it
// directly (every instance shadows the prototype). This module
// instead patches setup() (a real prototype method) and replaces
// this.onPrintClick right after calling super.setup(), once the
// original class-field function already exists on the instance -
// keeping a reference to it so any station NOT using
// flexsys_printing_method = 'direct_network' keeps working through
// the existing Agent-protocol path, completely unchanged.
// ---------------------------------------------------------------------

patch(FlexSysKdsScreen.prototype, {
    setup() {
        super.setup();

        // Standard Odoo way to reach the ORM service from a Component.
        // Needed because flexsys_kds's own backend controller does not
        // return this POC's own new station fields - they are read
        // directly here instead, without touching that controller.
        this.flexsysPoc1dOrm = useService("orm");

        // Required for the corrected initLNA(notificationService,
        // callback) pattern the Adapter now uses - obtained here (a
        // Component's own setup()) and passed through, never fetched
        // inside the Adapter itself.
        this.flexsysNotification = useService("notification");

        // The ORIGINAL Print button behavior - already assigned to
        // this instance as a class field by the time super.setup()
        // returns above. Kept so any station not using this POC's own
        // Direct Network method falls through to it unchanged.
        const originalOnPrintClick = this.onPrintClick;

        this.onPrintClick = async (orderId) => {
            console.log("=== FlexSys POC-1D: Card Print clicked ===");
            console.log("FlexSys POC-1D: orderId ->", orderId);

            const stationId = this.state.currentStationId;
            console.log("FlexSys POC-1D: stationId ->", stationId);

            if (!stationId) {
                console.log(
                    "FlexSys POC-1D: no current station - falling back " +
                        "to the existing Agent-protocol print."
                );
                return originalOnPrintClick(orderId);
            }

            let stationData;
            try {
                stationData = await this.flexsysPoc1dOrm.read(
                    "kds.station",
                    [stationId],
                    [
                        "name",
                        "company_id",
                        "flexsys_printing_method",
                        "flexsys_printer_ip",
                        "flexsys_use_local_network_access",
                    ]
                );
            } catch (e) {
                console.error(
                    "FlexSys POC-1D: failed to read kds.station - " +
                        "falling back to the existing Agent-protocol " +
                        "print.",
                    e
                );
                return originalOnPrintClick(orderId);
            }

            const station = stationData?.[0];
            console.log("FlexSys POC-1D: station record ->", station);

            if (!station || station.flexsys_printing_method !== "direct_network") {
                console.log(
                    "FlexSys POC-1D: this station's Printing Method " +
                        "(POC) is not 'Direct Network' - falling back " +
                        "to the existing Agent-protocol print, exactly " +
                        "as before this module was installed."
                );
                return originalOnPrintClick(orderId);
            }

            if (!station.flexsys_printer_ip) {
                console.error(
                    "FlexSys POC-1D FAIL: Printing Method (POC) is " +
                        "'Direct Network' but Printer IP (POC) is " +
                        "empty on this station. Set it on the " +
                        "station's own 'Printing (POC)' tab first."
                );
                return;
            }

            // REAL TICKET RENDERING ROUND: find the full order object
            // this screen already holds locally (this.state.orders is
            // the same array FlexSysKdsScreen's own rendering already
            // reads product_name/qty/variant_info/note/line_change
            // from for the card itself - confirmed by reading
            // kds_templates.xml before writing this) - no extra
            // network round-trip needed. Normalized via the ONE shared
            // function also used by the Public Kiosk integration, so
            // both screens make an identical "which raw fields feed
            // the ticket" decision.
            const rawOrder = this.state.orders.find((o) => o.id === orderId);
            if (!rawOrder) {
                console.error(
                    "FlexSys POC-1D FAIL: order id " +
                        orderId +
                        " not found in this.state.orders - cannot " +
                        "build a real ticket."
                );
                return;
            }
            // FIX ("Real Raster Ticket Consolidated Review", item 1):
            // this round's own test print must show "NEW" - a
            // hardcoded "REPRINT" here was wrong even for the very
            // first print of an order. The real decision (has a
            // successful print already happened for this Order +
            // Station, per kds.print.job records, not browser local
            // state) is deferred to the "Direct Printing <->
            // kds.print.job" Baseline phase - "NEW" here for now, with
            // the renderer itself fully able to accept REPRINT/ADDED/
            // UPDATED/CANCELLED once that real lifecycle exists.
            //
            // Internal/Public branch-name parity fix: both screens
            // must derive the branch name from the SAME source - the
            // station's own company_id - not Internal KDS reading
            // rawOrder.company_name (a different field entirely) while
            // Public Kiosk reads station.company_id.name. company_id
            // arrives from read() as [id, display_name]; kept as a
            // fallback only in the unlikely case company_id is unset.
            const branchName = (station.company_id && station.company_id[1]) || rawOrder.company_name || "";
            const normalizedOrder = window.FlexSysTicketBuilder.normalizeOrderForTicket(
                rawOrder,
                station.name,
                "NEW",
                branchName
            );
            console.log("FlexSys POC-1D: normalized order ->", normalizedOrder);

            // Hand off entirely to the separate Direct ePOS Adapter -
            // this file knows nothing about the transport itself.
            const result = await flexsysPrintViaDirectEpos({
                ip: station.flexsys_printer_ip,
                useLna: Boolean(station.flexsys_use_local_network_access),
                normalizedOrder,
                notificationService: this.flexsysNotification,
            });

            console.log("=== FlexSys POC-1D: Card Print finished ===");
            console.log("FlexSys POC-1D: adapter result ->", result);
        };
    },
});
