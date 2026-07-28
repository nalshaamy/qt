# QA Protocol — FS-SI-001

1. Install or upgrade `flexsys_odoo_stability` on staging.
2. Hard-refresh Backend and POS tabs.
3. Confirm the console API exists:
   `window.__flexsysOdooStability__.getStatus()`
4. Keep Backend and POS open in separate tabs.
5. Exercise normal sales, synchronization, and session closing.
6. On a quota event, capture:
   `await window.__flexsysOdooStability__.inspect()`
7. Verify only database `rpc` is reset.
8. Verify POS databases remain present and orders are not lost.

## Acceptance criteria

- No uncaught quota error from the RPC cache recovery path.
- No deletion of POS/offline databases.
- No duplicate recovery loop across tabs.
- Normal Backend and POS behavior after recovery.
