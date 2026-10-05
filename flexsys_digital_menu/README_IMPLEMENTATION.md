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
5. Set **Digital Menu → Administrator** for the responsible backend user.
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

## 19.0.1.0.9 — Odoo 19 Arabic PO Compatibility Fix

- Rebuilt `i18n/ar.po` using the native Odoo 19 PO structure.
- Every translated entry now includes the required `module: flexsys_digital_menu` extracted comment.
- Added Odoo-recognized occurrences for field/view/code terms.
- This fixes the Odoo 19 translation-loader crash during install/upgrade (`PoFileReader` failing on `match.groups()` when the module comment is missing).
- Added static validation to catch missing module comments or malformed PO occurrences before packaging.

## 19.0.1.0.10

- Changed category chips from scroll-only navigation to true filtering.
- `All` shows all menu categories/products; a selected category shows only that category's products.
- Reduced public hero/header, search/category slab, and footer vertical footprint again.
- Footer now shows the linked Odoo company's name instead of the menu name.


## 19.0.1.0.11
- Public header uses Brand Name (fallback company name) and centers logo + brand identity.
- Footer is localized as “All rights reserved to / جميع الحقوق محفوظة لـ” + company name.
- Hero/footer text colors are chosen automatically for contrast with optional overrides in Branding.
- Branding daily UI is simplified; Hero Image and SEO Title stay backward-compatible but are hidden from the daily Branding tab.
- Important badges use a subtle pulse with reduced-motion protection.
- Mobile product details use a viewport-safe fixed bottom sheet with higher z-index, scroll locking and safe-area support.

## 19.0.1.0.12 — Lightweight Brand Shell + Page Engine

- Replaced the previous hero-style public header with a compact, centered **Brand Shell**: logo → Brand Name → optional Tagline.
- The language/branch controls remain independent from the centered brand identity, so the header stays visually balanced.
- The public navigation is intentionally hidden when the menu is the only public page.
- Added a lightweight `flexsys.brand.page` engine for future customer-facing pages such as **About Brand**, **Branches**, and custom pages.
- Published Brand Pages automatically appear in the shared public navigation; draft/unpublished pages remain hidden.
- Brand Pages inherit the same logo, Brand Name, Cairo typography, Brand Engine colors, text contrast, navigation, and company footer as the Digital Menu.
- Current V1 remains menu-first and lightweight; no extra public page is created or exposed by default.
- Generic future page route: `/menu/<menu-slug>/page/<page-slug>`.
- Public navigation payload is language-aware and preserves Arabic/English context when moving between the menu and future Brand Pages.
- The public menu route and data architecture remain backward-compatible.

## 19.0.1.0.13 — Offers, Branch Pages, Layouts & Lightweight Analytics

### Offers / Promotions
- Added native `flexsys.menu.offer` records with image, bilingual title/description, publish state, date window and reusable Digital Menu schedules.
- Offers may link to one or more Odoo products.
- Optional **Offer Pricelist** uses the native Odoo pricelist engine; FlexSys does not create a parallel promotional-pricing engine.
- When an offer pricelist is present, offer-filtered product cards/details use that pricelist price, including variant price mapping.
- Active offers appear above the featured-products section; a one-product offer opens that product, while multi-product offers filter the menu to the offer products.

### Structured Branch Pages
- Extended `pos.config` with customer-facing branch metadata: public name, description, address, phone, WhatsApp, map URL / coordinates and branch image.
- Added structured weekly working-hours records with overnight-hours support and live **Open now / Closed now** calculation in the menu timezone.
- A Brand Page of type **Branches** automatically renders cards from the menu's configured POS branches.
- Added a **Create / Open Branches Page** action; the page remains unpublished until the manager explicitly publishes it.
- Map/directions links are validated to HTTP/HTTPS and WhatsApp numbers are sanitized for the public link.

### Multiple Menu Layouts
- Added three layout modes using the same Brand Engine and Design Tokens:
  - **Cards** — existing balanced product cards.
  - **Compact** — dense horizontal cards for larger catalogs.
  - **Image Focused** — stronger product imagery with reduced card copy.
- Layout selection is upgrade-safe: existing menus fall back to **Cards** automatically.

### Lightweight Anonymous Analytics
- Added anonymous events for menu views, product opens, category filters, searches, offer opens, language changes and branch changes.
- No customer identity or raw IP address is stored.
- Menu views are de-duplicated once per anonymous browser session per business day.
- Backend summary shows views, product opens, searches, top product, top category, top search and Arabic-language share.
- Search/product/category references are resolved server-side to readable labels.
- Analytics retention defaults to 90 days and is configurable from 7–365 days; a daily cron deletes expired events.
- Existing menus are upgrade-safe: analytics defaults effectively ON unless explicitly disabled.
- If `flexsys_operations` is installed, Branch Pages can reuse its existing public branch name/address/coordinates/open flag as fallback values without adding a hard dependency between the modules.

## 19.0.1.0.14 — Approved UI Target Implementation

This build applies the approved FlexSys Digital Menu visual target to the existing functional architecture without adding cart/ordering behavior.

### Public Brand Shell
- Reworked the header into a light brand shell with centered **Brand Name + optional Tagline**.
- Desktop navigation is centered below the identity; language/branch controls remain secondary.
- Mobile uses a compact hamburger navigation with centered brand identity and a small language control.
- Uploaded logo remains part of the Brand Engine but is no longer forced into the public header, matching the approved UI target.

### Search and Categories
- Search and category filters use the approved compact pill-based visual language.
- The control area remains sticky and lightweight.
- Category behavior is unchanged: **All** shows every product; selecting a category shows only that category.

### Offers Hero
- Replaced small offer cards with a large promotional hero/banner matching the approved target.
- The banner supports offer image, title, subtitle, description, promotional price, original price and action.
- Multiple active offers use previous/next controls and indicator dots.
- Active offers automatically add an **Offers / العروض** item to the shared brand navigation, linking to the offer section.

### Product Presentation
- Cards layout now uses a clean four-column desktop grid similar to the approved target.
- Product cards use tighter typography, spacing, rounded corners and subtle shadows.
- Existing description teaser + **Read more about me / اقرأ عني أكثر** behavior is preserved.
- Mobile Cards layout becomes a single-column horizontal card pattern for faster browsing.
- Compact and Image Focused layouts remain supported and were visually aligned with the new system.
- No cart/add button was introduced because ordering remains outside V1.

### Product Details
- Retained the viewport-safe mobile bottom sheet and desktop side sheet.
- Media, spacing, full description, variants and recommendation use the same softer card language as the approved target.

### Branch Pages
- Branch cards were visually aligned with the approved target using image-led cards, compact status, directions/contact actions and working hours.

### Cache / Upgrade UX
- Public CSS and JavaScript URLs now include a build version query (`19.0.1.0.14`) so browsers do not keep stale visual assets after an Odoo.sh upgrade.

The approved mockup remains a visual target rather than a literal screenshot of runtime data: customer colors, images, text and available sections continue to come from Odoo and the Brand Engine.

## 19.0.1.0.15 — Unified All Grid, Offers Page & Image Fallback

- `All / الكل` now renders every matching product in one continuous grid with no category headings and no duplicated Featured block. Selecting a category still shows only that category with its heading.
- Offers navigation now opens a real standalone `/menu/<slug>/offers` page instead of a hash jump. Only published, currently active offers are rendered.
- Offer cards link back to the menu with the selected offer applied, so linked offer products can be browsed immediately.
- Added a preview-safe Offers page route for backend menu previews.
- Reduced the backend Offer image widget to Odoo's compact avatar-style size, matching the normal product-image editing experience.
- Products without their own menu/product image now automatically use the Digital Menu brand logo, falling back to the Odoo company logo when necessary. This fallback applies to public and backend preview routes.
- Public CSS/JS cache version bumped to `19.0.1.0.15`.

## 19.0.1.0.16 — Multi-source Categories, Recommendations & Media Polish

- Replaced the daily **Source POS Category** control with **Source POS Categories** (`Many2many`). One public Digital Menu category can now group multiple POS categories.
- The old single-source field is retained internally for non-destructive upgrades; existing values are migrated into the new Many2many relation.
- When a menu-product line has no explicit Digital Menu category, the menu engine can infer the first matching public category from its configured source POS categories.
- Product image payload now marks brand/company-logo fallbacks explicitly. Product cards, product details and recommendation cards render these fallback logos with `object-fit: contain` and padding so the full logo is visible without cropping.
- Offer media was reduced and rebalanced: the menu offer hero uses a split text/image composition instead of stretching a small image across the full banner, and the dedicated Offers page uses compact fixed-size media closer to product-card proportions.
- Added product-level **Recommended Product** control under Product Details:
  - `Automatic` keeps the existing recommendation priority (same category → featured → sequence).
  - `Manual` allows one specific product to be selected when that product is available in the same effective public menu payload.
- Public CSS/JS cache version bumped to `19.0.1.0.16`.



## 19.0.1.0.17 — Recommendation Opt-in & Odoo 19 Constraint Cleanup

- **Recommended Product** now has exactly three modes: `Disabled`, `Automatic`, and `Manual`.
- `Disabled` is the default and the public payload/frontend render no “You may also like” section in this mode.
- `Automatic` uses same category → featured → sequence.
- `Manual` shows only the selected valid product; missing/unavailable manual targets do **not** fall back to Automatic.
- Upgrade script resets legacy `Automatic` values from 19.0.1.0.16 to `Disabled`, preserving explicit `Manual` selections, so recommendations are truly opt-in after upgrade.
- Migrated all six legacy `_sql_constraints` declarations to Odoo 19 `models.Constraint` attributes to remove Odoo.sh build warnings.
- Public CSS/JS cache version bumped to `19.0.1.0.17`.

## 19.0.1.0.18 — Promotional Banner Engine + Offer Media Guardrails

This release separates promotional advertising media from offer/product imagery.

### Promotional Banners
- New model: `flexsys.menu.banner`.
- Optional, centered banner area on the public menu between category controls and offers/products.
- Supported media types:
  - Static image: JPG / PNG / WebP.
  - Animated image: GIF / Animated WebP.
  - Video: MP4 / WebM, rendered muted + loop + playsinline.
- Desktop/tablet media plus an optional mobile-specific media override.
- `Contain` (default) or `Cover` fit mode.
- Optional click URL and open-in-new-tab behavior.
- Start/end dates and reusable Digital Menu schedules.
- Public media has a 25 MB per-file guardrail.
- Multiple active banners use lightweight arrows/dots; no banner UI is rendered when none are active.
- Anonymous analytics can record `banner_open` when a clickable banner is used.

### Fixed responsive banner geometry
The public banner container is intentionally bounded and centered:
- Desktop: max width 1100 px, approximately 3:1.
- Tablet: max width 820 px, approximately 2.5:1.
- Mobile: available content width with 16:9 ratio.

The media adapts *inside* the container. It never stretches the container itself.

### Offer images are no longer banners
Offer imagery remains part of a compact offer card:
- Desktop public offer image box: 210 × 180 px.
- Mobile public offer image box: approximately 120 × 128 px.
- `object-fit: contain` prevents source images from being distorted or enlarged to a giant hero background.
- Inline menu offer cards use the same bounded-media philosophy.

### Backend
- Added **Promotional Banners** menu and a tab inside each Digital Menu.
- The backend form clearly separates desktop/tablet media from optional mobile media.
- Banner schedule, click URL, media type and fit mode are managed without changing product or offer data.

### Compatibility
- Existing menus, offers and products require no migration to use banners.
- Banners are opt-in: existing menus render exactly as before until a banner is created and published.


## 19.0.1.0.20 — Production Polish & Stability

- Production baseline polish only; no new transaction flow or breaking public route changes.
- Product-card names are clamped to two lines for stable card heights; full names remain visible in product details.
- Public prices suppress unnecessary trailing `.00` while preserving real fractional prices up to the currency precision.
- Category chips remain a single smooth horizontal scroller on mobile with snap/active-chip centering.
- `All / الكل` remains one continuous product grid with no category headings.
- Badge pulse was softened to a subtle halo without scale animation and still respects reduced-motion preferences.
- Product-detail image and internal spacing were tightened further without hiding the full description.
- Brand/company logo fallbacks keep `contain` sizing with proportional padding across cards, details and recommendations.
- Offer images remain bounded below normal product-card media size; promotional banners remain a separate fixed-ratio centered surface.
- Public menu JSON cache window increased to 60s with stale-while-revalidate 180s; images continue to lazy-load and use async decoding where appropriate.
- General section spacing/rhythm was tightened for Featured / Offers / Products while preserving the approved Production UI baseline.
