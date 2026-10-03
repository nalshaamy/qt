# FlexSys Digital Menu (`flexsys_digital_menu`)

Odoo 19 Enterprise / Odoo.sh implementation of the FlexSys Digital Menu V1 specification.

## Implemented V1 foundations

- Clean `/menu/<slug>` public route.
- Standalone lightweight public frontend; it does not load the Odoo backend Web Client.
- Cairo typography for Arabic and English through the public page font stylesheet.
- Arabic / English runtime switching without full-page reload.
- Native RTL / LTR switching.
- Multi-menu, multi-POS/branch, multi-pricelist architecture.
- Product-level **Digital Menu** tab.
- Product Default → Menu Override → Branch Override effective-result logic.
- Independent menu categories and ordering.
- Menu-specific product name, description and image overrides.
- Featured / badge / calories / ingredients / allergens / dietary metadata.
- Manual or stock-based sold-out behavior.
- Menu/product scheduling.
- Product variants exposed as informational options with effective prices.
- Logo-driven automatic Brand Engine using Pillow.
- Contrast-aware design token generation.
- Custom themes and centralized CSS design tokens.
- QR PNG and SVG generation using Odoo's standard Python `qrcode` dependency.
- Draft / Published / Archived lifecycle.
- Authenticated Draft preview with Mobile / Tablet / Desktop device frames.
- Per-menu display controls for images, descriptions, prices, calories, badges, dietary flags, variants, ingredients and allergens.
- Public payload only exposes public keys; Odoo record IDs are not included.
- Company record rules and Digital Menu User / Manager groups.
- First-time setup wizard.
- Responsive cards, category navigation, search, featured slab and product bottom sheet.

## Public URL

Example:

`https://qtcafe.sa/menu/main`

Set **Public Domain** to `qtcafe.sa` when the Odoo instance serves that hostname. If left blank, `web.base.url` is used for generated links.

## Installation

1. Put `flexsys_digital_menu` in the Odoo.sh repository addons path.
2. Commit/push to the Odoo.sh branch.
3. Update the Apps list.
4. Install **FlexSys Digital Menu**.
5. Grant **Digital Menu Manager** to the responsible backend user.
6. Point of Sale → Digital Menu → Create Menu.
7. Upload logo → Generate Brand → organize categories/products → Publish.

## Validation before production

Run on a real Odoo 19 build:

```bash
odoo-bin -d <test_db> -i flexsys_digital_menu --test-enable --stop-after-init
```

Then perform browser acceptance on:

- Android Chrome.
- iPhone Safari.
- Desktop Chrome/Edge/Safari.
- Arabic RTL and English LTR.
- Single branch and multiple branches.
- Pricelist and branch pricelist behavior.
- Sold-out/manual/stock modes.
- Overnight schedules.
- Logo color extraction with light, dark, monochrome and transparent logos.

## Font note

The module intentionally does not bundle or redistribute font files. The public template requests Cairo from Google Fonts and provides system font fallbacks.


## V1.0.1 Product Detail Enhancement

- Enlarged product image in the public product detail sheet.
- Product description is rendered in a dedicated description box only when an effective description exists.
- Added one automatic “You may also like / قد يعجبك أيضًا” recommendation.
- Recommendation priority: available product in the same category, then featured available product, then the next available product by sequence.
- Selecting the recommendation opens its product details in the same lightweight sheet.

## V1.0.3 Simple Product UX

The product-level **Digital Menu** tab now follows the lightweight FlexSys Operations philosophy:

- One master checkbox only: **Show in Digital Menu**.
- No separate **Available in Digital Menu** checkbox in the daily-use UI.
- Effective availability remains automatic through menu availability, stock, schedule, and advanced override rules.
- Direct simple fields: Menu, Menu Category, Display Order, Featured, Badge, Menu Image, Short Description.
- Product details stay available below the simple controls: calories, spicy level, vegetarian/vegan, gluten, ingredients, allergens.
- Menu Image falls back to the normal Odoo product image in the public menu when no override is uploaded.
- Short Description is optional; the public description box is not rendered when empty.
- Branch selection is no longer part of the normal product setup. A menu-wide assignment automatically applies to the menu's configured branches.
- Existing advanced architecture is retained behind **Advanced Settings** for extra menus, branch overrides, price overrides, scheduling, and effective-result diagnostics.
- The menu's Products tab now defaults to a compact list and hides technical override columns unless requested.
- Creating a menu-product assignment automatically enables **Show in Digital Menu** for the product.
- The product-level checkbox is the master visibility switch; advanced rules cannot force a disabled product public.

## 19.0.1.0.4 — Odoo 19 access-right UX

Digital Menu security groups now use the native Odoo 19 `res.groups.privilege` hierarchy under the Sales module category. The user form therefore presents **Digital Menu** as a normal access-right selector (`User` / `Administrator`) instead of separate standalone checkboxes. Existing security group XML IDs are preserved for upgrade safety.


## 19.0.1.0.6 — Product Card Description Teaser

- Product cards no longer show the full short description.
- When an effective description exists, the card shows a single-line teaser only.
- A localized **اقرأ عني أكثر / Read more about me** action appears directly below the teaser.
- Selecting that action opens the same lightweight product-detail sheet as selecting the card.
- The complete description remains inside the product detail description box.
- When no effective description exists, neither the teaser nor the read-more action is rendered.


## 19.0.1.0.7 UX consolidation
- Compact public header/hero and footer.
- Product cards keep a one-line description teaser; product detail sheet renders the full description without clamping.
- Standard badges render in Arabic or English according to the public-menu language.
- Custom badges now have explicit Arabic and English values, with legacy fallback for existing data.
- Removed the separate Advanced Settings action from the daily product workflow. Necessary additional controls now live inside Product Details on the same Digital Menu tab.

## 19.0.1.0.8 — Card and Product Detail Density

- Reduced public product-card footprint on tablet/desktop by using compact fixed-range grid tracks instead of stretching cards to fill the full row.
- Tightened card padding, title size, teaser spacing, badges, and sold-out chip so more products fit cleanly on one screen.
- Kept the two-column compact mobile layout unchanged in principle.
- Reduced the product-detail sheet width on desktop and changed the product hero image from a full-width oversized panel to a contained, rounded 280px media area.
- Reduced product-detail image height to 220px on mobile, leaving more room for the product name, full description, pricing, details, and recommendation.
