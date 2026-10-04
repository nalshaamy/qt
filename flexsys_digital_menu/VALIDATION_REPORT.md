# FlexSys Digital Menu — Validation Report

**Version:** 19.0.1.0.15  
**Target:** Odoo 19 Enterprise / Odoo.sh  
**Validation type:** Static/source/package validation. Odoo runtime install/upgrade was not executed in this environment.

## Changes validated in this build

1. **All-products behavior**
   - `All / الكل` renders one continuous product grid.
   - Category headings are not rendered while `All` is active.
   - Featured products are not duplicated in a separate Featured block while `All` is active.
   - Selecting a specific category still renders only that category with its heading.

2. **Dedicated Offers page**
   - Public route added: `/menu/<slug>/offers`.
   - Preview route added: `/digital-menu/preview-offers/<menu_id>`.
   - Brand navigation now links Offers to the dedicated page, not `#fsm-offers`.
   - Page content is sourced from the existing public payload, therefore only currently active offers are shown; on public routes that also means published offers only.
   - Offer action links return to the menu with `?offer=<public_key>`, and the public menu frontend applies that offer automatically.

3. **Offer image size in Odoo backend**
   - Offer image field now uses Odoo's compact `oe_avatar` image presentation instead of expanding to an oversized form image.

4. **Product image fallback**
   - If no menu-specific or Odoo product image exists, the product image endpoint returns the Digital Menu brand logo.
   - If no Digital Menu logo exists, it falls back to the Odoo company logo.
   - The same fallback is implemented for public and backend-preview image routes.

## Static checks executed

- Python byte-code compilation: **PASS**
- XML parse validation: **PASS** (16 XML files)
- JavaScript syntax (`node --check`): **PASS**
- Manifest parse/version: **PASS** (`19.0.1.0.15`)
- Odoo 19 Arabic PO module-comment validation: **PASS**
- Feature assertions for unified All grid, Offers route, compact offer image widget and logo fallback: **PASS**
- Old Offers hash navigation (`#fsm-offers`) in executable source: **NONE FOUND**
- Public CSS/JS cache-busting version updated to `19.0.1.0.15`: **PASS**

## Runtime status

**Not executed here.** Final acceptance still requires an Odoo.sh Staging module Upgrade and browser verification on desktop/mobile.

Recommended runtime checks after upgrade:

- Open `/menu/<slug>` and press **All**: all products should appear in one grid with no category headings.
- Select one category: only that category's products should appear.
- Click **Offers / العروض** in the Brand navigation: `/menu/<slug>/offers` should open.
- Verify expired, future or unpublished offers do not appear publicly.
- Verify Offer image is compact in the Odoo Offer form.
- Open a product with no image: the brand/company logo should appear automatically in its product card/details.
