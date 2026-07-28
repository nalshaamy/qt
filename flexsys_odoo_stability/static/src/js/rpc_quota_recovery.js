/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { IndexedDB, IDBQuotaExceededError } from "@web/core/utils/indexed_db";

/**
 * FlexSys Odoo Stability — preventive RPC IndexedDB quota guard.
 *
 * The `rpc` IndexedDB database is a disposable web-client cache. A failed
 * write must never become a user-facing UncaughtPromiseError. This module
 * catches the quota failure at the IndexedDB write boundary, resets only the
 * `rpc` database, and resolves the optional cache write gracefully.
 *
 * POS/offline databases and business data are never deleted.
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
        version: "19.0.1.1.0-rc2",
        installedAt: new Date().toISOString(),
        recoveryInProgress: false,
        lastRecoveryAt: 0,
        lastEvent: null,
        lastResult: null,
        preventiveWritePatchInstalled: false,
        unhandledGuardInstalled: false,
        preventedUnhandledErrors: 0,
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

        if (error instanceof IDBQuotaExceededError) {
            return true;
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

    async function recoverRpcCache(source, error = null, indexedDbInstance = null) {
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

            // Prefer Odoo's own IndexedDB wrapper. It serializes deletion through
            // its mutex and is the safest path while a cache write is failing.
            let deletion;
            if (indexedDbInstance?.name === RPC_DB_NAME) {
                try {
                    await indexedDbInstance.deleteDatabase();
                    deletion = { status: "deleted", method: "odoo-indexeddb-wrapper" };
                } catch (deleteError) {
                    deletion = {
                        status: "error",
                        method: "odoo-indexeddb-wrapper",
                        error: serializeError(deleteError),
                    };
                }
            } else {
                deletion = await deleteRpcDatabase();
            }

            state.lastResult = {
                at: new Date().toISOString(),
                deletion,
                storageAfter: await storageEstimate(),
            };
            channel?.postMessage({ type: "recovery-finished", result: state.lastResult });

            if (deletion.status === "deleted") {
                console.warn(
                    "[FlexSys Stability] RPC cache write was safely skipped and the disposable " +
                        "rpc database was reset. POS/offline databases were not touched."
                );
            } else {
                console.error("[FlexSys Stability] RPC cache recovery did not complete.", deletion);
            }
            return state.lastResult;
        } finally {
            state.recoveryInProgress = false;
        }
    }

    function installPreventiveWritePatch() {
        if (IndexedDB.prototype.__flexsysPreventiveQuotaPatch__) {
            state.preventiveWritePatchInstalled = true;
            return;
        }

        Object.defineProperty(IndexedDB.prototype, "__flexsysPreventiveQuotaPatch__", {
            value: true,
            configurable: false,
            enumerable: false,
            writable: false,
        });

        patch(IndexedDB.prototype, {
            async write(table, key, value) {
                try {
                    return await super.write(table, key, value);
                } catch (error) {
                    if (this.name !== RPC_DB_NAME || !isQuotaExceeded(error)) {
                        throw error;
                    }

                    // RPC disk caching is an optional optimization. Returning
                    // successfully here preserves the real RPC result already
                    // held in RAM and prevents a user-facing rejected promise.
                    await recoverRpcCache("rpc-write-preventive-guard", error, this);
                    return undefined;
                }
            },
        });
        state.preventiveWritePatchInstalled = true;
    }

    function installUnhandledGuard() {
        const guard = (event) => {
            if (!isQuotaExceeded(event.reason)) {
                return;
            }

            // A second safety net for quota rejections created before this module
            // was evaluated or outside RPCCache. Suppress Odoo's technical popup,
            // recover the disposable rpc cache, and leave POS data untouched.
            event.preventDefault();
            event.stopImmediatePropagation?.();
            state.preventedUnhandledErrors += 1;
            void recoverRpcCache("unhandledrejection-safety-net", event.reason);
        };

        addEventListener("unhandledrejection", guard, { capture: true });
        state.unhandledGuardInstalled = true;
    }

    channel?.addEventListener("message", (event) => {
        if (event.data?.type === "recovery-started") {
            state.lastRecoveryAt = Math.max(state.lastRecoveryAt, Number(event.data.at) || 0);
        }
    });

    installPreventiveWritePatch();
    installUnhandledGuard();

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

    console.info("FlexSys Odoo Stability RC2 preventive guard installed", {
        version: state.version,
        preventiveWritePatchInstalled: state.preventiveWritePatchInstalled,
        unhandledGuardInstalled: state.unhandledGuardInstalled,
    });
}
