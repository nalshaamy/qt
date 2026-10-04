# FlexSys Digital Menu — Validation Report

**Version:** 19.0.1.0.16  
**Target:** Odoo 19 Enterprise / Odoo.sh  
**Validation type:** Static/source/package validation. Odoo runtime install/upgrade was not executed in this environment.

## Changes validated in this build

1. **Source POS Categories = Many2many**
   - Added `source_pos_category_ids` on `flexsys.menu.category`.
   - Category list/form and inline Main Menu category editor use `many2many_tags`.
   - Legacy `pos_category_id` remains internal for upgrade safety.
   - An idempotent upgrade bridge copies old single-source values into the new relation.
   - If a product assignment has no explicit Digital Menu category, the public payload may infer one from matching configured POS categories.

2. **Full-logo fallback rendering**
   - Public payload exposes `image_is_fallback` when the product image endpoint is serving Brand Logo / Company Logo instead of a product image.
   - Product cards, product details and recommendation cards apply `object-fit: contain` with padding to fallback logos only.
   - Real product images continue using `object-fit: cover`.

3. **Offer image sizing / quality protection**
   - Menu offer hero changed from full-background stretching to a split text/media layout with a bounded image region.
   - Dedicated Offers page uses a compact 210×180 media region on desktop and 120×128 on mobile.
   - Odoo Offer form keeps a compact avatar-style image widget.
   - This prevents low-resolution offer images from being enlarged across an oversized full-width hero.

4. **Recommended Product control**
   - Added `Automatic / Manual` recommendation mode on `product.template`.
   - Manual mode supports one selected product.
   - Public payload resolves the selected product only if it is present and available in the same effective menu payload.
   - Frontend prioritizes `recommended_key`; otherwise it falls back to the existing automatic algorithm.
   - Self-recommendation is blocked by a model constraint.

## Static checks executed

- Python byte-code compilation: **PASS**
- XML parse validation: **PASS**
- JavaScript syntax (`node --check`): **PASS**
- Manifest parse/version: **PASS** (`19.0.1.0.16`)
- Arabic PO entry structure/module comments: **PASS**
- Feature assertions for Many2many source categories, fallback-image metadata, manual recommendation and bounded offer media: **PASS**
- Public CSS/JS cache-busting version updated to `19.0.1.0.16`: **PASS**

## Runtime status

**Not executed here.** Final acceptance still requires an Odoo.sh Staging module Upgrade.

Recommended runtime checks after upgrade:

- Open Digital Menu → Categories and verify **Source POS Categories** accepts multiple POS categories.
- Verify an existing old Source POS Category is retained after upgrade.
- Open a product with no image and confirm the Brand Logo is fully visible (not cropped) in card, details and recommendation.
- Open an active Offer on desktop/mobile and confirm the image is bounded, sharp and not stretched across the entire hero.
- Set one product to **Recommended Product = Manual**, select another menu product, then confirm **قد يعجبك أيضًا / You may also like** uses it.
- Remove/hide the manual target and confirm recommendation falls back automatically without error.
