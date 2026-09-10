import { LoginScreen } from "@point_of_sale/app/screens/login_screen/login_screen";
import { _t } from "@web/core/l10n/translation";
import { rpc } from "@web/core/network/rpc";
import { patch } from "@web/core/utils/patch";

patch(LoginScreen.prototype, {
    async selectCashier(pin = false, login = false, list = false) {
        const employee = await super.selectCashier(...arguments);

        // pos_hr returns the employee only after the supplied PIN has been
        // accepted. Audit metadata only; never send or store the PIN itself.
        if (employee && login && pin) {
            try {
                await rpc("/flexsys/pos/device/pin-success", { employee_id: employee.id });
            } catch (error) {
                // Audit failure must never block a successful cashier login.
                console.warn("FlexSys POS Device Access: PIN audit failed", error);
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
