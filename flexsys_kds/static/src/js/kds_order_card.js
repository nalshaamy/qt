/** @odoo-module **/

import { Component } from "@odoo/owl";
import { KDS_LABELS } from "./kds_i18n";

export class KdsOrderCard extends Component {
    static template = "flexsys_kds.OrderCard";
    static props = {
        order: Object,
        onLineAction: Function,
        onOrderAction: Function,
        onPrintClick: Function,
        printingEnabled: Boolean,
        celebrate: Boolean,
    };

    setup() {
        this.labels = KDS_LABELS;
    }

    // CANCELLATION VISIBILITY (dev request): a cancelled line must never
    // count toward "is this order still waiting on something" -
    // matching the backend's own established pattern for the exact same
    // question (kds_order.py's is_expeditor_ready already filters
    // `l.state != 'cancelled'` before checking readiness). Before this
    // existed, a single cancelled item on an otherwise-fully-ready order
    // would make every "all lines done" check below return false
    // forever (a cancelled line never satisfies state === 'ready'/
    // 'completed'), silently blocking the order from ever reaching its
    // own Complete button - a real, separate bug this feature surfaced
    // while implementing it, not just a display change.
    get activeLines() {
        return this.props.order.lines.filter((l) => l.state !== "cancelled");
    }

    get borderClass() {
        // CANCELLATION VISIBILITY (dev request, point 2): takes priority
        // over everything else - a fully-cancelled order needs no
        // further alert-coloring (late/warning/priority all stop
        // mattering once there's nothing left to prepare).
        if (this.props.order.state === "cancelled") return "fs-card-cancelled";
        // 'completed' counts the same as 'ready' here (both are "done" -
        // green border) - the real COMPLETED tab (dev request) distinguishes
        // them at the tab/statusText level, not the border color.
        const lines = this.activeLines;
        const allReady = lines.length > 0 && lines.every((l) => l.state === "ready" || l.state === "completed");
        if (this.props.order.sla_status === "late") return "fs-card-late";
        if (allReady) return "fs-card-ready";
        if (this.props.order.sla_status === "warning") return "fs-card-warning";
        if (this.props.order.priority !== "normal") return "fs-card-priority";
        return "fs-card-normal";
    }

    get statusText() {
        // CANCELLATION VISIBILITY (dev request, point 2: "the operator
        // must immediately understand that the entire order has been
        // cancelled") takes priority - checked before Completed, since a
        // cancelled order was never going to complete.
        if (this.props.order.state === "cancelled") return this.labels.filterCancelled || "CANCELLED";
        // Real COMPLETED tab (dev request): explicitly distinguishes
        // Completed from merely-Ready now, keyed off the authoritative
        // order.state - previously both showed "READY" indistinguishably.
        // Everything else here is still deliberately computed from this
        // station's own lines (matching borderClass's own logic) rather
        // than the order-level `state` field for the New/Preparing cases,
        // which reflects the *whole* multi-station order and can lag
        // behind what this specific station's screen should show (e.g.
        // still "Preparing" overall while this station's own items are
        // already all Ready, waiting on another station) - Completed is
        // the one case where the order-level state is exactly right to
        // check directly, since only the order itself (not a per-station
        // view of it) is ever actually marked Completed.
        if (this.props.order.state === "completed") return this.labels.filterCompleted;
        const lines = this.activeLines;
        const allReady = lines.length > 0 && lines.every((l) => l.state === "ready" || l.state === "completed");
        const anyNew = lines.some((l) => l.state === "new" || l.state === "accepted");
        // REAL BUG FIX, confirmed at runtime (dev request "Runtime
        // Regression Fix Package", BUG-02/02B): anyStarted checked
        // BEFORE anyNew below - previously anyNew alone decided "NEW"
        // status, meaning a single freshly-added line (a POS Delta
        // adding one more item to an order already Preparing/Ready)
        // made the *entire* card flip back to showing "NEW" and
        // "START", even while other lines on the same order were
        // already Preparing/Ready/Completed - reading exactly like "the
        // complete order had never started" even though the order's own
        // state field never actually changed and nothing was actually
        // lost. "PREPARING" now correctly takes priority whenever *any*
        // line has been touched already, regardless of whether a
        // newly-added line also needs its own Start - the Start button/
        // action itself (see mainAction below) still correctly targets
        // that specific new line either way; only the status text was
        // misleading.
        const anyStarted = lines.some((l) => l.state === "preparing" || l.state === "ready" || l.state === "completed");
        if (allReady) return this.labels.filterReady;
        if (anyStarted) return this.labels.filterPreparing;
        if (anyNew) return this.labels.filterNew;
        return this.labels.filterPreparing;
    }

    get elapsedLabel() {
        if (!this.props.order.created_time) return "";
        const created = new Date(this.props.order.created_time);
        const diffMin = Math.floor((Date.now() - created.getTime()) / 60000);
        const h = Math.floor(diffMin / 60);
        const m = diffMin % 60;
        // Deliberately kept as digits (not translated) - a timer reading
        // "12:04" is universally understood the same way a clock is.
        return h > 0 ? `${h}:${String(m).padStart(2, "0")}` : `${m} min`;
    }

    get orderedAtLabel() {
        if (!this.props.order.created_time) return "";
        return new Date(this.props.order.created_time).toLocaleTimeString(
            [], { hour: "2-digit", minute: "2-digit" }
        );
    }

    get mainAction() {
        // CANCELLATION VISIBILITY (dev request, point 2): a fully-
        // cancelled order has nothing left to action at all.
        if (this.props.order.state === "cancelled") {
            return { action: null, label: this.labels.filterCancelled || "CANCELLED" };
        }
        const lines = this.activeLines;
        const anyNew = lines.some((l) => l.state === "new");
        const anyAccepted = lines.some((l) => l.state === "accepted");
        const anyPreparing = lines.some((l) => l.state === "preparing");
        if (anyNew || anyAccepted) return { action: "start", label: this.labels.actionStart };
        if (anyPreparing) return { action: "ready", label: this.labels.actionReady };
        // DESIGN REVERSAL (v5.4 - see kds_order.py::action_ready()'s own
        // docstring): reaching Ready no longer auto-completes. Every
        // line Ready/Completed no longer means "nothing left to do" on
        // its own - order.state is what distinguishes "sitting at Ready,
        // needs a deliberate Complete tap" from "already Completed,
        // sitting in its (now 10-minute) on-screen grace period" - both
        // have identical line states, so line state alone can't tell
        // them apart anymore.
        const allLinesDone = lines.length > 0 && lines.every((l) => l.state === "ready" || l.state === "completed");
        if (allLinesDone) {
            if (this.props.order.state === "completed") {
                return { action: null, label: this.labels.actionDone || "DONE" };
            }
            return { action: "complete_order", label: this.labels.actionComplete };
        }
        return { action: "ready", label: this.labels.actionReady };
    }

    get hasCustomerName() {
        const order = this.props.order;
        return Boolean(order.customer_name) && order.customer_name !== order.pos_reference;
    }

    _lineNextAction(state) {
        // Mirrors kds_order_line.py's LINE_TRANSITIONS: 'ready' is only a
        // valid move FROM 'preparing', not from 'new'/'accepted'.
        // Computing each line's own next action (rather than applying one
        // action to every line on the card) avoids a silently-failing
        // invalid-transition call when a single order has lines in
        // different states at once (e.g. one item already Preparing
        // while another hasn't been Started yet). 'cancelled' correctly
        // falls through to null here already (not explicitly listed) -
        // a cancelled line has no next action, matching point 1's
        // "no longer interactive" requirement.
        if (state === "new" || state === "accepted") return "start";
        if (state === "preparing") return "ready";
        return null;
    }

    onMainActionClick() {
        const action = this.mainAction.action;
        if (action === "complete_order") {
            // Order-level action (not per-line) - the new manual
            // Complete step, via the same onOrderAction prop already
            // used elsewhere (reopen/cancel from the backend form).
            this.props.onOrderAction(this.props.order.id, "complete");
            return;
        }
        for (const line of this.activeLines) {
            const lineAction = this._lineNextAction(line.state);
            if (lineAction) {
                this.props.onLineAction(line.id, lineAction);
            }
        }
    }

    onLineCheckboxClick(line) {
        // Checkbox on a single line - advances just that one item, unlike
        // the card's main button which advances every remaining line.
        const action = this._lineNextAction(line.state);
        if (action) {
            this.props.onLineAction(line.id, action);
        }
    }

    lineCheckboxClass(line) {
        // Four visual states: empty (new/accepted, not started), blue
        // with a dash (preparing - in progress), green with a checkmark
        // (ready/completed), grey with an X (cancelled - new, dev
        // request "Cancellation Visibility Improvement"). 'completed' is
        // reachable here too - the grace-period fix (see controller's
        // COMPLETED_GRACE_MINUTES) keeps a just-finished order's lines
        // visible for a few minutes after the whole order auto-
        // completes, and those lines do get bumped to 'completed' by
        // that cascade - must still show as checked, not silently fall
        // through to empty.
        if (line.state === "cancelled") return "fs-cancelled";
        if (line.state === "ready" || line.state === "completed") return "fs-checked";
        if (line.state === "preparing") return "fs-in-progress";
        return "";
    }

    onPrintClick() {
        if (this.props.printingEnabled) {
            this.props.onPrintClick(this.props.order.id);
        }
    }

    cleanVariantInfo(text) {
        // The POS attribute-selection flow this reads from returns full
        // "question: answer" text per attribute (e.g. "Cup type (choose
        // one): paper cup"), joined with ", " for multiple attributes.
        // Keeping only the part after each segment's last ":" gives just
        // the selected values ("paper cup, medium, +30g") without the
        // verbose questions - a display-only cleanup; the raw
        // kds.order.line.variant_info value is untouched.
        if (!text) return "";
        return text.split(", ").map((part) => {
            const idx = part.lastIndexOf(":");
            return idx === -1 ? part.trim() : part.slice(idx + 1).trim();
        }).join(", ");
    }
}
