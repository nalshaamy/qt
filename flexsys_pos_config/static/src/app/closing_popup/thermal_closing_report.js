/** @odoo-module **/

import { ClosePosPopup } from "@point_of_sale/app/components/popups/closing_popup/closing_popup";
import { patch } from "@web/core/utils/patch";

patch(ClosePosPopup.prototype, {
    get flexsysThermalClosingReportEnabled() {
        return Boolean(this.pos?.config?.flexsys_enable_thermal_closing_report);
    },

    get flexsysAutoPrintThermalClosingReportEnabled() {
        return Boolean(
            this.flexsysThermalClosingReportEnabled &&
            this.pos?.config?.flexsys_auto_print_thermal_closing_report
        );
    },

    async flexsysOpenThermalClosingReport(sessionId = null) {
        const reportSessionId = sessionId || this.pos?.session?.id;

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
                this.flexsysAutoPrintThermalClosingReportEnabled &&
                !this._flexsysAutoPrintInProgress &&
                !this._flexsysAutoPrintCompleted
            ) {
                this._flexsysAutoPrintInProgress = true;
                try {
                    await this.flexsysOpenThermalClosingReport(sessionId);
                    this._flexsysAutoPrintCompleted = true;
                } catch (error) {
                    // Closing has already succeeded. Printing errors must never
                    // roll back or block the original Odoo closing workflow.
                    console.error(
                        "FLPOS: The POS session closed successfully, but automatic printing failed.",
                        error
                    );
                } finally {
                    this._flexsysAutoPrintInProgress = false;
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
