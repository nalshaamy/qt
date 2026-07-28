# FlexSys Odoo Stability 19.0.1.1.0 RC2

Preventive compatibility guard for Odoo 19 RPC IndexedDB quota failures.

## Behavior

- Intercepts failed writes to Odoo's disposable `rpc` IndexedDB cache.
- Resets only the `rpc` database after a confirmed quota failure.
- Resolves the optional disk-cache write so it does not become a user-facing
  `UncaughtPromiseError`.
- Keeps POS/offline databases and business data untouched.
- Includes a final `unhandledrejection` safety net for already-created quota
  rejections.

## Console status

```javascript
window.__flexsysOdooStability__.getStatus()
```

Expected flags:

- `preventiveWritePatchInstalled: true`
- `unhandledGuardInstalled: true`
