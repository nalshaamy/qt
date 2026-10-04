# FlexSys Digital Menu — Validation Report

**Version:** 19.0.1.0.14  
**Module:** `flexsys_digital_menu`  
**Target:** Odoo 19 Enterprise / Odoo.sh

## Scope of this build

This release implements the approved public UI target on top of the existing V1 feature set. It is primarily a presentation-layer release; the established product/menu/branch/pricelist/offer/analytics architecture remains intact.

### UI target changes

- Compact centered Brand Shell with Brand Name and optional Tagline.
- Desktop brand navigation and mobile hamburger navigation.
- Compact search and pill category filters.
- Large offer hero/banner with image, content, pricing, navigation arrows and dots.
- Offers automatically appear in shared brand navigation when an active offer exists.
- Four-column desktop Cards presentation.
- Single-column horizontal Cards presentation on mobile.
- Updated Compact and Image Focused layouts.
- Refined product card typography, spacing, borders, shadows, badges and sold-out state.
- Existing description teaser / read-more behavior preserved.
- Refined desktop side sheet and mobile bottom sheet product details.
- Refined Branch Page cards and working-hours presentation.
- Compact company-rights footer retained.
- No cart/add-to-order controls were added.
- Public CSS/JS includes a version query to reduce stale-browser-cache issues after upgrade.

## Static validation performed

- Python AST parse across module Python files: **PASS**
- Python bytecode compilation: **PASS**
- XML parse across module XML files: **PASS**
- JavaScript syntax (`node --check`) for `menu.js` and `brand_page.js`: **PASS**
- Manifest parse / version / installable checks: **PASS**
- Manifest data-file existence checks: **PASS**
- Odoo 19 Search View guard: no legacy `expand` / `string` attributes on `<search><group>`: **PASS**
- Arabic PO per-entry `module: flexsys_digital_menu` marker guard: **PASS**
- Approved UI contract guards for offer hero, mobile navigation, cards layout, branches and cache-busted assets: **PASS**
- Generated Python cache files removed before packaging: **PASS**

## Odoo tests included

The module test suite now also contains coverage that verifies an active offer is added to the public brand navigation with an anchor to the offers section.

The Odoo TransactionCase suite is present but was **not executed against a live Odoo 19 registry in this environment**.

## Runtime status

A real Odoo.sh Staging **Upgrade** remains required. Static checks cannot guarantee final browser layout, QWeb execution, registry migration, translated runtime content or database-specific interactions.

### Recommended acceptance after upgrade

1. Hard refresh `/menu/<slug>` and confirm the centered Brand Shell and new search/category styling.
2. Test desktop at 1440px+: offer hero, four product cards per row and featured section.
3. Test Android/iPhone widths: hamburger navigation, single-column horizontal cards and product bottom sheet.
4. Create two active offers and verify arrows/dots switch the hero offer.
5. Verify **Offers / العروض** appears in brand navigation only while at least one active offer exists.
6. Switch Cards / Compact / Image Focused and verify each remains usable.
7. Open a Branches page and verify branch cards, status, contact/directions and working hours.
8. Verify Arabic RTL and English LTR.
