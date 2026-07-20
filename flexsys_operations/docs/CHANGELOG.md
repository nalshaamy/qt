# Changelog

## 19.0.1.0.0 — Foundation

- Renamed the module package to `flexsys_operations`.
- Updated static asset paths to the new technical module name.
- Added initial `common`, `services`, `tests`, and `docs` structure.
- Added service class scaffolding without changing existing business behavior.

## CORE-003B — Order serialization extraction

- Moved the legacy order payload construction to `services/order_service.py`.
- Kept the controller helper as a compatibility wrapper.
- No routes, database models, XML IDs, or response fields changed.
## 19.0.1.1.1 — CORE-003B.1

- Fixed stale module-qualified external ID in `ir.model.access.csv`.
- Updated controller template references to the `flexsys_operations` namespace.
- Updated static asset URLs to the renamed module path.
- Updated module context reference in settings view.
- Updated POS QWeb template namespace.
- Preserved legacy model names, database fields, SQL table names, and configuration keys for compatibility.

