/** @odoo-module **/

/**
 * FLPOS browser quota diagnostics (staging / release-candidate instrumentation).
 *
 * This module is intentionally observational:
 * - it does not clear browser data;
 * - it does not suppress or transform errors;
 * - it does not write diagnostic payloads back to browser storage;
 * - it avoids RPC calls and therefore has no database impact.
 *
 * When a quota exception is observed, a structured snapshot is printed in the
 * browser console and retained only in memory at `window.__flposQuotaDiagnostics__`.
 */

const GLOBAL_KEY = "__flposQuotaDiagnostics__";

if (!window[GLOBAL_KEY]?.installed) {
    const state = {
        installed: true,
        version: "19.0.15.3.2-rc2",
        tabId: globalThis.crypto?.randomUUID?.() || `tab-${Date.now()}-${Math.random()}`,
        startedAt: new Date().toISOString(),
        events: [],
        lastSnapshot: null,
    };
    window[GLOBAL_KEY] = state;

    const isQuotaError = (error) => {
        const name = String(error?.name || "");
        const message = String(error?.message || "");
        return (
            name === "QuotaExceededError" ||
            error?.code === 22 ||
            error?.code === 1014 ||
            /quota.*exceed|exceed.*quota/i.test(message)
        );
    };

    const safe = (callback, fallback = null) => {
        try {
            return callback();
        } catch {
            return fallback;
        }
    };

    const approximateStorageBytes = (storage) => {
        if (!storage) {
            return null;
        }
        let characters = 0;
        try {
            for (let index = 0; index < storage.length; index++) {
                const key = storage.key(index) || "";
                const value = storage.getItem(key) || "";
                characters += key.length + value.length;
            }
            // JavaScript strings are normally represented using UTF-16.
            return characters * 2;
        } catch {
            return null;
        }
    };

    const getStorageEstimate = async () => {
        if (!navigator.storage?.estimate) {
            return null;
        }
        try {
            const estimate = await navigator.storage.estimate();
            return {
                usage: estimate.usage ?? null,
                quota: estimate.quota ?? null,
                usagePercent:
                    estimate.quota > 0
                        ? Number(((estimate.usage / estimate.quota) * 100).toFixed(2))
                        : null,
                usageDetails: estimate.usageDetails || null,
            };
        } catch (error) {
            return { estimateError: String(error?.message || error) };
        }
    };

    const getIndexedDbList = async () => {
        if (!indexedDB?.databases) {
            return { supported: false, databases: [] };
        }
        try {
            const databases = await indexedDB.databases();
            return {
                supported: true,
                databases: databases.map((database) => ({
                    name: database.name || null,
                    version: database.version || null,
                })),
            };
        } catch (error) {
            return {
                supported: true,
                databases: [],
                listError: String(error?.message || error),
            };
        }
    };

    const serializeError = (error) => ({
        name: String(error?.name || ""),
        message: String(error?.message || error || ""),
        code: error?.code ?? null,
        stack: String(error?.stack || ""),
        constructor: String(error?.constructor?.name || ""),
    });

    const collectSnapshot = async ({ source, operation = null, error, context = {} }) => {
        const snapshot = {
            diagnosticVersion: state.version,
            timestamp: new Date().toISOString(),
            source,
            operation,
            tab: {
                id: state.tabId,
                url: location.href,
                pathname: location.pathname,
                title: document.title,
                visibilityState: document.visibilityState,
                hasFocus: safe(() => document.hasFocus(), null),
                referrer: document.referrer || null,
            },
            browser: {
                userAgent: navigator.userAgent,
                language: navigator.language,
                online: navigator.onLine,
                hardwareConcurrency: navigator.hardwareConcurrency ?? null,
            },
            storage: {
                estimate: await getStorageEstimate(),
                localStorageApproxBytes: safe(
                    () => approximateStorageBytes(window.localStorage),
                    null
                ),
                sessionStorageApproxBytes: safe(
                    () => approximateStorageBytes(window.sessionStorage),
                    null
                ),
                indexedDB: await getIndexedDbList(),
            },
            error: serializeError(error),
            context,
        };

        state.lastSnapshot = snapshot;
        state.events.push(snapshot);
        if (state.events.length > 20) {
            state.events.shift();
        }

        console.groupCollapsed(
            "%cFLPOS QUOTA DIAGNOSTIC",
            "background:#8b0000;color:#fff;padding:2px 6px;border-radius:3px;font-weight:bold;"
        );
        console.error("Quota exception captured", error);
        console.table({
            source: snapshot.source,
            operation: snapshot.operation,
            tabId: snapshot.tab.id,
            path: snapshot.tab.pathname,
            visibility: snapshot.tab.visibilityState,
            focused: snapshot.tab.hasFocus,
            storageUsage: snapshot.storage.estimate?.usage ?? "unknown",
            storageQuota: snapshot.storage.estimate?.quota ?? "unknown",
            storageUsagePercent: snapshot.storage.estimate?.usagePercent ?? "unknown",
            localStorageApproxBytes: snapshot.storage.localStorageApproxBytes ?? "unknown",
            sessionStorageApproxBytes: snapshot.storage.sessionStorageApproxBytes ?? "unknown",
        });
        console.log("Full diagnostic snapshot (copy this object):", snapshot);
        console.log(
            "Copy helper: await window.__flposQuotaDiagnostics__.copyLast()"
        );
        console.groupEnd();

        return snapshot;
    };

    const capture = (details) => {
        if (!isQuotaError(details.error)) {
            return;
        }
        // Do not block or alter the application's own error propagation.
        void collectSnapshot(details);
    };

    state.getLast = () => state.lastSnapshot;
    state.getEvents = () => [...state.events];
    state.copyLast = async () => {
        const text = JSON.stringify(state.lastSnapshot, null, 2);
        if (!state.lastSnapshot) {
            console.warn("FLPOS: No quota diagnostic snapshot has been captured yet.");
            return null;
        }
        try {
            await navigator.clipboard.writeText(text);
            console.info("FLPOS: Last quota diagnostic copied to clipboard.");
        } catch (error) {
            console.warn("FLPOS: Clipboard copy failed. Copy the returned text manually.", error);
        }
        return text;
    };

    window.addEventListener(
        "unhandledrejection",
        (event) => {
            capture({
                source: "window.unhandledrejection",
                operation: "promise",
                error: event.reason,
                context: { promise: String(event.promise || "") },
            });
        },
        true
    );

    window.addEventListener(
        "error",
        (event) => {
            capture({
                source: "window.error",
                operation: "script",
                error: event.error || new Error(event.message),
                context: {
                    filename: event.filename || null,
                    lineno: event.lineno || null,
                    colno: event.colno || null,
                },
            });
        },
        true
    );

    // Identify synchronous Web Storage writes that exhaust quota.
    const originalStorageSetItem = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
        try {
            return originalStorageSetItem.call(this, key, value);
        } catch (error) {
            capture({
                source: "Storage.setItem",
                operation:
                    safe(() => (this === window.localStorage ? "localStorage.setItem" : null)) ||
                    safe(() => (this === window.sessionStorage ? "sessionStorage.setItem" : null)) ||
                    "Storage.setItem",
                error,
                context: {
                    key: String(key),
                    attemptedValueCharacters: String(value).length,
                    callStack: String(new Error("Storage write call site").stack || ""),
                },
            });
            throw error;
        }
    };

    const instrumentIdbMethod = (methodName) => {
        const prototype = globalThis.IDBObjectStore?.prototype;
        const original = prototype?.[methodName];
        if (typeof original !== "function") {
            return;
        }
        prototype[methodName] = function (...args) {
            const callStack = String(new Error(`IndexedDB ${methodName} call site`).stack || "");
            let request;
            try {
                request = original.apply(this, args);
            } catch (error) {
                capture({
                    source: `IDBObjectStore.${methodName}`,
                    operation: "synchronous-throw",
                    error,
                    context: { storeName: this.name || null, callStack },
                });
                throw error;
            }
            request?.addEventListener?.(
                "error",
                () => {
                    capture({
                        source: `IDBObjectStore.${methodName}`,
                        operation: "request-error",
                        error: request.error,
                        context: { storeName: this.name || null, callStack },
                    });
                },
                { once: true }
            );
            return request;
        };
    };

    instrumentIdbMethod("add");
    instrumentIdbMethod("put");

    // Cache API writes can also surface quota failures.
    const instrumentCacheMethod = (methodName) => {
        const prototype = globalThis.Cache?.prototype;
        const original = prototype?.[methodName];
        if (typeof original !== "function") {
            return;
        }
        prototype[methodName] = async function (...args) {
            try {
                return await original.apply(this, args);
            } catch (error) {
                capture({
                    source: `Cache.${methodName}`,
                    operation: "cache-write",
                    error,
                    context: {
                        request: String(args[0]?.url || args[0] || ""),
                        callStack: String(new Error(`Cache ${methodName} call site`).stack || ""),
                    },
                });
                throw error;
            }
        };
    };

    instrumentCacheMethod("put");
    instrumentCacheMethod("add");
    instrumentCacheMethod("addAll");

    console.info("FLPOS quota diagnostics RC2 installed", {
        version: state.version,
        tabId: state.tabId,
        path: location.pathname,
    });
}
