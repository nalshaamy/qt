# FlexSys POS Receipt 19.0.1.0.17 — Build checks

**Scope:** Staging ZIP build; source upgrade and hardware printing are not available in the build environment.

## Performed and passed

- Python source compilation, manifest parsing, internal asset-path existence.
- XML well-formedness and target receipt-logo XPath presence in Odoo 19 ReceiptHeader source.
- JavaScript syntax check (Node.js).
- No `_load_pos_data_fields` override introduced; receipt-only configuration endpoint retained.
- Browser geometry smoke tests (Chromium headless, simulated receipt DOM): widths **30, 50, 72 mm**, horizontal + square sample logos, centered within **72 mm** available print width, aspect ratios maintained, no logical overflow.
- Logo-width server field set to 72mm by default; integer validation for **30...72mm** added.
- Full ZIP contents validated (`ZipFile.testzip()`).

## Must still be verified together on Odoo.sh Staging

- Install/upgrade and OWL asset compilation in live Odoo 19 Enterprise.
- New order POS startup, payment, taxes, refunds and price lists.
- Logo at 72, 50, 30 mm directly printed on **Epson TM-T20III**.
- Header promotional images before/after logo, footer image, toggles, and bilingual thank-you message.
- Fiscal QR scanning, Saudi Riyal symbol, readable items/totals and bilingual layout.
- Settings should reflect each POS config separately after reopening/reloading POS.
- Confirm invalid values 29 and 73 cannot be saved.

**Not a production acceptance certificate.** This file records static/browser results only, not physical thermal receipt tests.
