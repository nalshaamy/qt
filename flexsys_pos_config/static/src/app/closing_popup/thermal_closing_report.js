/** @odoo-module **/

import { ClosePosPopup } from "@point_of_sale/app/components/popups/closing_popup/closing_popup";
import { patch } from "@web/core/utils/patch";
import { useState } from "@odoo/owl";

patch(ClosePosPopup.prototype, {
    setup() {
        super.setup(...arguments);
        this.flexsysClosingReportMenuState = useState({ open: false });
    },

    get flexsysA4ClosingReportEnabled() {
        return Boolean(this.pos?.config?.flexsys_enable_a4_closing_report);
    },

    get flexsysThermalClosingReportEnabled() {
        return Boolean(this.pos?.config?.flexsys_enable_thermal_closing_report);
    },

    get flexsysClosingReportMenuEnabled() {
        return Boolean(
            this.flexsysA4ClosingReportEnabled || this.flexsysThermalClosingReportEnabled
        );
    },

    get flexsysClosingReportMenuOpen() {
        return Boolean(this.flexsysClosingReportMenuState?.open);
    },

    flexsysToggleClosingReportMenu() {
        this.flexsysClosingReportMenuState.open = !this.flexsysClosingReportMenuState.open;
    },

    flexsysCloseClosingReportMenu() {
        this.flexsysClosingReportMenuState.open = false;
    },

    async flexsysOpenA4ClosingReport() {
        this.flexsysCloseClosingReportMenu();
        const reportSessionId = this.pos?.session?.id;

        if (!reportSessionId) {
            console.error("FLPOS: Unable to determine the POS session ID.");
            return;
        }

        return this.report.doAction(
            "flexsys_pos_config.action_report_pos_session_closing",
            [reportSessionId]
        );
    },

    get flexsysAutoPrintThermalClosingReportEnabled() {
        return Boolean(
            this.flexsysThermalClosingReportEnabled &&
            this.pos?.config?.flexsys_auto_print_thermal_closing_report
        );
    },

    async flexsysOpenThermalClosingReport(sessionId = null) {
        this.flexsysCloseClosingReportMenu();
        // OWL passes the click event as the first argument when this method is
        // called directly from t-on-click. Only accept a real numeric session
        // ID; otherwise use the current POS session. This keeps manual and
        // automatic printing on the exact same report action.
        const explicitSessionId = Number.isInteger(sessionId) ? sessionId : null;
        const reportSessionId = explicitSessionId || this.pos?.session?.id;

        if (!reportSessionId) {
            console.error("FLPOS: Unable to determine the POS session ID.");
            return;
        }

        return this.report.doAction(
            "flexsys_pos_config.action_report_pos_session_closing_thermal",
            [reportSessionId]
        );
    },

    async closeSession() {
        const router = this.pos?.router;
        const originalRouterClose = router?.close;
        const sessionId = this.pos?.session?.id;
        let routerCloseRequested = false;

        // Odoo closes the POS router immediately after a successful session close.
        // Delay only that final navigation so the report action can run first.
        if (router && typeof originalRouterClose === "function") {
            router.close = () => {
                routerCloseRequested = true;
            };
        }

        try {
            const result = await super.closeSession(...arguments);
            const sessionClosed = this.pos?.session?.state === "closed";

            if (
                sessionClosed &&
                !this._flexsysClosingReportInProgress &&
                !this._flexsysClosingReportCompleted
            ) {
                this._flexsysClosingReportInProgress = true;
                try {
                    if (this.flexsysAutoPrintThermalClosingReportEnabled) {
                        // Automatic mode: use the compact thermal report action.
                        await this.flexsysOpenThermalClosingReport(sessionId);
                    } else if (this.flexsysA4ClosingReportEnabled) {
                        // Manual/PDF mode: preserve the established A4 closing
                        // report flow when automatic thermal printing is disabled.
                        await this.report.doAction(
                            "flexsys_pos_config.action_report_pos_session_closing",
                            [sessionId]
                        );
                    }
                    this._flexsysClosingReportCompleted = true;
                } catch (error) {
                    // Closing has already succeeded. A report-display error must
                    // not roll back or block the original Odoo closing workflow.
                    console.error(
                        "FLPOS: The POS session closed successfully, but the closing report could not be opened.",
                        error
                    );
                } finally {
                    this._flexsysClosingReportInProgress = false;
                }
            }

            return result;
        } finally {
            if (router && typeof originalRouterClose === "function") {
                router.close = originalRouterClose;
                if (routerCloseRequested) {
                    originalRouterClose.call(router);
                }
            }
        }
    },
});
