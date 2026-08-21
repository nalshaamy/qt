/** @odoo-module **/

import { Component } from "@odoo/owl";
import { KDS_LABELS } from "./kds_i18n";

export class KdsOrderCard extends Component {
    static template = "flexsys_kds.OrderCard";
    static props = {
        order: Object,
        onLineAction: Function,
        // BUG-07 FIX: no longer called by this component anywhere (its
        // one call site, completing an order, is now line-level - see
        // onMainActionClick's own "complete_station" branch) - kept
        // declared/wired through (kds_app.js, kds_store.js's own
        // orderAction still exist) rather than removed, in case a
        // genuinely order-level action is ever added back to this card.
        onOrderAction: Function,
        onPrintClick: Function,
        printingEnabled: Boolean,
        celebrate: Boolean,
    };

    setup() {
        this.labels = KDS_LABELS;
    }

    // BUG-09 FIX ("POS Quantity Delta Is Not Explicitly Communicated to
    // Kitchen") - see controllers/kds_kiosk.py's own matching
    // qtyDeltaSuffix() for the full explanation. A plain method (not a
    // getter) since it needs the specific `line` being rendered, called
    // per-line from the template - OWL templates can't cleanly build a
    // conditional string like this inline the way a JS template literal
    // can.
    lineChangeLabel(line) {
        const label = line.line_change_label || line.line_change;
        if (line.line_change !== "updated" || !line.qty_delta) return label;
        const sign = line.qty_delta > 0 ? "+" : "";
        return `${label} (${sign}${line.qty_delta})`;
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

    // BUG-08 FIX ("Cancelled Lines Break Station Card Lifecycle /
    // Terminal Cleanup") - see the matching, more detailed comment on
    // the public kiosk's own stationLifecycle() in controllers/
    // kds_kiosk.py for the full explanation. Same logic here: a station
    // whose every line is terminal (completed and/or cancelled, none
    // genuinely active) is classified two ways - at least one line
    // genuinely 'completed' means this station's work finished
    // (handled by the existing allCompleted getter below); zero
    // completed (every terminal line 'cancelled') means nothing here
    // ever finished, and the card should instead preserve the last
    // operational stage (NEW/PREPARING/READY) this station actually
    // reached before cancellation, per point 1 of the dev request
    // ("Preserve Last Operational State").
    get stationLifecycle() {
        const lines = this.props.order.lines;
        const active = this.activeLines;
        if (active.length > 0) {
            return { hasActiveWork: true };
        }
        const hasAnyCompleted = lines.some((l) => l.state === "completed");
        if (hasAnyCompleted || !lines.length) {
            return { hasActiveWork: false, allCancelled: false };
        }
        const everReady = lines.some((l) => l.ready_time);
        const everPreparing = lines.some((l) => l.preparation_start_time);
        const lastStage = everReady ? "ready" : everPreparing ? "preparing" : "new";
        return { hasActiveWork: false, allCancelled: true, lastStage };
    }

    get borderClass() {
        // CANCELLATION VISIBILITY (dev request, point 2): takes priority
        // over everything else - a fully-cancelled order needs no
        // further alert-coloring (late/warning/priority all stop
        // mattering once there's nothing left to prepare).
        if (this.props.order.state === "cancelled") return "fs-card-cancelled";
        // BUG-08 FIX: a station cancelled with nothing ever completed
        // gets the same muted "cancelled" treatment as a fully-cancelled
        // order, not the "ready" green it would otherwise fall through
        // to once activeLines is empty.
        const lifecycle = this.stationLifecycle;
        if (!lifecycle.hasActiveWork && lifecycle.allCancelled) return "fs-card-cancelled";
        // BUG-10 FIX: driven by order.effective_stage - see
        // kds_app.js's own filteredOrders/counts for the full
        // explanation of why this single backend-authoritative value
        // replaced several separately-maintained local checks.
        // 'completed' counts the same as 'ready' here (both are "done" -
        // green border) - the real COMPLETED tab (dev request) distinguishes
        // them at the tab/statusText level, not the border color.
        const isReadyOrDone = this.props.order.effective_stage === "ready" || this.props.order.effective_stage === "completed";
        // UI/DATA FIX ("Master Change Request", item 28, "Completed
        // Late Visual"): "عند انتقال Late Order إلى Completed... لا
        // يلزم إبقاء البطاقة باللون الأحمر كحالة نشطة." Confirmed
        // live: the 'late' check below used to run unconditionally,
        // before isReadyOrDone was even consulted - a genuinely
        // COMPLETED order that had been Late at some point along the
        // way kept the same red "still urgent" card treatment forever,
        // with nothing distinguishing it from an order that is still
        // active and still actually running late right now. Checked
        // here first instead, but ONLY for 'completed' specifically -
        // not 'ready' (an order that reached Ready but hasn't been
        // handed off/completed yet is still an active state, and a
        // genuinely late one there should keep the red urgency exactly
        // as before). sla_status itself - the underlying data this
        // fix explicitly must not touch ("احتفظ بحقيقة أنه Late في
        // البيانات/Analytics") - is never read, written, or
        // recomputed here; only which CSS class a COMPLETED order's
        // own card resolves to changes.
        if (this.props.order.effective_stage === "completed") return "fs-card-ready";
        if (this.props.order.sla_status === "late") return "fs-card-late";
        if (isReadyOrDone) return "fs-card-ready";
        if (this.props.order.sla_status === "warning") return "fs-card-warning";
        if (this.props.order.priority !== "normal") return "fs-card-priority";
        return "fs-card-normal";
    }

    // BUG-07 FIX ("Station COMPLETE does not transition from READY"):
    // THIS station's own lines specifically - distinct from
    // order.state === "completed", which now only becomes true once
    // EVERY station has completed its own portion (see kds_order.py's
    // is_fully_completed). order.state can no longer be relied on alone
    // to mean "this station's own work here is finished" - on a genuine
    // multi-station order, Kitchen's own card needs to reflect that
    // Kitchen is done independently of whether Coffee/Bar are.
    // BUG-10 FIX: now reads order.effective_stage directly rather than
    // re-deriving it locally.
    get allCompleted() {
        return this.props.order.effective_stage === "completed";
    }

    get statusText() {
        // CANCELLATION VISIBILITY (dev request, point 2: "the operator
        // must immediately understand that the entire order has been
        // cancelled") takes priority - checked before Completed, since a
        // cancelled order was never going to complete.
        if (this.props.order.state === "cancelled") return this.labels.filterCancelled || "CANCELLED";
        // BUG-08 FIX ("visually indicate that the remaining station work
        // is cancelled... the operator should understand: this station
        // was preparing this order, but all remaining work was
        // cancelled"): checked before the rest below, same priority as
        // the fully-cancelled-order case just above. effective_stage
        // for this exact case already returns the *preserved* stage
        // value, which must be labeled as cancelled-at-that-stage here,
        // not mistaken for genuinely active work.
        const lifecycle = this.stationLifecycle;
        const stageLabels = {
            new: this.labels.filterNew, preparing: this.labels.filterPreparing,
            ready: this.labels.filterReady, completed: this.labels.filterCompleted,
        };
        // REAL BUG FIX ("CANCELLED FILTER CLASSIFICATION + RETENTION
        // LIFECYCLE", Issue 1): order.effective_stage itself is now the
        // distinct "cancelled" value for this exact case (see
        // controllers/kds.py's own _effective_stage() docstring for the
        // full explanation of why - "NEW = 6" with all 6 cards
        // genuinely CANCELLED, since effective_stage used to reuse the
        // "preserved last stage" value directly). The "was X" stage
        // label must therefore come from lifecycle.lastStage
        // (stationLifecycle above, computed independently from
        // ever_ready/ever_preparing timestamps) instead of
        // order.effective_stage, which no longer carries that
        // information - looking it up there now would incorrectly read
        // "CANCELLED (was undefined)".
        if (!lifecycle.hasActiveWork && lifecycle.allCancelled) {
            return `${this.labels.filterCancelled || "CANCELLED"} (${this.labels.wasStage || "was"} ${stageLabels[lifecycle.lastStage]})`;
        }
        // BUG-10 FIX: driven by the same single authoritative
        // order.effective_stage every tab filter/count now uses (see
        // kds_app.js's own filteredOrders/counts) - previously a
        // separately-maintained local computation (anyNew/anyStarted/
        // allReady/allCompleted) that happened to mostly agree with the
        // tab logic via BUG-02's own "anyStarted before anyNew"
        // precedence - now there is structurally only one answer to
        // "what stage is this card in", not two parallel
        // implementations that could drift.
        return stageLabels[this.props.order.effective_stage] || this.labels.filterPreparing;
    }

    get elapsedLabel() {
        if (!this.props.order.created_time) return "";
        const created = new Date(this.props.order.created_time);
        const diffMin = Math.floor((Date.now() - created.getTime()) / 60000);
        const h = Math.floor(diffMin / 60);
        const m = diffMin % 60;
        // UI/DATA FIX ("Master Change Request", item 27, "SLA Timer"):
        // "الشاشة الداخلية يفضل توحيد صيغة الوقت معها [الـKiosk] بدل
        // صيغة ملتبسة مثل: 2:28." Confirmed live: this screen's own
        // format ("H:MM", e.g. "2:28") and the public kiosk's own
        // format (controllers/kds_kiosk.py's own elapsed(), matching
        // `${h}h ${m}m` when h > 0, else `${m}m`) genuinely differed -
        // unified to the kiosk's own exact format here instead of the
        // reverse (kiosk left unchanged - it was already the one
        // matching what this fix asks for; the exact same expression
        // is duplicated here, not merely approximated, since this
        // file's own JS cannot import from that separate server-
        // rendered template). The timer's own START POINT
        // (created_time, read above, unchanged) is explicitly not
        // touched - only the digits' own display format.
        return h > 0 ? `${h}h ${m}m` : `${m}m`;
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
        // REAL BUG FIX, confirmed live on Odoo.sh (BUG-08, point 2: "No
        // Active Work = No Workflow Actions... authoritative from
        // backend payload/workflow eligibility, not only hidden with
        // CSS") - checked before effective_stage is even consulted,
        // since a "preserved last stage" of e.g. 'preparing' (BUG-08)
        // must NOT be mistaken for a genuinely active preparing station
        // that still needs a READY tap.
        const lifecycle = this.stationLifecycle;
        if (!lifecycle.hasActiveWork && lifecycle.allCancelled) {
            return { action: null, label: this.labels.filterCancelled || "CANCELLED" };
        }
        // BUG-10 FIX: driven by the same single authoritative
        // order.effective_stage every tab filter/count now uses - see
        // kds_app.js's own filteredOrders/counts, and controllers/
        // kds.py's own _effective_stage(), for the full explanation.
        // BUG-07's own reasoning still applies throughout: computed
        // per-station on the backend, never from the order's own
        // aggregate `state` field, so Kitchen's own button is correct
        // independent of whatever Coffee/Bar are still doing.
        switch (this.props.order.effective_stage) {
            case "new": return { action: "start", label: this.labels.actionStart };
            case "preparing": return { action: "ready", label: this.labels.actionReady };
            case "ready": return { action: "complete_station", label: this.labels.actionComplete };
            case "completed": return { action: null, label: this.labels.filterCompleted };
            default: return { action: null, label: this.labels.filterCancelled || "CANCELLED" };
        }
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
        if (action === "complete_station") {
            // BUG-07 FIX: was an order-level action (onOrderAction,
            // "complete") - completing this station's own ready lines
            // individually instead, through the same onLineAction prop
            // already used for start/ready below, so completion is
            // scoped to exactly this card's own lines and never touches
            // another station's lines on the same order. Only lines
            // actually sitting at "ready" get the call (a line already
            // "completed" - possible mid-batch if this ever races with
            // something else touching the same card - is simply
            // skipped, not re-completed).
            for (const line of this.activeLines) {
                if (line.state === "ready") {
                    this.props.onLineAction(line.id, "complete");
                }
            }
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
