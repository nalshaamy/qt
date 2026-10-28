# FlexSys Recruitment Portal — RC4 CSS Hotfix QA

**Module:** `flexsys_recruitment_portal`  
**Version:** `19.0.1.0.3` (RC4 — Staging only)  
**Source:** RC3 19.0.1.0.2. No frontend Website dependency.  
**Issue reported:** `/careers` shown with huge unstyled company logo, Odoo message “A css error occured, using an old style to render this page”; separate JavaScript `IDBQuotaExceededError` in `web.assets_web.min.js`.

## Diagnosis and scope

- The `/careers` QWeb page appears to load, but its styles do not. RC3 registered an SCSS file as a custom Odoo asset bundle and called it via `t-call-assets`. This is a credible source of the visible CSS compilation/fallback error; full root-cause confirmation would require the corresponding **Odoo.sh server log**.
- The browser's `IDBQuotaExceededError` is emitted from `web.assets_web.min.js` (Odoo webclient) and generally indicates that local browser IndexedDB storage quota is exceeded. We cannot conclude from the screenshot that it was caused by this Careers module. RC4 does not modify Odoo's upstream IndexedDB handling.

## What changed

1. Removed the `assets` manifest section and the two `t-call-assets` usages from Careers QWeb pages.
2. Converted nested SCSS to browser-native *flat CSS* in `static/src/css/careers.css`, eliminating runtime SCSS compilation for this portal.
3. Referenced the stylesheet and existing JS directly through standard static URLs, with versioned query strings to avoid stale browser cache.
4. Set explicit `width` and `height` HTML attributes plus inline maximum dimensions on the header logo. The logo remains limited to 52 × 52 CSS pixels even if the CSS file fails to load.
5. Left the privacy, application processing, recruitment models, multi-company selection, and brand CSS-variable generation behavior unchanged.
6. Added four targeted standalone regression tests under `tests/test_standalone_assets.py`.

## Local verification actually executed

| Test | Result | What it proves |
|---|---|---|
| RC3 baseline independent regression suite, adapted to RC4 | **58/58 PASS** | Validators, file formats, brand engine, translations, technical Website-free conditions |
| New standalone asset unit tests | **4/4 PASS** | No SCSS asset bundle, direct link, XML, flat CSS, 52px logo attributes |
| Chromium responsive smoke (390px, 1440px) | **2/2 PASS** | Local CSS layout, brand custom property applied, logo is 52 × 52px, no horizontal overflow |
| XML syntax | **9/9 PASS** | lxml parses all addon XML files |
| Arabic translation import structure | **PASS** | Babel PO parsing and 16 Odoo module markers |
| Python compilation | **20/20 PASS** | Syntax only, not Odoo registry installation |
| JavaScript syntax | **1/1 PASS** | `node --check` |
| Manifest and declared file paths | **PASS** | Updated version, no `website`, no asset declaration |
| ZIP integrity | **PASS** | Verified after packaging |

**Not tested here:** live CSS response from the staging host, Odoo module upgrade, QWeb rendered inside Odoo 19, compatibility with other addons, network/browser IndexedDB quota after clearing storage, actual CV submissions and access controls. Do not mark Odoo.sh acceptance cases complete based solely on local tests.

## Staging upgrade procedure

1. Commit/replace the entire `flexsys_recruitment_portal` directory in the **staging branch** with RC4. Do not deploy to Production.
2. In Odoo.sh confirm a successful build, then upgrade the already installed module (or install if absent).
3. Open `https://nalshaamy-qt-staging-39272377.dev.odoo.com/flexsys_recruitment_portal/static/src/css/careers.css?v=19.0.1.0.3` — it must return a CSS text response (HTTP 200), **not** HTML/404.
4. Open `/careers?debug=1` and then `/careers/apply`, hard-refresh (Ctrl+Shift+R); verify CSS loaded, logo 52px, working mobile layout, privacy page and functioning form (use synthetic data only).
5. If `IDBQuotaExceededError` persists, retry first in a fresh Incognito window. If Incognito works, clear **only the staging site's stored data** in Chrome after saving work and stopping any unsynced operations; sign in again. Do not indiscriminately delete Odoo server attachments, databases or Production/POS offline data.
6. If the red CSS compilation warning persists globally (for instance `/web` or unrelated pages), inspect **Odoo.sh server logs** for the original SCSS/asset compiler failure: a different installed addon or global asset may be at fault. Do not assume RC4 fixes every addon.

**Release status:** RC4 is a CSS-isolation hotfix validated offline, **not** production-approved.
