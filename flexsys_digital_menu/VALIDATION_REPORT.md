# FlexSys Digital Menu 19.0.1.0.22 — Validation Report

## Scope
Patch release built directly from 19.0.1.0.21 after Staging regression review.

## Runtime behavior changed
- Removed the automatic `Featured / مميز` card chip introduced in 0.21.
- `Featured` remains a ranking signal and featured products still sort first in the continuous **All** grid.
- Explicit product `Badge` rendering is restored as the only marketing badge shown on product cards.
- Existing badge pulse behavior is preserved through `badge_pulse` and `.fsm-badge.pulse`.

## Preserved 0.21 fixes
- Centered product modal.
- Product/menu media revision URLs and cache invalidation.
- Explicit mobile banner override selection.
- Mobile banner `contain` fallback when no mobile override exists.
- iOS category edge padding / horizontal scroll behavior.

## Static validation
- Python compile: PASS
- Manifest parse/version: PASS (`19.0.1.0.22`)
- XML parse: PASS (17 XML files)
- JavaScript syntax: PASS
- Arabic PO structural parse: PASS
- Legacy `_sql_constraints` scan: PASS (none found)
- Featured auto-chip absent: PASS
- Featured sorting retained: PASS
- Explicit Badge + pulse path retained: PASS
- Centered modal CSS retained: PASS
- Static asset cache-busting updated to 0.22: PASS
- ZIP integrity: PASS

## Runtime validation still required on Odoo.sh Staging
1. Confirm a Featured product sorts first but does **not** show an automatic `مميز` chip.
2. Confirm configured Badge (Best Seller/New/Chef/etc.) renders in its previous position and pulses when applicable.
3. Confirm centered modal, iPhone category scrolling, and banner mobile override remain unchanged.
4. Review Odoo.sh logs after module upgrade.
