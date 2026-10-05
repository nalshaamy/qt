# FlexSys Digital Menu 19.0.1.0.21 — Validation Report

## Scope
Final polish / RC fix pack applied to the tested 19.0.1.0.20 staging baseline after Desktop, Galaxy and iPhone acceptance testing.

## Fixes included
- Featured product card marker + Featured-first ordering in the continuous **All** grid.
- Existing product badge and Featured marker can coexist.
- Public JSON cache changed to immediate-refresh semantics for backend content edits.
- Write-date revision tokens added to public logo/category/product/offer/banner asset URLs.
- Explicit mobile banner override source selection.
- Desktop-banner mobile fallback uses `contain` when no mobile override exists.
- Centered product modal replaces side drawer / bottom sheet.
- iPhone category scroller safe padding / snap fix.
- Static CSS/JS cache-busting bumped to 19.0.1.0.21.

## Static validation performed
- Python compile: **PASS**
- XML parse: **PASS**
- JavaScript syntax (`menu.js`): **PASS**
- Manifest syntax/version: **PASS**
- Odoo 19 constraint style (`_sql_constraints` absent): **PASS**
- Feature assertions for modal/banner/cache/featured fixes: **PASS**
- ZIP structure/integrity: **PASS**

## Runtime status
Not executed against an Odoo runtime from this environment. The next required step is an Upgrade on Staging followed by focused regression of: Featured/Badges, iPhone banner override, centered product modal, iPhone category edges, then Odoo.sh logs.
