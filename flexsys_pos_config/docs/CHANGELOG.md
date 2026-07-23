# Changelog

## 19.0.4.1.0

- Introduced the first functional FLPOS Receipt Studio MVP.
- Added a component library with logo, company, queue, customer, QR, divider, spacer, and other receipt sections.
- Added component creation, duplication, removal, enable/disable, and ordering controls.
- Added live alignment, font-size, bold, title, and custom-content properties.
- Expanded safe sample-data preview rendering for the new components.
- Kept the technical module name `flexsys_pos_config` unchanged.

## 19.0.1.1.1

- Added product documentation package.
- Replaced the outdated root README with current feature and installation information.
- Added installation, quick-start, user, feature, FAQ, troubleshooting, release, roadmap, support, and developer documents.
- Clarified that the current generated closing report is A4 while thermal report generation remains planned.

## 19.0.1.1.0

- Connected the custom receipt logo option to the printed receipt.
- Added receipt-scoped hiding of the default logo.
- Kept the Odoo footer option independent.
- Avoided POS Loader, POS Store, ReceiptHeader, and JavaScript patches.

## 19.0.1.0.9

- Added FLPOS configuration fields for receipt and closing-report options.

## 19.0.1.0.8

- Established the verified stable baseline used for subsequent development.

## 19.0.4.2.0
- Exposed Receipt Studio permissions directly in Users > Access Rights under a dedicated FLPOS category.
- Removed the need to assign users from the technical Groups screen.
- Prevented Receipt Studio Manager from implicitly granting POS Manager privileges.
- Redesigned the POS settings entry as a polished Receipt Studio launch card.
