
## 19.0.2.20.0

- Added Quick Reorder from the customer order history.
- Added automatic customer favorites based on repeat orders and quantities.
- Reorder uses current prices and excludes unavailable products before cart review.
- Fixed the customer tracking link shown after order creation.


## 19.0.2.16.0 — Queue Engine Foundation

- Added station queue strategies: FIFO, priority, requested time, and balanced.
- Added deterministic queue positions and waiting-time indicators.
- Added queue rebuild action and automatic resequencing after task changes.
- Prevented starting a task unless it is first in its station queue and capacity is available.
- Preserved multi-company and point-of-sale scope rules.
# 19.0.2.8.0

- Adopted customer-facing business routes under `/operations` and `/self-order`.
- Added clean API namespaces: `/operations/api/...` and `/self-order/api/...`.
- Preserved legacy `/qtcafe` and `/qr-menu` routes as compatibility aliases.
- Updated frontend links and JavaScript calls to use the new routes.
- Renamed visible QR-order alerts to generic order terminology.

## 19.0.2.5.0

- Added Mission Control as the default manager landing workspace.
- Added live operational health, execution task metrics, station status and recent event feed.
- Added launcher-style shortcuts while preserving existing Operations pages and manager permissions.
- Kept the implementation multi-company aware and compatible with independent manager accounts.

# 19.0.2.1.0

- Added line-level preparation lifecycle: New, Preparing, Ready, Unavailable, Cancelled.
- Added order lifecycle states: Scheduled, Partially Ready, Completed, Rejected.
- Added automatic order readiness calculation from order-line states.
- Added preparation progress and unavailable-line counters.
- Added requested-time support to public self-order creation.
- Kept all legacy technical model names and routes for database compatibility.

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
## 19.0.2.0.0 — Operations Foundation
- Renamed the visible application to **Operations**.
- Renamed visible **QR Orders** terminology to **Orders** while preserving technical model and route identifiers for upgrade safety.
- Added **Order Source** with `Self Order` as the default source and future-ready sources for POS, waiter, kiosk, website, mobile and API.
- Added order **Priority** and optional **Requested Time** fields.
- Renamed menu-facing QR menu terminology to **Self Order Menu / Menu Products / Menu Categories**.
- Kept legacy `qr` source value readable as `Self Order` for backward compatibility.


## 19.0.2.15.0
- Built Station Engine v1.0 with capacity enforcement, health indicators, load metrics, SLA timing, assigned users, and station lifecycle controls.


## 19.0.2.18.0

- Added Resource Engine for employees, machines, printers, displays, and external services.
- Added automatic resource assignment when execution tasks start.
- Added resource availability, capacity, skills, and live task metrics.
- Station effective capacity now reflects operational resources when resources are configured.
- Resource assignment is recorded in station task events.
