# FlexSys Digital Menu 19.0.1.0.23 — Validation Report

## Scope
Narrow hotfix built directly from 19.0.1.0.22 after Staging acceptance review.

## Runtime behavior changed
- Restored a dedicated **Featured / الأكثر تميزًا** section above the normal product grid on `All / الكل`.
- Featured-section order uses existing `featured_sequence`, then normal `sequence` as a tie-breaker.
- The normal All grid remains continuous and keeps its own order.
- Restored the earlier visible Badge pulse (`scale(1.025)` + halo, 2.2s).

## Explicitly untouched
- Models and database fields.
- Controllers and public routes.
- Security / ACLs.
- Offers and promotional banners.
- Centered product modal.
- Mobile banner override and asset revisioning.
- iPhone category scrolling.
- Many2many POS-category mapping.
- Recommendation logic.
- Analytics.

## Static validation
- Python compile: PASS
- Manifest parse/version: PASS (`19.0.1.0.23`)
- XML parse: PASS
- JavaScript syntax: PASS
- Arabic PO structural parse: PASS
- Legacy `_sql_constraints` scan: PASS (none found)
- Featured dedicated-section path present: PASS
- All-grid continuity retained: PASS
- Explicit Badge rendering path retained: PASS
- Restored Badge pulse signature: PASS
- Reduced-motion safeguard retained: PASS
- Static asset cache-busting updated to 0.23: PASS
- Functional source diff limited to `menu.js` + `menu.css`: PASS
- ZIP integrity: PASS

## Runtime validation still required on Odoo.sh Staging
1. Toggle Featured ON and confirm the product appears in **الأكثر تميزًا** above the regular product grid.
2. Toggle Featured OFF and confirm it disappears from that section while remaining normally available in its category/menu.
3. Confirm configured Badges (Best Seller/New/Chef/Seasonal/etc.) pulse visibly but gently.
4. Confirm centered modal, offers, banners, iPhone category scrolling, and mobile-media override remain unchanged.
5. Review Odoo.sh logs after module upgrade.
