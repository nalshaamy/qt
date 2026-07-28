# Upstream reference

Odoo 19 official change:

- `[FIX] web: RPCCache: delete db on QuotaExceededError`
- Commit: `a3e784519725a2e1b88a921ad3f0f0e6de46f3d0`

RC2 adds a compatibility boundary around `IndexedDB.write()` for the `rpc`
database so the optional cache-write failure is resolved before it reaches
Odoo's global error service.
