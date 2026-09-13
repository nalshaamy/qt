# Odoo Apps Publishing Checklist — 19.0.1.0.1

## Store metadata — complete

- [x] Store app name: `POS Device Access`
- [x] Brand / author: `FlexSys`
- [x] Version: `19.0.1.0.1`
- [x] Launch price: `79 USD`
- [x] Support: `info@flexsyssa.com`
- [x] Website: `https://flexsyssa.com`
- [x] License left unchanged
- [x] English HTML description present
- [x] Icon and cover/listing images present
- [x] No external service or activation server required
- [x] Module never creates a `res.users` record automatically; administrator must select an existing Linked POS User

## Static release checks — complete

- [x] Documentation consolidated to avoid duplicate installation/security guides

- [x] Arabic PO entries explicitly bound to `flexsys_pos_device_access`
- [x] No raw Pairing Token field stored in persistent/transient models
- [x] Cashier audit wording uses `Cashier Login Reported`
- [x] Python syntax, XML parsing, JS syntax, manifest references checked
- [x] Package cleaned from Python bytecode/cache and OS metadata
- [x] Package checked for development-host/customer-domain/test-credential strings

## Runtime acceptance — run on a clean Odoo 19 database before publishing

- [ ] Clean Install succeeds
- [ ] Arabic and English UI load correctly
- [ ] Create Device: saving without Linked POS User is blocked
- [ ] Create Device with an existing valid Linked POS User and run Test Device Access
- [ ] Multi-company Linked POS User: device session opens the assigned POS company even when the user's normal active company is different
- [ ] POS frontend receives a non-empty `pos.config` and initializes without `currency_id` errors
- [ ] Device entry performs a fresh server POS-data load and does not reuse a stale empty `pos.config` cache
- [ ] Browser A consumes one-time Pairing Link successfully
- [ ] Multi-database host: generated Pairing Link starts at `/web/login?db=<database>` and carries the pairing secret in `#flexsys_pair=...`
- [ ] Multi-database host: fresh browser selects the intended database without showing the Odoo login form, then continues to pairing
- [ ] Credentials for two databases on the same hostname do not overwrite each other
- [ ] Browser B cannot reuse the consumed Pairing Link
- [ ] Employee PIN remains mandatory
- [ ] Device reaches only its assigned POS
- [ ] Normal Backend navigation is blocked for the device-bound session
- [ ] Cross-POS navigation is blocked
- [ ] Reset Pairing invalidates the existing browser credential
- [ ] Re-pair succeeds after reset
- [ ] Revoke blocks the paired device
- [ ] Uninstall → Install succeeds on the clean test database
- [ ] Capture clean real Odoo 19 screenshots for the store page

No upgrade-from-older-release test is required for the first publication because no prior commercial release has customers.
