# Changelog

## 19.0.1.0.1 — Commercial Security Hardening

- Device entry now forces a fresh Odoo POS data bootstrap while still clearing any cached cashier identity so employee PIN verification remains mandatory.

- Fixed Linked POS User company context so Odoo always loads the assigned `pos.config` instead of crashing on `currency_id` when the user's normal active company differs.

- Consolidated commercial documentation: installation moved into the User Guide and security operations moved into SECURITY.md.

- Removed automatic POS Service User creation; device records now require an administrator-selected existing Linked POS User.

- Store release metadata finalized; launch price set to USD 79.
- Multi-database hardening: pairing now bootstraps through Odoo's server-wide `/web/login?db=...` route before entering the database-bound FlexSys controller; device cookies remain namespaced per database.

- Raw one-time Pairing URLs are no longer persisted even in transient wizard rows; the secret is carried only in the one-response action context.
- Cashier audit semantics are now accurate: `Cashier Login Reported` replaces the stronger `Cashier PIN Verified` claim, while Odoo `pos_hr` remains responsible for PIN verification.
- Kept a backward-compatible legacy JSON-RPC alias and legacy audit selection value for safe upgrades.
- Added regression tests for non-stored pairing URL handling and audit-event compatibility.


## 19.0.1.0.0 — Commercial Branding & Pricing

- Replaced the Odoo app icon with the approved FlexSys FS + secure shield identity.
- Updated commercial list price to USD 99.
- License remains unchanged.

## 19.0.1.1.2 — Commercial Packaging & Documentation

- Added Odoo Apps HTML description.
- Added cover and English feature preview images.
- Expanded installation, user, and security operations documentation.
- Expanded Arabic translations for management UI and validation messages.
- Added commercial listing metadata and USD price.
- Preserved the existing module license unchanged.
- No Device Pairing architecture change from 19.0.1.1.1.

## 19.0.1.1.1

- Replaced the device-session Backend warning with: `Backend access is disabled`.
- Added Arabic translation: `الوصول إلى الواجهة الخلفية غير متاح`.

## 19.0.1.1.0 — Device Pairing

- Added one-time Pairing Links.
- Added browser Device Credentials with Secure + HttpOnly cookie delivery.
- Added Reset Pairing and credential-version invalidation.
- Added pairing states and audit events.

## 19.0.1.0.4 — Polish & Hardening

- Added managed POS Service User support.
- Added Device Access preflight test.
- Improved access state, expiry, IP/CIDR validation, and audit management.
