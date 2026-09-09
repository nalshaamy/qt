import { LoginScreen } from "@point_of_sale/app/screens/login_screen/login_screen";
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
});
