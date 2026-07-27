
## 19.0.15.2.0
- Reduced the thermal closing report logo to a maximum of 70 px × 35 px.
- Kept the logo proportional, centered, and isolated from the A4 report styling.
# 19.0.15.1.0

- Switched the thermal closing report from the embedded FLPOS Cairo font to an Odoo-compatible font stack.
- Thermal font order: Inter, Noto Sans Arabic, Noto Sans, Lato, DejaVu Sans, Arial, sans-serif.
- Kept the Executive A4 report typography unchanged.
- No report calculations, layouts, sections, or automatic-closing behavior were changed.

# 19.0.15.0.0
- Added the **Print Closing Report Automatically** option under Point of Sale closing-report settings.
- Enabled: after a successful Close Register operation, the thermal closing report opens automatically.
- Disabled: the approved A4/PDF closing report is displayed instead.
- Preserved the approved Arabic and English Executive Report layouts.

# 19.0.14.3.0
- Fixed English Executive Report product-name cells so Arabic RTL alignment rules no longer leak into the English LTR template.
- Preserved the approved Arabic report layout unchanged.

# Changelog

## 19.0.14.2.8
- Applied Arabic PDF alignment directly in QWeb with inline wkhtmltopdf-safe styles.
- Right-aligned Arabic product names.
- Right-aligned Payment Methods, Cash Control, and Cashier Performance section headings.
- Right-aligned Method and Amount headers/data in the Arabic payment table.
- Preserved the final-total-only behavior for multi-page product tables.

## 19.0.14.2.7
- Fixed Arabic product-name alignment using direct wkhtmltopdf-safe classes.
- Fixed Arabic section-title alignment for Payments, Cash Control, and Cashier Performance.
- Fixed Arabic Payment Method and Amount alignment.

# Changelog

## 19.0.14.2.6
- Renamed the commercial product to **FLPOS Intelligence**.
- Right-aligned Arabic product names, section titles, and requested payment fields.
- Prevented the product-table grand total from repeating on intermediate PDF pages.
- Preserved English/LTR report behavior.

# 19.0.14.2.5
- Corrected Arabic product-table column widths to match the physical QWeb order used by wkhtmltopdf.
- Prevented the Arabic total header (الإجمالي) and other compact column headings from splitting across lines.
- Preserved the approved RTL layout, centered data, calculations, branding, and session card without other visual changes.

# 19.0.14.2.4
- Correct POS discount totals using the explicit line discount percentage.
- Physically mirror Arabic report columns for wkhtmltopdf-safe RTL output.
- Mirror Arabic payment, cash control, and cashier-performance tables.
- Stabilize negative monetary values.
- Keep all report-table content centered.

## 19.0.14.2.3 — Executive Report Native RTL Edition
- Rebuilt Arabic product sales, payment methods, cash reconciliation, and cashier performance tables in true logical RTL order.
- Centered all report table headers and body data, including product names, categories, attributes, payment methods, cashier names, quantities, percentages, and monetary values.
- Stabilized mixed Arabic/English values using centered bidirectional text handling.
- Preserved the English Executive Report as LTR while applying the same centered tabular presentation.


## 19.0.14.2.2
- Completed the Executive Report production-polish pass for Arabic and English.
- Standardized table header height, padding, vertical alignment, and centered headings.
- Improved long product and cashier name wrapping without breaking A4 width.
- Stabilized product table column widths and numeric alignment in both native layouts.
- Improved section spacing, logo scaling, repeated print headers, and page-break behavior.
- Confirmed the Arabic Refunds label is stored as the correct UTF-8 text: المرتجعات.


## 19.0.14.2.1
- Centered all Executive Report table column headers in both Arabic and English.
- Preserved language-aware alignment for table body cells and numeric values.
## 19.0.14.1.0
- Removed the bilingual closing-report language option; supported choices are Auto, Arabic, and English.
- Added Arabic (Saudi/modern Odoo locale) translations so session report buttons follow the Odoo user interface language.
- Existing POS configurations using Bilingual are migrated safely to Auto.

## 19.0.14.0.0 — Report language finalization
- Added per-POS report language: Auto, Arabic, English, or Bilingual.
- Executive A4 report now follows the selected report language; thermal report localization remains unchanged in this revision.
- Corrected Executive Report wording and removed mixed-language subtitle duplication.
- Removed generic logo placeholder; company name is used when no logo exists.
- Centralized the Refunds label to prevent corrupted Arabic rendering.


## 19.0.14.0.0 — Final A4 readability refinement

- Centered session information, KPI values, table headers, and numeric data.
- Kept product names aligned to the reading direction for long-name readability.
- Increased product-sales table typography and row spacing for comfortable daily use.
- Enlarged report logo and centered the report header.
- Improved signature spacing and added FLPOS version/website to the footer.

# 19.0.14.0.0

- Fixed closing-report logo selection for both A4 and thermal reports.
- Reports now use the POS Receipt Logo first and fall back to the company logo.
- Fixed customer receipts hiding the company logo when no custom receipt logo exists.
- Removed cached Python bytecode from the distribution package.

# Changelog

## 19.0.13.0.0
- Removed the visible timezone name from the A4 report while preserving user-timezone conversion internally.
- Removed the module version from the report footer.
- Split the report issue timestamp into clean date and time lines.
- Removed decorative KPI sequence numbers and improved card spacing.
- Replaced the cashier summary with a precise cashier count in the session panel.
- Added distinct positive, negative, and balanced cash-difference states.
- Highlighted the leading cashier row in the performance table.
- Kept company-logo fallback free of the generic “Your logo” placeholder.

## 19.0.12.1.0
- Renamed the A4 timestamp to **Report Issued At** / **وقت إصدار التقرير**.
- Converted report issue, session opening, and session closing timestamps using the current Odoo user timezone.
- Added the effective timezone name below the report issue timestamp for audit clarity.
- Added safe fallbacks to the company partner timezone and UTC when the user has no timezone configured.

## 19.0.12.0.0
- Redesigned the A4 closing report with stronger FLPOS/FlexSys branding.
- Added unit price and tax columns to product sales details.
- Added payment percentage bars and cash-difference status highlighting.
- Added average order and average items KPIs to cashier performance.
- Improved A4 spacing, typography, status badges, signatures, and footer.

## 19.0.11.1.0
- Replaced the standalone Closing Register print button with a dropdown menu.
- Added **Closing Report (A4)** linked to the FLPOS A4 report action.
- Added **Closing Report (Thermal)** linked to the 80 mm thermal report action.
- The menu only shows report options enabled in the POS configuration.


## 19.1.0.0.0
- New FLPOS A4 Closing Report design.
- Added branded header, session information panel and six KPI cards.
- Added professional product sales table with numbered rows and totals.
- Added payment percentages, cash control and cashier performance sections.
- Improved A4 print layout, RTL alignment and page-break handling.

## 19.0.10.0.3
- Added TTF Cairo files for reliable wkhtmltopdf PDF rendering.
- Kept WOFF2 files as browser/POS fallback.
- Forced the embedded FLPOS Cairo family on A4 and thermal reports.
- Refined thermal session table widths and prevented field-label wrapping.


## 19.0.10.0.2

- Embedded Cairo Regular, SemiBold, and Bold WOFF2 fonts in the module.
- Applied Cairo to thermal and A4 session reports.
- Applied Cairo to FLPOS POS receipts with safe fallback fonts.

# 19.0.10.0.1

- Refined the thermal session information table for stable RTL alignment.
- Prevented session labels and compact date/time values from wrapping unexpectedly.
- Displayed “لم تغلق بعد” for open sessions and `--` when duration is unavailable.
- Rebuilt cashier performance rows as a fixed table for consistent order and sales columns.

## 19.0.10.0.0
- Added a structured thermal session information table.
- Added the active cashier summary to session information.
- Added optional per-cashier order count, sales, refunds, discounts, and net sales.
- Cashier attribution uses POS employee data when available and safely falls back to the order user.

## 19.0.9.1.0
- Added an optional setting to hide free or zero-sales products from the Top Selling Products section.
- Improved quantity and sales amount alignment on 80 mm thermal reports.

## 19.0.9.0.3
- Final polish for Top Selling Products on thermal reports.
- Rank now appears before the product name.
- Quantity and sales are combined into one compact line.
- Added a light separator between products.

# Changelog

## 19.0.9.0.2

- Changed the section title to **Top 10 Selling Products**.
- Corrected rank placement so each line starts with `1.` before the product name.
- Split quantity and sales into separate lines for clearer 80 mm printing.
- Added a light dashed separator between ranked products and refined RTL/LTR alignment.

## 19.0.9.0.1

- Improved the optional **Top Selling Products** thermal layout for clearer 80 mm printing.
- Removed internal product references from this ranking and now displays the product name only.
- Moved rank, quantity, and sales amount into a stable two-line layout to improve RTL alignment.

## 19.0.9.0.0

- Added an optional **Top Selling Products** section to the thermal closing report.
- Added a per-POS toggle under Closing Reports; it is disabled by default to keep the report compact.
- Shows up to ten products, grouped by product template and ranked by sold quantity, with quantity and sales amount.

## 19.0.8.0.1

- Fixed the manual **Print** button producing a blank thermal closing report.
- Manual and automatic printing now resolve the same valid POS session ID and use the same report action.

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

## 19.0.14.0.0 — Final report readability refinement

- Centered the A4 report header, session information, KPI cards, numeric values, table headers, signatures, and footer.
- Kept product names aligned to the Arabic reading direction.
- Increased product-sales table font size and row spacing.
- Strengthened product names while keeping SKU/barcode metadata visually secondary.
- Applied matching readability refinements to the 80 mm thermal report.
- Removed Python cache artifacts from the distributable archive.

### Final A4 commercial polish
- Increased report logo prominence by approximately 12%.
- Strengthened session-field hierarchy and KPI values.
- Added visual hierarchy for product name, category, and attributes.
- Compacted approval signatures and footer spacing.
- Hardened Arabic rendering for the refunds label in wkhtmltopdf.

- A4 header: removed FlexSys/Operations Platform branding for customer-facing white-label reports.
- A4 header: changed report type label to Executive Report / تقرير تنفيذي.

### Bilingual executive report refinement
- Added a dedicated Arabic-first bilingual layout with stacked Arabic and English labels.
- Isolated RTL and LTR text to prevent reversed English word order in wkhtmltopdf.
- Kept Arabic-only and English-only report directions unchanged.
- Preserved Odoo UI button translations independently from the selected report language.
