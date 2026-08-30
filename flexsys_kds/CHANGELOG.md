# Changelog

All notable changes to FlexSys KDS are documented here.

## [19.0.1.0.0] - Commercial Candidate

### Added
- Multi-station Kitchen Display workflow (New → Accepted → Preparing →
  Ready → Completed), with Cancelled and On Hold.
- Intelligent, rule-based station routing with product- and
  category-level fallback.
- KDS Only / Printer Only / KDS + Printer operating modes, configurable
  per station.
- Expeditor / Packing final-assembly workflow, with its own tracked
  task and SLA.
- Public Kiosk: secure, token-based, per-station screen requiring no
  Odoo login.
- SLA monitoring per station, with configurable Warning/Late
  thresholds.
- Kitchen printing: Direct Network (Epson ePOS) browser printing,
  Manual Direct Print, and POS Direct Auto Print, all tracked through
  a single centralized print job queue.
- Role and station-based access controls (Operator / Supervisor /
  Branch Manager / Administrator).
- Company-aware routing, operational data isolation, and role-based
  access controls for multi-company environments.
- Operational audit logging for workflow transitions, corrections,
  printing events, and administrative actions.

### Improved
- POS quantity reconciliation, preserving historical production when
  quantities change instead of overwriting or duplicating it.
- Multi-station completion handling, so each station completes its
  own portion of an order independently.
- Print queue ordering (newest order first) and backup-printer
  fallback handling on repeated print failures.

### Security
- Station-scoped access for Operators and Supervisors — no station
  assignment means no access.
- Company-aware access controls throughout.
- Protected workflow fields — state and timestamps can only change
  through normal workflow actions, never a direct edit.
- Token-based Public Kiosk access, with Operating Mode enforcement
  (Printer Only stations are not reachable via Kiosk).

### Localization
- Arabic and English localization.
- RTL-aware layouts for the Internal KDS screen and Public Kiosk.
- Arabic backend translation coverage (menus, views, selection
  values).

### Removed
- Order Priority / Urgent / VIP is not part of the active product
  workflow or UI.

### Changed
- Changed commercial license from LGPL-3 to OPL-1.

### Fixed
- POS line note displayed as raw JSON (e.g. `[{"text":"Heating","colorIndex":0}]`)
  instead of the human-readable text in the Internal KDS, Public
  Kiosk, and printed tickets, when Odoo 19's own color-coded POS
  Quick/Customer Notes were used - now normalized to plain readable
  text everywhere a line note is rendered.
