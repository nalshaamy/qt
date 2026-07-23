# Architecture

## Module

Technical name: `flexsys_pos_config`

Dependency: `point_of_sale`

## Models

- `pos.config`: stores receipt and report configuration.
- `res.config.settings`: exposes related POS configuration fields.
- `pos.session`: computes closing-report data from standard POS records.

## Frontend

Receipt changes use QWeb inheritance of `point_of_sale.OrderReceipt` and scoped SCSS.

The implementation intentionally avoids:

- Odoo Core modification.
- POS Store patching.
- POS Loader override.
- JavaScript patching.
- ReceiptHeader component replacement.

## Reporting

The enhanced closing report uses a standard `ir.actions.report`, an A4 paper format, and a QWeb PDF template bound to `pos.session`.
