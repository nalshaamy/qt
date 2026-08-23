/** @odoo-module **/

import { Component, onWillStart, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";
import { makeKdsStore } from "./kds_store";
import { KdsOrderCard } from "./kds_order_card";
import { KDS_LABELS } from "./kds_i18n";

// Languages Odoo ships RTL for; kept as a small explicit list (rather than
// trying to derive it from the locale code alone) since this only needs to
// flip the *custom* KDS screen's own layout - the rest of the Odoo backend
// already handles RTL for these via its own asset bundle.
const RTL_LANGS = ["ar", "he", "fa", "ur"];

// Point 5: querystring-driven kiosk mode. Reached either directly
// (?station=KITCHEN&kiosk=1, as set by the /flexsyskds/<code> redirect
// controller) or manually appended to the normal backend action URL.
const KIOSK_BODY_CLASS = "o_flexsys_kiosk";

export class FlexSysKdsScreen extends Component {
    static template = "flexsys_kds.Screen";
    static components = { KdsOrderCard };
    static props = ["*"];

    setup() {
        this.store = makeKdsStore();
        this.state = useState(this.store.state);
        this.action = useService("action");
        // UI/DATA FIX ("Printing Cleanup - Toast + Job Record
        // Simplification"), decision item 6: the notification service
        // was injected here specifically for the Print/Reprint failure
        // Toast (v7.17.0/v7.17.1), which is now removed entirely per
        // explicit direction - "No Printer -> No Job is sufficient."
        // No other part of this component currently needs the
        // notification service, so the injection itself is removed
        // too, rather than left unused.
        this.labels = KDS_LABELS;
        // KDS FULLSCREEN MODE (dev request "V1 Finalization", item 1):
        // deliberately a separate local reactive object, not folded into
        // this.store.state - fullscreen is a purely browser/DOM concern
        // for this one component instance, not server-synced KDS data,
        // so it doesn't belong in the same state object that
        // loadOrders()/loadStations() manage.
        this.fsState = useState({ isFullscreen: false });

        // Multi-language: the user's language drives both which translated
        // strings render (handled transparently by _t()/backend *_label
        // fields once i18n/*.po is imported) and whether this screen
        // should render right-to-left. `user.lang` from @web/core/user is
        // the standard client-side source for this in recent Odoo
        // versions; falls back to session_info if that module's shape
        // ever changes.
        let lang = "en_US";
        try {
            lang = user.lang || (odoo.session_info && odoo.session_info.user_context
                && odoo.session_info.user_context.lang) || "en_US";
        } catch (e) {
            lang = "en_US";
        }
        this.isRtl = RTL_LANGS.includes(lang.split("_")[0]);

        const params = new URLSearchParams(window.location.search);
        this._requestedStationCode = params.get("station");
        this.isKiosk = params.get("kiosk") === "1";

        this.busService = useService("bus_service");
        this._busChannel = false;
        this._onBusNotification = this._onBusNotification.bind(this);

        onWillStart(async () => {
            await this.store.refreshAll();
            if (this._requestedStationCode) {
                const match = this.state.stations.find(
                    (s) => (s.code || "").toLowerCase() === this._requestedStationCode.toLowerCase()
                );
                if (match && match.id !== this.state.currentStationId) {
                    await this.store.setStation(match.id);
                }
                // If no station matches the code, fall back silently to
                // whichever station the store already defaulted to
                // (the first one the user is allowed to see) rather than
                // showing an empty/broken screen over a typo'd URL.
            }
        });
        onMounted(() => {
            if (this.isKiosk) {
                document.body.classList.add(KIOSK_BODY_CLASS);
            }
            this._subscribeBus(this.state.currentStationId);
            this.busService.subscribe("flexsys_kds.order_update", this._onBusNotification);
            this.busService.start();
            // Fallback safety net - bus should make this redundant in the
            // common case, kept at a longer interval than the old 4s.
            this.store.startPolling(15000);
            this._tickClock();
            this._clockHandle = setInterval(() => this._tickClock(), 1000);
            // KDS FULLSCREEN MODE: keeps fsState.isFullscreen correct even
            // when fullscreen is exited a way other than tapping the
            // button - the Esc key, or a tablet's own system gesture
            // ("standard browser Fullscreen exit behavior may be used",
            // per the dev request itself) - rather than only updating on
            // click. The Fullscreen API itself never reloads the page or
            // touches any other state (store data, filters, timers,
            // realtime subscriptions all keep running untouched), which
            // is what satisfies the request's own "must NOT" list
            // automatically, by construction.
            this._onFullscreenChange = () => {
                this.fsState.isFullscreen = Boolean(document.fullscreenElement);
            };
            document.addEventListener("fullscreenchange", this._onFullscreenChange);
        });
        onWillUnmount(() => {
            document.body.classList.remove(KIOSK_BODY_CLASS);
            this.store.stopPolling();
            this.busService.unsubscribe("flexsys_kds.order_update", this._onBusNotification);
            this._unsubscribeBus();
            clearInterval(this._clockHandle);
            document.removeEventListener("fullscreenchange", this._onFullscreenChange);
        });
    }

    _tickClock() {
        this.state.clockLabel = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }

    get currentStation() {
        return this.state.stations.find((s) => s.id === this.state.currentStationId) || {};
    }

    get printingEnabled() {
        // Gated by the station's own printing configuration
        // (operating_mode), not by a per-user permission - explicit
        // decision, see controllers/kds.py::reprint().
        return Boolean(this.currentStation.printing_enabled);
    }

    _channelName(stationId) {
        return stationId ? `flexsys_kds-station-${stationId}` : false;
    }

    _subscribeBus(stationId) {
        const channel = this._channelName(stationId);
        if (channel) {
            this.busService.addChannel(channel);
            this._busChannel = channel;
        }
    }

    _unsubscribeBus() {
        if (this._busChannel) {
            this.busService.deleteChannel(this._busChannel);
            this._busChannel = false;
        }
    }

    _onBusNotification(payload) {
        // Any order_update notification triggers a refetch of the current
        // station's orders. The payload only carries a station id, never
        // order content, by design (see kds_notify.py).
        this.store.loadOrders();
    }

    get filteredOrders() {
        const filter = this.state.filter;
        let orders = this.state.orders;
        if (filter === "late") {
            orders = orders.filter((o) => o.sla_status === "late");
        } else if (filter === "new" || filter === "preparing" || filter === "ready" || filter === "completed") {
            // REAL BUG FIX, confirmed live on Odoo.sh (BUG-10, "Reopened
            // READY Order Appears in Multiple Stage Tabs"): each of
            // these four tabs used to run its own INDEPENDENT check
            // ("does ANY line match this tab's own state(s)?"), each
            // entirely oblivious to the others - a reopened order with
            // one line back at "new" (freshly added/reset by a POS
            // Delta) and another still "preparing" satisfied BOTH
            // checks at once, so the same physical ticket counted under
            // NEW *and* PREPARING simultaneously ("NEW = 1, PREPARING =
            // 1" for one ticket, reported live), on top of everything
            // BUG-03/BUG-07/BUG-08 already had to separately account
            // for (per-station Ready visibility, completion, preserved-
            // last-stage-while-cancelled). Replaced with
            // order.effective_stage - one authoritative value, computed
            // once on the backend (see controllers/kds.py's own
            // _effective_stage() for the full algorithm), used
            // identically here and for the card's own displayed status
            // text (KdsOrderCard's own statusText getter) -
            // structurally guaranteeing a ticket belongs to exactly one
            // tab, rather than relying on several independently-written
            // checks to happen to agree.
            orders = orders.filter((o) => o.effective_stage === filter);
        } else if (filter !== "all") {
            orders = orders.filter((o) => o.lines.some((l) => l.state === filter));
        }
        // Dropdown filters narrow further, on top of the pill filter above -
        // e.g. "PREPARING" + order type "Delivery" shows only preparing
        // delivery orders, not one or the other.
        if (this.state.orderTypeFilter !== "all") {
            orders = orders.filter((o) => o.order_type === this.state.orderTypeFilter);
        }
        if (this.state.employeeFilter !== "all") {
            orders = orders.filter((o) => (o.employee_name || "") === this.state.employeeFilter);
        }
        if (this.state.companyFilter !== "all") {
            orders = orders.filter((o) => (o.company_name || "") === this.state.companyFilter);
        }
        if (this.state.posConfigFilter !== "all") {
            orders = orders.filter((o) => (o.pos_config_name || "") === this.state.posConfigFilter);
        }
        return orders;
    }

    get orderTypeOptions() {
        // Static, not derived from loaded orders - order types are a
        // fixed set (kds.order.order_type Selection), so every option is
        // always offered regardless of what's currently on screen.
        return [
            { value: "dine_in", label: this.labels.orderTypeDineIn },
            { value: "take_away", label: this.labels.orderTypeTakeAway },
            { value: "delivery", label: this.labels.orderTypeDelivery },
            { value: "pickup", label: this.labels.orderTypePickup },
            { value: "drive_thru", label: this.labels.orderTypeDriveThru },
        ];
    }

    get employeeOptions() {
        // Dynamic - only employees who actually have orders on this
        // station right now, so the list doesn't fill up with names
        // that would just filter to an empty grid.
        const names = new Set(
            this.state.orders.map((o) => o.employee_name).filter(Boolean)
        );
        return [...names].sort();
    }

    get companyOptions() {
        // Dynamic, same reasoning as employeeOptions - most single-company
        // setups will just have one value here (or the filter row hides
        // itself entirely, see the template's t-if), but multi-company
        // POS setups routing to a shared station benefit from this.
        const names = new Set(
            this.state.orders.map((o) => o.company_name).filter(Boolean)
        );
        return [...names].sort();
    }

    get posConfigOptions() {
        const names = new Set(
            this.state.orders.map((o) => o.pos_config_name).filter(Boolean)
        );
        return [...names].sort();
    }

    get counts() {
        const orders = this.state.orders;
        // REAL BUG FIX (BUG-10) - see filteredOrders' own detailed
        // comment. One authoritative value per order, computed once,
        // drives every count below - eliminating the possibility of the
        // same ticket incrementing more than one bucket at once.
        const byStage = {};
        for (const o of orders) {
            byStage[o.effective_stage] = (byStage[o.effective_stage] || 0) + 1;
        }
        return {
            all: orders.length,
            new: byStage.new || 0,
            preparing: byStage.preparing || 0,
            ready: byStage.ready || 0,
            completed: byStage.completed || 0,
            late: orders.filter((o) => o.sla_status === "late").length,
        };
    }

    onSelectStation(ev) {
        this._unsubscribeBus();
        const stationId = parseInt(ev.target.value, 10);
        this.store.setStation(stationId);
        this._subscribeBus(stationId);
    }

    onToggleFullscreen() {
        // KDS FULLSCREEN MODE (dev request "V1 Finalization", item 1):
        // targets document.documentElement (the whole page), not just
        // this component's own root node - a kitchen tablet should see
        // Odoo's own backend chrome disappear too, not just have this
        // screen's own content area grow inside a still-visible browser
        // frame. fsState.isFullscreen itself isn't set here directly -
        // the fullscreenchange listener (see onMounted above) is the
        // single source of truth for that, so the icon/label stay
        // correct regardless of whether fullscreen was entered/exited
        // via this button, the Esc key, or a device's own gesture.
        if (!document.fullscreenElement) {
            const el = document.documentElement;
            const request = el.requestFullscreen || el.webkitRequestFullscreen || el.msRequestFullscreen;
            if (request) request.call(el).catch(() => {});
        } else {
            const exit = document.exitFullscreen || document.webkitExitFullscreen || document.msExitFullscreen;
            if (exit) exit.call(document).catch(() => {});
        }
    }

    onSetFilter(filter) {
        this.store.setFilter(filter);
    }

    onSelectOrderTypeFilter(ev) {
        this.store.setOrderTypeFilter(ev.target.value);
    }

    onSelectEmployeeFilter(ev) {
        this.store.setEmployeeFilter(ev.target.value);
    }

    onSelectCompanyFilter(ev) {
        this.store.setCompanyFilter(ev.target.value);
    }

    onSelectPosConfigFilter(ev) {
        this.store.setPosConfigFilter(ev.target.value);
    }

    onLineAction = (lineId, action, reason) => {
        this.store.lineAction(lineId, action, reason);
    };

    onOrderAction = (orderId, action) => {
        this.store.orderAction(orderId, action);
    };

    onPrintClick = (orderId) => {
        // Default reason since the card's print button is a single tap,
        // no reason-picker dialog - 'kitchen_request' reads reasonably
        // as "requested from the station itself" in the audit log.
        //
        // UI/DATA FIX ("Printing Cleanup - Toast + Job Record
        // Simplification"), decision item 6: the Toast requirement is
        // removed entirely per explicit direction - "No Printer -> No
        // Job is sufficient." The backend guard that actually matters
        // (models/kds_print_job.py's own NoPrinterConfiguredError,
        // preventing any kds.print.job from ever being created for a
        // station with no configured printer) is completely unchanged
        // and still fully in effect; only the UI notification layer
        // added in v7.17.0/v7.17.1 for this specific requirement is
        // removed here, reverting to the simple fire-and-forget call
        // this method always had before that round.
        this.store.reprint(orderId, this.state.currentStationId, "kitchen_request");
    };
}

registry.category("actions").add("flexsys_kds_screen", FlexSysKdsScreen);
