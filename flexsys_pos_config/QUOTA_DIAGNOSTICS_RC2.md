# FLPOS Quota Diagnostics RC2

This release candidate adds non-destructive diagnostics for intermittent
`QuotaExceededError` exceptions across both the Odoo backend and POS tabs.

## Safety properties

- Does not clear localStorage, sessionStorage, IndexedDB, or Cache Storage.
- Does not suppress exceptions or change Odoo error handling.
- Does not send diagnostics to the server or modify database records.
- Stores at most 20 diagnostic snapshots in page memory only.

## When the error appears

1. Open the browser developer tools (F12).
2. Select **Console**.
3. Expand the **FLPOS QUOTA DIAGNOSTIC** group.
4. Run:

```javascript
await window.__flposQuotaDiagnostics__.copyLast()
```

5. Paste the copied JSON into the investigation report.

The snapshot identifies the tab, URL, failing storage API, call stack, browser
storage estimate, IndexedDB database names, and approximate Web Storage sizes.
