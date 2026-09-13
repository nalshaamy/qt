import { LoginScreen } from "@point_of_sale/app/screens/login_screen/login_screen";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { _t } from "@web/core/l10n/translation";
import { rpc } from "@web/core/network/rpc";
import { patch } from "@web/core/utils/patch";


patch(PosStore.prototype, {
    checkPreviousLoggedCashier() {
        const url = new URL(window.location.href);
        if (url.searchParams.get("flexsys_device_entry") === "1") {
            // Odoo uses from_backend=1 to force a fresh server load. In normal
            // Odoo behavior that flag can preserve the previously connected
            // cashier. FlexSys device entry must always keep employee PIN
            // verification mandatory, so discard only the cached cashier id.
            this._resetConnectedCashier();

            // The marker is one-shot. Keep from_backend until Odoo consumes it
            // in firstPage, but remove our own marker immediately.
            url.searchParams.delete("flexsys_device_entry");
            window.history.replaceState({}, "", url);
            return;
        }
        return super.checkPreviousLoggedCashier(...arguments);
    },
});

patch(LoginScreen.prototype, {
    async selectCashier(pin = false, login = false, list = false) {
        const employee = await super.selectCashier(...arguments);

        // This hook runs after Odoo's native cashier-selection flow returns an
        // employee. FlexSys records the resulting cashier login as audit
        // metadata only; the PIN itself is never sent to FlexSys or stored.
        if (employee && login && pin) {
            try {
                await rpc("/flexsys/pos/device/cashier-login", { employee_id: employee.id });
            } catch (error) {
                // Audit failure must never block a successful cashier login.
                console.warn("FlexSys POS Device Access: cashier-login audit failed", error);
            }
        }
        return employee;
    },

    async clickBack() {
        // In a FlexSys-bound device session the Backend is intentionally not
        // available. Show a short product-level message rather than pos_hr's
        // user/cashier-specific warning. The server-side guard remains the
        // authoritative enforcement layer.
        try {
            const info = await rpc("/flexsys/pos/device/session-info", {});
            if (info?.is_device_session) {
                this.pos.notification.add(_t("Backend access is disabled"), { type: "danger" });
                return;
            }
        } catch (error) {
            // If the status check fails, fall back to Odoo's standard flow.
            // The HTTP backend guard still prevents device-session escape.
            console.warn("FlexSys POS Device Access: session status check failed", error);
        }
        return await super.clickBack(...arguments);
    },
});
