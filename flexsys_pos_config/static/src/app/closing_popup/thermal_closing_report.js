/** @odoo-module **/

import { ClosePosPopup } from "@point_of_sale/app/components/popups/closing_popup/closing_popup";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { useState } from "@odoo/owl";

/**
 * Return true only for browser storage quota failures.
 *
 * Browsers do not expose this error consistently: Chromium normally uses
 * `QuotaExceededError`, while other engines can expose a numeric DOMException
 * code or only include the quota text in the message.
 */
function isStorageQuotaError(error) {
    const name = String(error?.name || "");
    const message = String(error?.message || "");
    return (
        name === "QuotaExceededError" ||
        error?.code === 22 ||
        error?.code === 1014 ||
        /quota.*exceed|exceed.*quota/i.test(message)
    );
}

patch(ClosePosPopup.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = this.orm || useService("orm");
        this.notification = this.notification || useService("notification");
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

    /**
     * Verify the authoritative server state after an exceptional close flow.
     * This is intentionally used only after a quota error, so normal closing
     * does not gain an additional RPC call.
     */
    async _flexsysIsSessionClosedOnServer(sessionId) {
        if (!sessionId || !this.orm) {
            return false;
        }
        try {
            const [session] = await this.orm.read("pos.session", [sessionId], ["state"]);
            return session?.state === "closed";
        } catch (verificationError) {
            console.error(
                "FLPOS: Could not verify the POS session state after a browser storage error.",
                verificationError
            );
            return false;
        }
    },

    /**
     * Open the configured post-close report without affecting the completed
     * accounting close if report rendering or browser display fails.
     */
    async _flexsysOpenConfiguredClosingReport(sessionId) {
        if (
            this._flexsysClosingReportInProgress ||
            this._flexsysClosingReportCompleted
        ) {
            return;
        }
        this._flexsysClosingReportInProgress = true;
        try {
            if (this.flexsysAutoPrintThermalClosingReportEnabled) {
                await this.flexsysOpenThermalClosingReport(sessionId);
            } else if (this.flexsysA4ClosingReportEnabled) {
                await this.report.doAction(
                    "flexsys_pos_config.action_report_pos_session_closing",
                    [sessionId]
                );
            }
            this._flexsysClosingReportCompleted = true;
        } catch (error) {
            console.error(
                "FLPOS: The POS session closed successfully, but the closing report could not be opened.",
                error
            );
            this.notification?.add(
                _t("The session was closed, but the closing report could not be opened."),
                { type: "warning" }
            );
        } finally {
            this._flexsysClosingReportInProgress = false;
        }
    },

    /**
     * Harden Odoo's closing flow against intermittent browser quota failures.
     *
     * The error is suppressed only when the server confirms that the session
     * is already closed. All other exceptions are rethrown unchanged. Router
     * navigation is replayed only after a confirmed successful close.
     */
    async closeSession() {
        if (this._flexsysCloseSessionPromise) {
            return this._flexsysCloseSessionPromise;
        }

        this._flexsysCloseSessionPromise = (async () => {
            const router = this.pos?.router;
            const originalRouterClose = router?.close;
            const sessionId = this.pos?.session?.id;
            let routerCloseRequested = false;
            let sessionClosed = false;
            let result;

            if (router && typeof originalRouterClose === "function") {
                router.close = () => {
                    routerCloseRequested = true;
                };
            }

            try {
                try {
                    result = await super.closeSession(...arguments);
                    sessionClosed = this.pos?.session?.state === "closed";
                } catch (error) {
                    if (!isStorageQuotaError(error)) {
                        throw error;
                    }

                    sessionClosed = await this._flexsysIsSessionClosedOnServer(sessionId);
                    if (!sessionClosed) {
                        throw error;
                    }

                    console.warn(
                        "FLPOS: Browser storage quota was exceeded after the POS session had already closed on the server.",
                        { sessionId, error }
                    );
                    this.notification?.add(
                        _t(
                            "The session closed successfully. Browser storage is nearly full; clear old site data before the next shift."
                        ),
                        { type: "warning", sticky: true }
                    );
                }

                if (sessionClosed) {
                    await this._flexsysOpenConfiguredClosingReport(sessionId);
                }
                return result;
            } finally {
                if (router && typeof originalRouterClose === "function") {
                    router.close = originalRouterClose;
                    if (routerCloseRequested && sessionClosed) {
                        originalRouterClose.call(router);
                    }
                }
            }
        })();

        try {
            return await this._flexsysCloseSessionPromise;
        } finally {
            this._flexsysCloseSessionPromise = null;
        }
    },
});
