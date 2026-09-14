# FlexSys POS Hide Powered By

Standalone addon for **Odoo 19**.

## Purpose

Hides the `Powered by Odoo` block from the standard Point of Sale customer receipt.

## Technical behavior

The module inherits the OWL/QWeb template `point_of_sale.OrderReceipt` and adds `t-if="false"` to the standard element carrying the class `footer-powered-by`.

It does not modify Odoo core files.

## Installation on Odoo.sh

1. Add the folder `flexsys_pos_hide_powered_by` to your custom addons Git repository.
2. Commit and push it to the desired Odoo.sh branch.
3. Wait for the build to finish.
4. Update the Apps list if needed.
5. Search for **FlexSys POS Hide Powered By** and install it.
6. Close/reopen the POS or hard-refresh the POS assets.

## Version

19.0.1.0.0
