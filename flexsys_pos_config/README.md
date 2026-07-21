# FLPOS — Odoo 19

Standalone service module for Odoo Point of Sale. The technical module name is `flexsys_pos_config`.

## Features

- Appears as a service module, not as a separate Odoo application.
- Adds an **FLPOS** section under **Point of Sale → Configuration → Settings**.
- Removes **Powered by Odoo** from customer receipts by default.
- Provides a dedicated receipt logo per POS configuration, independent from the company logo.
- Adds an enhanced A4 POS session closing report.
- Includes payment totals, cash reconciliation, taxes, discounts and refunds.
- Groups product sales by exact variant with attributes and POS category.
- Includes Arabic RTL report layout.

## Installation

Copy `flexsys_pos_config` into the custom addons path, update the Apps List, and install **FLPOS**.
