# Receipt Studio Runtime Removal — 19.0.5.0.1

This release removes Receipt Studio execution from the Point of Sale frontend.

- Receipt Studio remains available in the Odoo backend as a designer and preview tool.
- POS no longer receives `flexsys_receipt_design` JSON.
- POS no longer loads the Receipt Studio OrderReceipt QWeb override or its runtime stylesheet.
- The native Odoo POS receipt is used.
- The quota protection remains: `flexsys_receipt_logo` binary is removed from the POS offline payload.

No compiler or generated QWeb integration is included in this release.
