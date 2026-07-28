# FlexSys Odoo Stability

A narrowly scoped Odoo 19 compatibility addon for browser-storage resilience.

## Current protection

When a browser quota failure reaches the web client, the addon attempts to reset
only the disposable Odoo IndexedDB database named `rpc`. It never deletes:

- `point-of-sale-*`
- `point_of_sale_config_*_logger`
- pending POS orders
- offline POS business data

The behavior follows the intent of Odoo 19 upstream fix `odoo/odoo#237075`:
reset the RPC cache after `QuotaExceededError` so later writes can recover.

## Browser console API

```javascript
await window.__flexsysOdooStability__.inspect()
await window.__flexsysOdooStability__.recoverRpcCache()
window.__flexsysOdooStability__.getStatus()
```

## Installation

Install as a separate technical addon. Do not merge its source into
`flexsys_pos_config`.
