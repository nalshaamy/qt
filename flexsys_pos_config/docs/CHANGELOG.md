## 19.0.8.0.0

- Added optional automatic thermal closing report printing after a successful Close Register operation.
- Kept the manual Print button available.
- Added duplicate-call protection and ensured printing failures never block session closing.

## 19.0.7.1.8

- Linked the POS Closing Register **Print** button to the **Thermal Closing Report** setting.
- The Print button now appears only when the option is enabled for the active POS configuration.
- Added thermal and A4 closing-report flags to the POS configuration payload.

## 19.0.7.1.6

- Renamed the POS closing popup action to **Print**.
- Positioned Print beside Daily Sale in the native Odoo button row.
- Fixed Arabic labels using runtime Unicode labels.
- Normalized non-breaking spaces in monetary values.
- Forced Arabic RTL report context and improved PDF font handling.

## 19.0.7.1.5
- Fixed Odoo 19 ClosePosPopup import path.
- Bound Thermal PDF action to the native POS report service.

# FLPOS Changelog

## 19.0.7.1.1

- Added an 80 mm Thermal PDF button directly inside the POS Closing Register popup.
- The button opens the current session thermal closing report in a new browser tab.
- Kept the existing backend preview and download actions unchanged.

## 19.0.7.0.4

- Fixed receipt logo fallback behavior.
- When Custom Receipt Logo is disabled, Odoo uses the company logo normally.
- Hide Default Receipt Logo now applies only when Custom Receipt Logo is enabled.

## 19.0.7.0.3

- Fixed POS startup crash: `currency_id` was missing from the configuration payload.
- Removed the restrictive `_load_pos_data_fields` override.
- Added FLPOS receipt options through `_load_pos_data_read` while preserving all Odoo fields.

## 19.0.7.0.2

- Loaded FLPOS receipt settings into the Odoo 19 POS frontend.
- Fixed custom receipt logo display.
- Fixed hiding the default company receipt logo.
- Fixed hiding the `Powered by Odoo` footer.

## 19.0.7.0.0

- Removed Receipt Studio completely.
- Removed receipt template, block, preview, OWL, JavaScript, SCSS, views, actions, ACLs, rules, and groups.
- Removed the published Receipt Studio template field from POS configuration.
- Preserved standard FLPOS receipt options and enhanced session closing reports.
- Added an upgrade migration to clean obsolete Receipt Studio metadata.

## 19.0.7.1.0
- Added 80 mm thermal PDF session closing report.
- Added dedicated custom paper format (80 × 297 mm).
- Added thermal PDF preview and download buttons on POS sessions.
- Added RTL Arabic thermal layout with sales, payments, cash reconciliation, and product summary.

## 19.0.7.2.2
- Redesigned the thermal product section as a clearer three-column table.
- Added a product marker, variant count, product total quantity, and product total amount.
- Added hierarchical attribute-name/value details under every sold variant.
- Preserved best-selling-first sorting and variant contribution percentages.
