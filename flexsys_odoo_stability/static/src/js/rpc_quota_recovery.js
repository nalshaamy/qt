/** @odoo-module **/

/**
 * FlexSys Odoo Stability — RPC IndexedDB quota recovery.
 *
 * Scope is deliberately narrow:
 * - Detect quota failures in the browser.
 * - Automatically delete ONLY Odoo's disposable `rpc` cache database.
 * - Never delete POS/offline databases or business data.
 * - Coordinate recovery across open tabs.
 *
 * This is a compatibility guard for Odoo 19 environments where a quota
 * exception can escape the RPC cache recovery path. It is safe to remove once
 * the running Odoo revision reliably includes the upstream recovery behavior.
 */

const GLOBAL_KEY = "__flexsysOdooStabilityInstalled__";
const API_KEY = "__flexsysOdooStability__";
const RPC_DB_NAME = "rpc";
const CHANNEL_NAME = "flexsys_odoo_stability";
const RECOVERY_COOLDOWN_MS = 15_000;
const DELETE_RETRY_MS = 750;
const MAX_DELETE_RETRIES = 4;

if (!globalThis[GLOBAL_KEY]) {
    globalThis[GLOBAL_KEY] = true;

    const state = {
        installedAt: new Date().toISOString(),
        recoveryInProgress: false,
        lastRecoveryAt: 0,
        lastEvent: null,
        lastResult: null,
        transactionPatchInstalled: false,
    };

    let channel = null;
    try {
        channel = new BroadcastChannel(CHANNEL_NAME);
    } catch {
        // BroadcastChannel is optional. Recovery still works in this tab.
    }

    function serializeError(error) {
        if (!error) {
            return null;
        }
        return {
            name: String(error.name || ""),
            message: String(error.message || error || ""),
            stack: String(error.stack || ""),
        };
    }

    function isQuotaExceeded(error, seen = new Set()) {
        if (!error || seen.has(error)) {
            return false;
        }
        if (typeof error === "object") {
            seen.add(error);
        }

        const name = String(error.name || "").toLowerCase();
        const message = String(error.message || error || "").toLowerCase();
        if (
            name.includes("quotaexceeded") ||
            name.includes("idbquotaexceeded") ||
            message.includes("quota exceeded") ||
            message.includes("quotaexceeded") ||
            message.includes("idbquotaexceeded")
        ) {
            return true;
        }
        return isQuotaExceeded(error.cause, seen) || isQuotaExceeded(error.reason, seen);
    }

    async function storageEstimate() {
        try {
            if (!navigator.storage?.estimate) {
                return null;
            }
            const estimate = await navigator.storage.estimate();
            return {
                usage: estimate.usage ?? null,
                quota: estimate.quota ?? null,
                usageDetails: estimate.usageDetails ?? null,
            };
        } catch (error) {
            return { error: serializeError(error) };
        }
    }

    function databaseExists(name) {
        if (!indexedDB.databases) {
            return Promise.resolve(null);
        }
        return indexedDB
            .databases()
            .then((databases) => databases.some((database) => database.name === name))
            .catch(() => null);
    }

    function deleteDatabaseOnce(name) {
        return new Promise((resolve) => {
            let settled = false;
            const finish = (result) => {
                if (!settled) {
                    settled = true;
                    resolve(result);
                }
            };

            let request;
            try {
                request = indexedDB.deleteDatabase(name);
            } catch (error) {
                finish({ status: "error", error: serializeError(error) });
                return;
            }

            request.onsuccess = () => finish({ status: "deleted" });
            request.onerror = () =>
                finish({ status: "error", error: serializeError(request.error) });
            request.onblocked = () => finish({ status: "blocked" });
        });
    }

    async function deleteRpcDatabase() {
        for (let attempt = 1; attempt <= MAX_DELETE_RETRIES; attempt++) {
            const result = await deleteDatabaseOnce(RPC_DB_NAME);
            if (result.status === "deleted") {
                return { ...result, attempt };
            }
            if (result.status !== "blocked") {
                return { ...result, attempt };
            }
            await new Promise((resolve) => setTimeout(resolve, DELETE_RETRY_MS * attempt));
        }
        return { status: "blocked", attempt: MAX_DELETE_RETRIES };
    }

    async function recoverRpcCache(source, error = null) {
        const now = Date.now();
        if (state.recoveryInProgress || now - state.lastRecoveryAt < RECOVERY_COOLDOWN_MS) {
            return { status: "skipped", reason: "cooldown-or-in-progress" };
        }

        state.recoveryInProgress = true;
        state.lastRecoveryAt = now;
        state.lastEvent = {
            at: new Date(now).toISOString(),
            source,
            url: location.href,
            visibility: document.visibilityState,
            error: serializeError(error),
            storageBefore: await storageEstimate(),
            rpcDatabaseExisted: await databaseExists(RPC_DB_NAME),
        };

        try {
            channel?.postMessage({ type: "recovery-started", at: now, source });
            const deletion = await deleteRpcDatabase();
            state.lastResult = {
                at: new Date().toISOString(),
                deletion,
                storageAfter: await storageEstimate(),
            };
            channel?.postMessage({ type: "recovery-finished", result: state.lastResult });

            if (deletion.status === "deleted") {
                console.warn(
                    "[FlexSys Stability] Odoo RPC cache was reset after a quota error. " +
                        "POS/offline databases were not touched."
                );
            } else {
                console.error("[FlexSys Stability] RPC cache recovery did not complete.", deletion);
            }
            return state.lastResult;
        } finally {
            state.recoveryInProgress = false;
        }
    }

    function handlePossibleQuota(source, error) {
        if (isQuotaExceeded(error)) {
            void recoverRpcCache(source, error);
        }
    }

    function installRpcTransactionObserver() {
        const prototype = globalThis.IDBDatabase?.prototype;
        if (!prototype || prototype.__flexsysRpcObserverInstalled__) {
            return false;
        }

        const originalTransaction = prototype.transaction;
        Object.defineProperty(prototype, "__flexsysRpcObserverInstalled__", {
            value: true,
            configurable: false,
            enumerable: false,
            writable: false,
        });

        prototype.transaction = function (...args) {
            const transaction = originalTransaction.apply(this, args);
            if (this.name === RPC_DB_NAME) {
                const inspect = () => {
                    const error = transaction.error;
                    handlePossibleQuota("rpc-indexeddb-transaction", error);
                };
                transaction.addEventListener("abort", inspect);
                transaction.addEventListener("error", inspect);
            }
            return transaction;
        };
        state.transactionPatchInstalled = true;
        return true;
    }

    addEventListener("unhandledrejection", (event) => {
        handlePossibleQuota("unhandledrejection", event.reason);
    });

    addEventListener("error", (event) => {
        handlePossibleQuota("window-error", event.error || event.message);
    });

    channel?.addEventListener("message", (event) => {
        if (event.data?.type === "recovery-started") {
            state.lastRecoveryAt = Math.max(state.lastRecoveryAt, Number(event.data.at) || 0);
        }
    });

    installRpcTransactionObserver();

    globalThis[API_KEY] = Object.freeze({
        getStatus() {
            return typeof structuredClone === "function"
                ? structuredClone(state)
                : JSON.parse(JSON.stringify(state));
        },
        async recoverRpcCache() {
            return recoverRpcCache("manual");
        },
        async inspect() {
            return {
                state: this.getStatus(),
                storage: await storageEstimate(),
                databases: indexedDB.databases ? await indexedDB.databases() : null,
            };
        },
    });
}
