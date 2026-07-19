# FlexSys Trans Manager

Technical name: `flexsys_odoo_trans`
Version: `19.0.1.2.0`
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
