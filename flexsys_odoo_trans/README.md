# FlexSys Trans Manager

Technical name: `flexsys_odoo_trans`
Version: `19.0.1.5.0`
Odoo: 19.0

## Public routes
- `/fstrans/login`
- `/fstrans/dashboard`
- `/fstrans/dashboard/stock`
- `/fstrans/dashboard/movements`
- `/fstrans/logout`

## Setup
1. Install the module.
2. Open FlexSys Trans Manager > Independent Managers as an Odoo administrator.
3. Create a manager, assign a company and warehouse, and set a password of at least 8 characters.
4. Sign in through `/fstrans/login`.

Independent managers are not `res.users`; they use a separate model and session.


## FlexSys unified identity
- Cairo is the default interface font.
- The shared design tokens live in `static/src/css/flexsys_identity.css`.
- Primary: `#102F4A`
- Secondary: `#5F8DB2`
- Accent: `#F39A3C`
- Unified radii, shadows, focus states, cards, tables, filters, login, and navigation.


## 19.0.2.0.0 — FlexSys UX Architecture v2

- Rebuilt the dashboard as a command center with KPIs, alerts, quick access, and a compact activity feed.
- Moved all warehouse functions under a dedicated Warehouses workspace.
- Added internal pages for Operations, Transfers, Inventory Count, Stock, and Movement History.
- Added server-side pagination and operational filters for warehouse operations and transfers.
- Added warehouse overview cards and direct navigation from dashboard summaries to the responsible workspace.
- Standardized the independent manager session key as `flexsys_inventory_manager_id` while retaining legacy-session compatibility.
Test For Acode