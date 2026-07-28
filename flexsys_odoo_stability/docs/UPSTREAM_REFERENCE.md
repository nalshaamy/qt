# Upstream references

- Odoo 19 PR #237075 / merged commit a3e784519725a2e1b88a921ad3f0f0e6de46f3d0
  `[FIX] web: RPCCache: delete db on QuotaExceededError`
- Odoo 19 PR #246476 (forward-ported as #250978)
  `[FIX] point_of_sale: Fix indexedDB race condition on pos init`

This addon implements only the narrow RPC-cache recovery guard. It does not
copy or modify Odoo core source files and does not patch POS database reset
logic.
