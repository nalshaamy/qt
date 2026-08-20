/** @odoo-module **/

import { reactive } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { playBeep, playCancelAlert } from "./kds_audio";

export function makeKdsStore() {
    const state = reactive({
        stations: [],
        currentStationId: false,
        orders: [],
        filter: "all",
        orderTypeFilter: "all",
        priorityFilter: "all",
        employeeFilter: "all",
        companyFilter: "all",
        posConfigFilter: "all",
        connectionStatus: "online",
        lastSync: false,
        loading: false,
        clockLabel: "--:--",
        // Order ids that JUST crossed into fully-Ready on the most recent
        // poll - used by KdsOrderCard to trigger the one-time celebration
        // spin. Plain array (not a Set) since it needs to live on the
        // reactive state for the template to react to it, and Owl's
        // reactive proxying of Set/Map isn't something to rely on.
        celebrateOrderIds: [],
    });

    // Tracks which order ids we've already seen *for the currently
    // selected station*, so we can beep only for genuinely new arrivals -
    // null means "not initialized yet" (never beep on the very first
    // load, or right after switching stations, since every order sitting
    // on screen at that moment would otherwise look "new").
    let knownOrderIds = null;
    // Same idea, for the Ready-transition celebration: which order ids
    // were already fully-Ready as of the last poll.
    let wasReadyIds = new Set();
    // CANCELLATION VISIBILITY (dev request, point 5): tracks which
    // *lines* (not orders - a single item can be cancelled without its
    // order being cancelled at all) were already cancelled as of the
    // last poll, so the alert plays only for genuinely new
    // cancellations, not every poll for as long as a cancelled line
    // stays visible in its own grace window - same null-until-first-
    // load pattern as knownOrderIds above, for the same reason.
    let knownCancelledLineIds = null;
    // REALTIME VALIDATION (dev request, "no duplicate orders or
    // transitions may occur because Bus + polling both receive the same
    // event"): state.orders is always a full replace (never an append/
    // merge - see loadOrders() below), so literal duplicate order
    // records in state were never structurally possible. What genuinely
    // could happen: Bus and the polling fallback can both trigger
    // loadOrders() close together, and if the two resulting RPC calls
    // happen to resolve *out of order* (network jitter - the request
    // that started later resolving before the one that started earlier),
    // the state could very briefly regress to a slightly staler snapshot
    // than what was already showing, until the next refresh corrects it.
    // Not a "duplicate" in the strict sense, but still worth closing -
    // this sequence-number guard discards any response that's no longer
    // the most recently *issued* request by the time it resolves. As a
    // bonus, this same guard also closes a second, separate race found
    // while reviewing this: switching stations (setStation() below)
    // starts a new loadOrders() call, but a still-in-flight call for the
    // *previous* station (kicked off by Bus/polling right before the
    // switch) could otherwise resolve afterward and overwrite state with
    // the wrong station's orders - its lower sequence number now gets it
    // discarded the same way.
    let loadOrdersSeq = 0;

    async function loadStations() {
        state.stations = await rpc("/flexsys_kds/stations", {});
        if (!state.currentStationId && state.stations.length) {
            state.currentStationId = state.stations[0].id;
        }
    }

    async function loadOrders() {
        if (!state.currentStationId) {
            return;
        }
        const mySeq = ++loadOrdersSeq;
        state.loading = true;
        try {
            const orders = await rpc("/flexsys_kds/orders", {
                station_id: state.currentStationId,
            });
            // Discard this response if a newer loadOrders() call has
            // been issued since this one started - see loadOrdersSeq's
            // own comment above for why this matters (Bus + polling
            // resolving out of order).
            if (mySeq !== loadOrdersSeq) {
                return;
            }
            const isFirstLoad = knownOrderIds === null;
            const newIds = new Set(orders.map((o) => o.id));
            if (!isFirstLoad) {
                const hasNewArrival = [...newIds].some((id) => !knownOrderIds.has(id));
                if (hasNewArrival) playBeep();
            }
            knownOrderIds = newIds;

            // CANCELLATION VISIBILITY (dev request, point 5: "clearly
            // distinguishable cancellation notification/sound so kitchen
            // staff notice it quickly"): fires for a newly-cancelled
            // *line*, whether it's a single item cancelled on an
            // otherwise-active order, or every line on a fully-cancelled
            // order (each line's own cancelled_at still gets set
            // individually by the cascade - see
            // kds_order.py::action_cancel() - so this same per-line
            // check naturally covers both cases without needing separate
            // logic for "was this a full-order cancel").
            const cancelledLineIds = new Set(
                orders.flatMap((o) => o.lines.filter((l) => l.state === "cancelled").map((l) => l.id))
            );
            const isFirstCancelCheck = knownCancelledLineIds === null;
            if (!isFirstCancelCheck) {
                const hasNewCancellation = [...cancelledLineIds].some((id) => !knownCancelledLineIds.has(id));
                if (hasNewCancellation) playCancelAlert();
            }
            knownCancelledLineIds = cancelledLineIds;

            const nowReadyIds = new Set(
                // Excludes cancelled lines from the "all ready" check -
                // same activeLines() principle used throughout
                // kds_order_card.js (a cancelled item must never block
                // or misrepresent whether the rest of an order's
                // production has finished).
                orders.filter((o) => {
                    const lines = o.lines.filter((l) => l.state !== "cancelled");
                    return lines.length > 0 && lines.every((l) => l.state === "ready");
                }).map((o) => o.id)
            );
            state.celebrateOrderIds = isFirstLoad
                ? []
                : [...nowReadyIds].filter((id) => !wasReadyIds.has(id));
            wasReadyIds = nowReadyIds;

            state.orders = orders;
            state.connectionStatus = "online";
            state.lastSync = new Date();
        } catch (e) {
            if (mySeq !== loadOrdersSeq) {
                return;
            }
            state.connectionStatus = "offline";
        } finally {
            if (mySeq === loadOrdersSeq) {
                state.loading = false;
            }
        }
    }

    async function refreshAll() {
        await loadStations();
        await loadOrders();
    }

    async function setStation(stationId) {
        state.currentStationId = stationId;
        knownOrderIds = null; // reset - don't beep for orders already on the new station
        wasReadyIds = new Set(); // reset - don't celebrate orders already Ready on the new station
        knownCancelledLineIds = null; // reset - don't alert for cancellations already on the new station
        await loadOrders();
    }

    async function lineAction(lineId, action, reason) {
        await rpc("/flexsys_kds/line/action", { line_id: lineId, action, reason });
        await loadOrders();
    }

    async function orderAction(orderId, action) {
        await rpc("/flexsys_kds/order/action", { order_id: orderId, action });
        await loadOrders();
    }

    async function reprint(orderId, stationId, reason, reasonNote) {
        // UI/DATA FIX ("Printing Cleanup & Job History - Final
        // Request"), item 3: the RPC's own result is now returned to
        // the caller instead of being discarded - the backend can now
        // genuinely fail this call (no printer configured for the
        // station), and the caller (kds_app.js's own onPrintClick)
        // needs the result to show the required Toast rather than
        // silently doing nothing, which is what happened before this
        // fix for every failure path here, not just this new one.
        return await rpc("/flexsys_kds/print/reprint", {
            order_id: orderId,
            station_id: stationId,
            reason,
            reason_note: reasonNote,
        });
    }

    function setFilter(filter) {
        state.filter = filter;
    }

    function setOrderTypeFilter(value) {
        state.orderTypeFilter = value;
    }

    function setPriorityFilter(value) {
        state.priorityFilter = value;
    }

    function setEmployeeFilter(value) {
        state.employeeFilter = value;
    }

    function setCompanyFilter(value) {
        state.companyFilter = value;
    }

    function setPosConfigFilter(value) {
        state.posConfigFilter = value;
    }

    let pollHandle = false;
    function startPolling(intervalMs = 4000) {
        stopPolling();
        pollHandle = setInterval(loadOrders, intervalMs);
    }
    function stopPolling() {
        if (pollHandle) {
            clearInterval(pollHandle);
            pollHandle = false;
        }
    }

    return {
        state,
        loadStations,
        loadOrders,
        refreshAll,
        setStation,
        lineAction,
        orderAction,
        reprint,
        setFilter,
        setOrderTypeFilter,
        setPriorityFilter,
        setEmployeeFilter,
        setCompanyFilter,
        setPosConfigFilter,
        startPolling,
        stopPolling,
    };
}
