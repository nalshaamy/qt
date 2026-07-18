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
