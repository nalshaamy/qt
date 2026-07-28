# RC2 QA Protocol

1. Upgrade the module on staging.
2. Hard refresh Backend and POS tabs.
3. Confirm both status flags are `true`.
4. Reproduce the multi-tab scenario that previously raised the quota popup.
5. Confirm:
   - no Odoo technical error popup appears;
   - POS/offline databases remain present;
   - the `rpc` database is recreated automatically when needed;
   - normal navigation and reports continue working.
6. Capture `getStatus()` after the event.
