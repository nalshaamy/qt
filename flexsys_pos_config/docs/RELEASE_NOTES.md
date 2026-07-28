# FLPOS 19.0.14.0.0

This release fixes logo rendering across customer receipts and POS session closing reports. The dedicated POS Receipt Logo has priority; the company logo is used automatically when no dedicated logo is configured.


## 19.1.0.0.0
- New FLPOS A4 Closing Report design.
- Added branded header, session information panel and six KPI cards.
- Added professional product sales table with numbered rows and totals.
- Added payment percentages, cash control and cashier performance sections.
- Improved A4 print layout, RTL alignment and page-break handling.

## 19.0.10.0.2

- Embedded Cairo Regular, SemiBold, and Bold WOFF2 fonts in the module.
- Applied Cairo to thermal and A4 session reports.
- Applied Cairo to FLPOS POS receipts with safe fallback fonts.

## 19.0.9.1.0
- Added an optional setting to hide free or zero-sales products from the Top Selling Products section.
- Improved quantity and sales amount alignment on 80 mm thermal reports.

## 19.0.9.0.3
- Final polish for Top Selling Products on thermal reports.
- Rank now appears before the product name.
- Quantity and sales are combined into one compact line.
- Added a light separator between products.

# Release Notes — 19.0.1.1.1

This release adds the first complete documentation package for FLPOS and updates the root project information to match the current implementation.

## Functional scope

- Per-POS dedicated receipt logo.
- Optional default receipt logo visibility.
- Optional Odoo receipt footer visibility.
- Enhanced A4 POS session closing report.

## Compatibility

- Odoo 19
- Point of Sale

## Upgrade note

After upgrading the module, reload active POS browser sessions to ensure the latest configuration and frontend assets are used.
