/** @odoo-module **/

// PHASE 3 ("POS Direct Auto Print Worker"): the POS Browser's own
// local print executor for server-triggered Auto Print
// (kds.print.job records with source='pos_auto') - the Direct
// Network replacement for the Legacy Print Agent path specifically
// for Printer Only / KDS+Printer-with-Auto-Print-ON stations.
//
// REUSES, NEVER DUPLICATES (per explicit direction, items G):
// - window.FlexSysTicketBuilder.normalizeOrderForTicket() /
//   renderKitchenTicketToCanvas() (static/src/shared/flexsys_ticket_renderer.js,
//   the SAME shared renderer Internal KDS and Public Kiosk already
//   use) - loaded as a plain, non-module <script> in the same POS
//   asset bundle (see __manifest__.py), so it is available here as a
//   global, exactly like it already is on the standalone Public
//   Kiosk page.
// - flexsysPrintViaDirectEpos() (./flexsys_epos_direct_adapter.js,
//   the SAME Direct ePOS transport Internal KDS already uses) -
//   imported as a real ES module, same relative-path pattern already
//   proven by kds_app.js's own import of it.
//
// Ticket quality/layout is therefore IDENTICAL across Internal KDS,
// Public Kiosk, and POS Auto Print - there is only ever one renderer
// and one transport implementation in this whole codebase.
//
// PATCH POINT (item H): patches PosStore.prototype.setup() - the
// SAME confirmed-safe hook point flexsys_kds_offline_send_warning.js
// already uses successfully in this exact module, rather than
// afterProcessServerData() (mentioned only as a suggestion in the
// original request, not something this environment has a live Odoo
// 19 instance available to confirm exists/behaves as expected - see
// this file's own HONEST LIMITATION note further below). setup() is
// called once per POS session with this.config/this.session/
// this.device already populated (the same assumption
// flexsys_kds_offline_send_warning.js's own setup() patch already
// relies on, confirmed working in that file), which is all this
// worker needs to start.
//
// CONFIRMED AGAINST REAL ODOO 19 SOURCE (item 2/3 of this round's own
// verification requirement): fetched the actual, current
// addons/point_of_sale/static/src/app/services/pos_store.js from
// Odoo's own public GitHub repository (19.0 branch) before writing
// this file's own final version, specifically to confirm:
//   - this.data.call(model, method, args) is genuinely the correct
//     signature - Odoo's own core POS code calls it exactly this way
//     itself (e.g. `await this.data.call("pos.order",
//     "cancel_order_from_pos", [Array.from(ids)]);` inside
//     deleteOrders() in that same file) - not a guess.
//   - this.config, this.device are set inside processServerData(),
//     called from initServerData(), called and awaited from the
//     REAL setup() before it returns.
//   - this.session is a GETTER (`get session() { return
//     this.data.models["pos.session"].get(odoo.pos_session_id); }`),
//     resolvable as soon as this.data.models itself is populated -
//     also guaranteed by the time the real setup() finishes.
// This confirms setup() (patched below, NOW WITH `await
// super.setup(...args)` - see that patch's own comment for the real
// bug this fixes) is a safe, correct hook point for this worker -
// afterProcessServerData() was only ever a suggestion in the original
// request, never required over setup() once setup() itself is
// properly awaited.
import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { flexsysPrintViaDirectEpos } from "./flexsys_epos_direct_adapter";

// item M: polling fallback interval - the worker also runs
// immediately after finishing a job and on the browser's own online
// event, this interval is only the periodic fallback for "a job
// became claimable with no other trigger firing" (e.g. a fresh order
// arriving with no online/finish event of its own to react to).
const POLL_INTERVAL_MS = 2000;
const RESULT_STORAGE_PREFIX = "flexsys_kds_direct_print_result:";

function resultStorageKey(jobId) {
    return RESULT_STORAGE_PREFIX + jobId;
}

function readPendingResults() {
    const results = [];
    try {
        for (let i = 0; i < window.localStorage.length; i++) {
            const key = window.localStorage.key(i);
            if (key && key.startsWith(RESULT_STORAGE_PREFIX)) {
                try {
                    results.push(JSON.parse(window.localStorage.getItem(key)));
                } catch (parseError) {
                    // A corrupted/foreign entry under our own prefix -
                    // remove it rather than looping on it forever.
                    window.localStorage.removeItem(key);
                }
            }
        }
    } catch (error) {
        console.error("FlexSys KDS: failed to read pending Direct Auto Print results", error);
    }
    return results;
}

function persistPendingResult(entry) {
    try {
        window.localStorage.setItem(resultStorageKey(entry.job_id), JSON.stringify(entry));
    } catch (error) {
        console.error("FlexSys KDS: failed to persist Direct Auto Print result locally", error);
    }
}

function clearPendingResult(jobId) {
    try {
        window.localStorage.removeItem(resultStorageKey(jobId));
    } catch (error) {
        console.error("FlexSys KDS: failed to clear a reported Direct Auto Print result", error);
    }
}

/**
 * item O: the Adapter's own {successful, errorCode, ...} shape,
 * normalized into a clean {code, message} pair - mirrors the same
 * normalizeDirectPrintError() helper already proven in kds_app.js,
 * duplicated here (not imported) since kds_app.js is not itself an
 * exported module surface this worker should depend on - only the
 * shared renderer/adapter are the intended shared surface (item G).
 */
function normalizeWorkerPrintError(result) {
    if (result && result.errorCode) {
        return { code: result.errorCode, message: result.errorCode };
    }
    return { code: "UNKNOWN", message: "Unknown error" };
}

class FlexSysPosDirectPrintWorker {
    constructor(pos) {
        this.pos = pos;
        this.running = false;
        this.cycleInFlight = false;
    }

    start() {
        // item M: guard against a duplicate worker start - setup()
        // could in principle run more than once in some POS
        // lifecycle edge case; this flag makes start() itself
        // idempotent regardless.
        if (this.running) {
            return;
        }
        this.running = true;

        this._boundOnline = () => this._runCycle();
        window.addEventListener("online", this._boundOnline);

        this._pollTimer = setInterval(() => this._runCycle(), POLL_INTERVAL_MS);

        // Run one cycle immediately at startup too, rather than only
        // after the first poll interval elapses.
        this._runCycle();
    }

    async _runCycle() {
        // item M: no concurrent cycles - a still-running previous
        // cycle (e.g. a slow claim RPC) simply skips this trigger
        // rather than overlapping with it.
        if (this.cycleInFlight) {
            return;
        }
        if (!navigator.onLine) {
            return;
        }
        this.cycleInFlight = true;
        try {
            // item O, step 1: flush any locally-persisted terminal
            // results FIRST, before claiming anything new - a result
            // that already happened (the printer already printed)
            // must never be lost behind a fresh claim attempt.
            //
            // AUDIT FIX ("Version 43 - Final Phase 3 Corrections"),
            // item 2: confirmed - _flushPendingResults() used to
            // catch a failed report RPC internally and return
            // normally either way, so a previously-printed job's own
            // unacknowledged result could sit in localStorage while
            // the worker went ahead and claimed (and physically
            // printed) another job in the SAME cycle. Result-first
            // must genuinely BLOCK new claims when any pending
            // report could not be acknowledged - _flushPendingResults()
            // now returns whether every pending marker was actually
            // acknowledged by the server, and a new claim is only
            // attempted when that's true.
            const allFlushed = await this._flushPendingResults();
            if (!allFlushed) {
                return;
            }
            // AUDIT FIX ("Version 43 - Final Phase 3 Corrections"),
            // item 4: confirmed - the old code called `this._runCycle()`
            // from INSIDE _claimAndPrintOne(), while the OUTER
            // _runCycle() invocation still had cycleInFlight=true set -
            // that inner call exited immediately on its own
            // `if (this.cycleInFlight) return;` guard, so "immediately
            // check for another job" never actually happened; only the
            // next 2-second poll tick did. Replaced with a genuine
            // sequential loop HERE instead: each iteration fully
            // awaits _claimAndPrintOne() (one claim RPC, one physical
            // print attempt, one result report) before the next
            // iteration even starts - still exactly one job claimed
            // and printed at a time, never concurrently, per the
            // explicit "sequential one-at-a-time execution remains
            // mandatory" requirement. The loop naturally stops the
            // first time there's nothing left to claim.
            // eslint-disable-next-line no-await-in-loop
            while (await this._claimAndPrintOne()) {
                // Intentionally empty - see comment above.
            }
        } catch (error) {
            console.error("FlexSys KDS: Direct Auto Print worker cycle failed", error);
        } finally {
            this.cycleInFlight = false;
        }
    }

    /**
     * @returns {Promise<boolean>} true only if every locally-persisted
     * pending result BELONGING TO THE CURRENT SESSION was successfully
     * reported to and acknowledged by the server this cycle (or there
     * were none to begin with) - false if at least one CURRENT-session
     * report RPC failed/dropped, in which case the caller must not
     * proceed to claim a new job this cycle. A stale marker belonging
     * to a DIFFERENT (older) POS session never affects this return
     * value either way - see the AUDIT FIX comment below for why.
     */
    async _flushPendingResults() {
        const pending = readPendingResults();
        let allFlushed = true;
        const currentSessionId = this.pos.session && this.pos.session.id;
        const currentSessionAccessToken = this.pos.session && this.pos.session.access_token;
        for (const entry of pending) {
            // AUDIT FIX ("Version 47 continuation - do not persist
            // access_token; result retry behavior"): the pending
            // marker itself never stores a session token (see
            // persistPendingResult()'s own call site below) - only
            // pos_session_id, which identifies WHICH session the
            // result belongs to. If that matches the CURRENT session
            // (covers: plain polling retry, a page reload within the
            // same session, or a different authenticated user opening
            // the SAME Odoo POS session later - Odoo 19's own session
            // identity/token are still exactly the same in all three
            // cases), the current in-memory access_token is used to
            // retry the report - never a token read from storage.
            //
            // If the marker belongs to a DIFFERENT, older session
            // (e.g. the POS was closed and reopened as a new session
            // since that job was printed), this worker must NOT use
            // the CURRENT session's own token to report a result for
            // a job that session never claimed - report_pos_direct_
            // auto_result() would reject it anyway
            // (direct_executor_pos_session_id mismatch), but more
            // importantly, retrying it here would eventually
            // (wrongly) resolve into a report attempt with the wrong
            // credentials. Such a stale marker is safely discarded
            // here instead: the server-side lifecycle (claim_deadline/
            // dispatch_deadline crons) is the actual, authoritative
            // mechanism that resolves that OLD job's own state
            // (typically RESULT_TIMEOUT, since no executor for the
            // new session will ever claim/report it again) - this is
            // purely a local cleanup so a stale marker can never block
            // the CURRENT session's own claims indefinitely. Discarding
            // it here counts as neither success nor failure for the
            // CURRENT session's own allFlushed result.
            if (entry.pos_session_id !== currentSessionId) {
                console.error(
                    "FlexSys KDS: discarding a stale Direct Auto Print result marker "
                        + "from a different POS session (job_id=" + entry.job_id + ") - "
                        + "the server-side timeout lifecycle will resolve that job instead."
                );
                clearPendingResult(entry.job_id);
                continue;
            }
            if (!currentSessionAccessToken) {
                // Server data not ready yet for the current session -
                // cannot safely retry now; leave the marker in place
                // and try again next cycle.
                allFlushed = false;
                continue;
            }
            try {
                await this.pos.data.call("kds.print.job", "report_pos_direct_auto_result", [
                    entry.job_id,
                    entry.pos_session_id,
                    currentSessionAccessToken,
                    entry.executor_id,
                    entry.successful,
                    entry.error_code || false,
                    entry.error_message || false,
                ]);
                // item O: only removed once the server has actually
                // acknowledged the report - a failed/dropped RPC here
                // leaves the marker in place for the next cycle to
                // retry, exactly as required.
                clearPendingResult(entry.job_id);
            } catch (error) {
                // Deliberately logs only the error object itself,
                // never `entry` as a whole and never the session
                // token (which is never stored in `entry` at all, nor
                // read from anywhere but the live this.pos.session
                // getter above) - the session token must never appear
                // in console/audit text.
                console.error(
                    "FlexSys KDS: failed to report a pending Direct Auto Print result "
                        + "(will retry next cycle)",
                    error
                );
                allFlushed = false;
            }
        }
        return allFlushed;
    }

    /**
     * @returns {Promise<boolean>} true ONLY when a job was claimed,
     * physically printed (successful or not - print failure is not
     * this method's own failure), AND its own result was successfully
     * reported to and acknowledged by the server (marker cleared) -
     * the one case where continuing the sequential loop is safe.
     * false covers every other case: nothing to claim, a precondition/
     * claim RPC error, OR (AUDIT FIX, "Version 44") the result report
     * RPC itself failing after a genuine physical print attempt - in
     * that last case a job WAS printed but its own marker deliberately
     * remains in localStorage, unacknowledged, and the caller must NOT
     * claim another job until a later cycle's own _flushPendingResults()
     * successfully reports it.
     */
    async _claimAndPrintOne() {
        const executorId = this.pos.device && this.pos.device.identifier;
        if (!executorId) {
            // No stable device identifier available yet - nothing safe
            // to claim under.
            return false;
        }
        const sessionId = this.pos.session && this.pos.session.id;
        if (!sessionId) {
            return false;
        }
        // AUDIT FIX ("Version 47 - Odoo 19 POS Session Identity
        // Correction"): confirmed against Odoo 19's own real
        // pos_session.py (_load_pos_data_fields() explicitly loads
        // 'access_token' into pos.session data sent to the frontend)
        // and PosStore's own `get session()` getter
        // (this.data.models["pos.session"].get(...)) - by this point
        // (after `await super.setup()` already completed, per the
        // Version 43 fix), this.pos.session.access_token is genuinely
        // available. session.user_id is NOT used anywhere in this
        // file - Odoo 19 itself allows the same session to be used by
        // a different authenticated user than whoever opened it, so
        // the token (not user_id) is the real session-identity proof.
        const sessionAccessToken = this.pos.session && this.pos.session.access_token;
        if (!sessionAccessToken) {
            return false;
        }

        let claimed;
        try {
            claimed = await this.pos.data.call("kds.print.job", "claim_direct_auto_jobs", [
                sessionId,
                sessionAccessToken,
                executorId,
                1,
            ]);
        } catch (error) {
            console.error("FlexSys KDS: Direct Auto Print claim RPC failed", error);
            return false;
        }
        if (!claimed || !claimed.length) {
            return false;
        }

        const payload = claimed[0];
        const normalizedOrder = window.FlexSysTicketBuilder.normalizeOrderForTicket(
            payload.order,
            payload.station_name,
            payload.ticket_status || "NEW",
            payload.branch_name
        );

        const result = await flexsysPrintViaDirectEpos({
            ip: payload.printer_ip,
            useLna: Boolean(payload.use_local_network_access),
            normalizedOrder,
            notificationService: this.pos.notification,
        });

        const successful = Boolean(result && result.successful);
        const normalizedError = successful ? null : normalizeWorkerPrintError(result);
        // item 4 (Version 47): the pending-result marker must carry
        // SECURITY FIX ("Version 47 continuation - Do NOT persist
        // pos.session.access_token in localStorage"): the marker
        // stored here deliberately does NOT include the session
        // token - access_token is a live session capability/
        // credential, and creating a second, persistent copy of it in
        // FlexSys's own localStorage (outside Odoo's own session
        // management) serves no real purpose here: this.pos.session
        // itself already has both the id and the current
        // access_token in memory for as long as the worker is running,
        // and _flushPendingResults() above reads the token fresh from
        // there at retry time - keyed only by pos_session_id, which
        // identifies WHICH session a stored result belongs to without
        // ever needing to store the credential itself.
        const resultEntry = {
            job_id: payload.job_id,
            executor_id: executorId,
            pos_session_id: sessionId,
            successful,
            error_code: normalizedError ? normalizedError.code : false,
            error_message: normalizedError ? normalizedError.message : false,
        };

        // item O: persist the terminal result locally BEFORE
        // attempting to report it - if the report RPC itself fails or
        // the connection drops right after a successful physical
        // print, the next cycle's own _flushPendingResults() retries
        // the REPORT, never the PRINT itself.
        persistPendingResult(resultEntry);

        if (!successful) {
            // item P: a visible, non-blocking, sticky notification on
            // failure - success stays silent, per explicit direction.
            try {
                this.pos.notification.add(
                    `Kitchen auto print failed for ${payload.station_name || "this station"}. `
                        + "Check the printer or local network.",
                    { type: "danger", sticky: true }
                );
            } catch (notifyError) {
                console.error("FlexSys KDS: failed to show Direct Auto Print failure notification", notifyError);
            }
        }

        try {
            await this.pos.data.call("kds.print.job", "report_pos_direct_auto_result", [
                resultEntry.job_id,
                resultEntry.pos_session_id,
                sessionAccessToken,
                resultEntry.executor_id,
                resultEntry.successful,
                resultEntry.error_code,
                resultEntry.error_message,
            ]);
            clearPendingResult(resultEntry.job_id);
            // AUDIT FIX ("Version 44 - One Remaining Worker Runtime
            // Blocker"): confirmed - this method used to unconditionally
            // `return true;` after the try/catch above, regardless of
            // whether the report RPC actually succeeded. That meant a
            // report RPC failure DURING the sequential while loop (as
            // opposed to an already-stale marker caught by
            // _flushPendingResults() at the very START of a cycle) was
            // silently ignored by the loop's own continuation
            // condition - Job A's own result stayed correctly
            // unacknowledged in localStorage, but the loop still
            // claimed and physically printed Job B in the very same
            // cycle. The result-first contract requires that ANY
            // physically-executed print result still unacknowledged by
            // the server blocks every further claim until it's
            // acknowledged - `return true` here (report genuinely
            // acknowledged, marker cleared) is the ONLY case where it's
            // safe for the while loop in _runCycle() to continue.
            return true;
        } catch (error) {
            console.error(
                "FlexSys KDS: failed to report Direct Auto Print result immediately "
                    + "(will retry next cycle)",
                error
            );
            // The marker deliberately stays in localStorage (never
            // cleared here) - the NEXT cycle's own _flushPendingResults()
            // retries only the REPORT, never the physical print itself.
            // Returning false stops the sequential while loop
            // immediately, so no further job is claimed this cycle
            // while Job A's own result remains unacknowledged.
            return false;
        }
    }
}

patch(PosStore.prototype, {
    async setup(...args) {
        // CRITICAL FIX (confirmed by direct read of Odoo 19's own
        // real pos_store.js source, addons/point_of_sale/static/src/
        // app/services/pos_store.js): the ORIGINAL setup() is itself
        // async and internally awaits initServerData() (which sets
        // this.config/this.device and makes this.session - a getter
        // reading this.data.models["pos.session"] - genuinely
        // resolvable) before returning. The prior version of this
        // patch called `super.setup(...args)` WITHOUT awaiting it -
        // since our own setup() override is also async, that meant
        // the worker below could start executing (this.config/
        // this.device/this.session read) BEFORE the real Odoo
        // setup() had actually finished populating them, exactly the
        // failure mode explicitly warned against. `await` here
        // guarantees this.config.id / this.session.id /
        // this.device.identifier / this.data.call / this.notification
        // are all genuinely ready by the time the worker starts.
        await super.setup(...args);
        try {
            // AUDIT FIX ("Version 43 - Final Phase 3 Corrections"),
            // item 3: confirmed - start()'s own `if (this.running)
            // return;` guard only protects a SINGLE worker instance
            // from starting twice; it does nothing if setup() itself
            // runs more than once (a real Odoo POS lifecycle
            // possibility), since a brand-new
            // FlexSysPosDirectPrintWorker was unconditionally created
            // here every time, with its own fresh running=false - a
            // second poll timer and a second 'online' listener would
            // then both keep running forever alongside the first,
            // neither ever cleaned up. The guard now lives at the
            // PosStore level instead: a worker is only ever created
            // and started ONCE per PosStore instance - an existing,
            // already-running worker is never overwritten or
            // duplicated by a later setup() call.
            if (!this._flexsysDirectPrintWorker) {
                this._flexsysDirectPrintWorker = new FlexSysPosDirectPrintWorker(this);
                this._flexsysDirectPrintWorker.start();
            }
        } catch (error) {
            // Never let a worker startup failure break POS startup
            // itself - the cashier's own order flow must never depend
            // on this succeeding.
            console.error("FlexSys KDS: failed to start the Direct Auto Print worker", error);
        }
    },
});
