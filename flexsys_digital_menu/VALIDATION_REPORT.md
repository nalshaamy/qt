# FlexSys Digital Menu 19.0.1.0.18 — Validation Report

## Scope
Release adds the Promotional Banner Engine and tightens offer-image sizing without changing existing product/menu business data.

## Static validation performed
- Python compile: **PASS**
- XML parse for all XML files: **PASS**
- JavaScript syntax (`menu.js`, `brand_page.js`): **PASS**
- Manifest parse/version/data references: **PASS**
- Odoo 19 PO structural module comments: **PASS**
- Odoo 19 constraint style check (`_sql_constraints` absent): **PASS**
- Asset cache-busting version updated to `19.0.1.0.18`: **PASS**
- ZIP structure/integrity: validated during packaging

## New model / security
- `flexsys.menu.banner`
- User + Administrator ACLs
- Multi-company record rule

## Public behavior assertions
- Banner payload is empty when no active published banner exists.
- Active banners expose only public keys and dedicated media URLs.
- Banner layout uses a bounded, centered responsive container.
- Default banner fit is `contain`; `cover` is opt-in.
- Video media is rendered muted, looped and inline.
- Optional mobile media override is supported.
- Click URL accepts only safe relative paths or http(s) URLs.
- Offer image boxes remain compact and use `contain`.

## Runtime status
Not executed against the user's Odoo.sh runtime from this environment. Final acceptance still requires module Upgrade on Odoo 19 Staging and browser checks on desktop + mobile.
