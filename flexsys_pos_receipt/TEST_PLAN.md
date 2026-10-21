# FlexSys POS Receipt 19.0.1.0.16 — Staging acceptance

**Status:** Not runtime-tested in this build environment. Do not deploy to production before every check passes.

1. Upgrade on Odoo 19 Enterprise/Odoo.sh staging; confirm no ParseError or OWL error.
2. POS starts and completes new paid sale; no `use_pricelist`, `currency_id`, or IndexedDB failure.
3. Configure each POS separately: enable header image (above logo) and print; change to below logo and print; disable and print. Repeat for footer image.
4. Check PNG/JPEG, narrow/wide, maximum dimensions and b/w contrast; confirm fiscal QR and original logo remain distinct, unchanged.
5. Enable company details and test bottom address; disable and verify; VAT number remains at the top.
6. Set thank-you Arabic and English and verify UI-language switching. Disable text and verify it disappears.
7. Print new POS order: exact tracking number visible once, framed and labeled 'رقم الطلب' / 'Order Number'; separate technical invoice reference remains labeled 'رقم الفاتورة' / 'Invoice No.' for audit/fiscal traceability.
8. Add a real named customer: print 'العميل: [name]' / 'Customer: [name]'; a no-customer order hides the label.
9. Multi-item, modifiers, discounts, refunds, 0%-tax and 15%-tax cases: verify figures and three columns.
10. TM-T20III Epson 80mm native direct printing: legibility, 72mm content, no clipping, correct Riyal SVG. Scan fiscal QR with approved verifier.
11. Disable network then print: original native receipt prints with no promo images if no cached settings; POS stays operational.
12. Do not clear POS IndexedDB if it may contain offline/unsynced orders.

**Note**: display settings are loaded from a narrowly scoped authenticated HTTP endpoint on first receipt render, without overriding `_load_pos_data_fields`. Pending runtime verification for printer image capture and settings fetch timing. If settings cannot load, receipt falls back to core printing without optional images/messages.
