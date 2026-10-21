# FlexSys POS Receipt — Odoo 19 Enterprise

Version: **19.0.1.0.16 (STAGING CANDIDATE)**. Based on user-tested 0.15 design source.

## Features
- POS thermal 80mm receipt with 72mm print width for Epson TM-T20III calibration.
- Preserves Odoo-original logo, ZATCA payload, prices, accounting and taxation.
- Arabic/English text display, RTL/LTR item handling, per-POS Saudi Riyal SVG / SR selection.
- Exactly one framed order/tracking number. The **distinct technical invoice reference** is still printed, labeled "Invoice No." / "رقم الفاتورة", to preserve fiscal traceability; it is not mislabeled as another order number.
- Displays customer label only when a customer is present.
- Per-POS controls: promotional image **above/below existing logo**, optional footer image, company footer display, Arabic/English thank-you message.
- Both promotional image fields are resized server-side to max 576x700px; use high-contrast images for thermal printing.
- Customizations load **only when rendering a receipt**, from a user-authenticated, company-scoped, read-only endpoint. No POS data-loader `_load_pos_data_fields` override.
- Fallback during temporary network outages: standard receipt renders without optional promo content when settings cannot be fetched.

## Configuration
Point of Sale > Configuration > Point of Sales > Edit a POS > **FlexSys POS Receipt**.
Upload images to the dedicated fields and enable respective checkboxes. The POS customer account must have POS access. After settings changes, reload POS so the client-side read cache picks them up.

## Security and scope
Images are served through an authenticated HTTP route, restricted to POS users and the POS's company. This module never changes `res.currency`, `product.pricelist`, POS payment logic or ZATCA data. Image payloads are limited to 1.2MB base64 each; unsupported image signatures are rejected.

## Runtime status
Python/XML/JS static checks performed; Odoo server upgrade, POS runtime, Epson direct printing and ZATCA QR scanning **not performed** in this environment. See `TEST_PLAN.md` for mandatory nine-gate acceptance tests. Do not deploy to production until all pass.
