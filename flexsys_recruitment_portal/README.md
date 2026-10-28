# FlexSys Recruitment Portal — Odoo 19

**Release candidate:** `19.0.1.0.2` · **Public route:** `https://qtcafe.sa/careers` (no Website app required)

## Deployment

1. Place the `flexsys_recruitment_portal/` folder inside an Odoo.sh Git repository addons path.
2. Update the Odoo apps list and install **FlexSys Recruitment Portal**; dependencies are `web` (core web client) and `hr_recruitment` (Recruitment). `mail` is supplied transitively by Recruitment; the Website addon is not a dependency.
3. In the standalone **General Applications** menu, open **Configuration**, choose the company which will receive applications and press **Use for Public /careers**. The installation hook creates one configuration and talent pool for the database environment company.
4. Check the selected company, Talent Pool and career categories. The hook seeds English initial categories per company and they can be translated or renamed.
5. Enter your **reviewed, accurate Arabic/English privacy notice** and retention policy before collecting live personal data.
6. Upload a Candidate Logo. Choose Automatic / Custom / Automatic with Overrides. Click **Generate Brand Preview** → **Open Visual Preview** → **Publish Brand**.
7. Open `https://qtcafe.sa/careers` and `/careers/apply`. No DNS or CNAME changes are necessary **only if** qtcafe.sa already routes to this Odoo.sh instance.
8. Run actual tests on Staging before any Production deployment.

## Features included

- Public `/careers`, `/careers/apply`, `/careers/submit`, `/careers/success`, `/careers/privacy` routes and isolated frontend assets.
- Creation of `hr.applicant` with `job_id=False`, native Talent Pool linkage, protected CV file, generated reference, and duplicate marker.
- Submitted request ledger with PostgreSQL UNIQUE constraint and idempotent response to repeated request IDs.
- Saudi mobile normalization, typed server validations and allowed career categories per configured company.
- PDF structural screening, DOCX structural screening available but **disabled by default** pending approved malware scanning. Default CV size 5 MiB.
- Cross-company configuration constraints; HR permissions and private submissions.
- Hash-only request attempt logging, 20 attempts / 30 minutes and 5 recorded submissions / 30 minutes per requester + company; daily purge for attempt metadata.
- Basic queued email acknowledgement when the applicant provides an address.
- Company-bound logo-to-color extraction, WCAG-targeted contrast, publish-only brand preview, overrides via validated JSON and CSS token scoping.
- Arabic translation catalogue (may require translation verification with installed database languages).

## Important production limitations / open acceptance items

This bundle was built and checked **without a local Odoo runtime**. Independent tests run in `offline_tests`, but install, end-to-end HTTP, Odoo ACL, Odoo.sh and native Talent Pool transitions must be tested on Odoo 19 Staging. A release candidate is **not** a production-certified build.

- Antivirus / advanced PDF malware inspection is not bundled. Do not permit public PDF/DOCX uploads in production until a suitable scanning and quarantine policy is approved and integrated. DOCX remains disabled by default.
- The retention period is for **review**, not automatic erasure; counsel and a privacy owner must approve handling and deletion procedures.
- The Backend dashboard uses standard Odoo list/graph/pivot analysis, not a bespoke KPI card dashboard.
- Additional companies may have their own careers configs and talent pools. Since `/careers` is a single shared path, a Careers Manager explicitly selects the active company with **Use for Public /careers**. No browser-supplied company selector is accepted.
- The public confirmation/reference page discloses no applicant data and is not a status-tracking service.
- Email sending depends on Odoo mail queue/outgoing SMTP setup.
- The design tries to avoid clashes with Digital Menu but interoperability needs Staging verification.
- Permissions must be exercised with real HR staff and companies, including restricted group combinations.

## Development and checks

- Static compile: `python -m compileall -q flexsys_recruitment_portal`
- Offline tests (host with pytest and Pillow): `python -m pytest -q offline_tests`
- Odoo.sh Staging: install with Odoo tests enabled and run `tests/test_core_odoo.py`, then manually execute all 38 acceptance tests described in `TSD_v1.1.md`.

## Portal colors

Manual overrides are JSON using lowercase token names, e.g. `{"primary":"#123456","accent":"#334455"}`. Invalid colors are rejected; text colors are adjusted to ensure readable contrast. The candidate logo and palette are **not public** until **Publish Brand** is pressed.

## Privacy defaults

The default privacy text is a placeholder. Do not collect personal information until the actual notice, retention handling and contact details have been approved. Submitters must acknowledge the published notice.

## Build status

Refer to `QA_REPORT.md` alongside the package for exact evidence, test counts and unresolved checks.

## Website-free configuration / upgrade notes (RC3)

- This addon does **not** install or require the Odoo Website application. It uses standard Odoo HTTP routes (`auth='public'`, `type='http'`) and standalone `request.render()` QWeb templates.
- The published `/careers` path selects its receiving company using an explicit server-side `ir.config_parameter`: `flexsys_recruitment_portal.public_config_id`. Administrators should use **Use for Public /careers**, not edit the parameter manually.
- On a **fresh install**, the post-install hook creates an initial company configuration and selects it. Confirm the company in Configuration before submitting real applications.
- Multiple company configs are supported, but only one serves the shared `/careers` path at a time.
- **Existing RC2 installations:** RC2 used a required `website_id` and allowed multiple configurations per website. If RC2 was installed and multiple websites for a single company are present, the supplied RC3 pre-migration removes the obsolete column's NOT NULL requirement and stops the upgrade if multiple configs belong to the same company. Preserve and manually reconcile conflicting branding/settings on a staging backup before retrying; the post-migration selects the single existing company configuration for `/careers`. RC2 install failures normally roll back installation.
- **Removing a dependency does not uninstall an already installed Website addon.** Manage uninstallation separately after checking other modules depend on it.


### RC4 hotfix — CSS isolation (19.0.1.0.3)

The public careers pages use a browser-native stylesheet at
`/flexsys_recruitment_portal/static/src/css/careers.css` and a normal
`<script defer>` tag. They do **not** register SCSS or use `t-call-assets`,
so no Odoo asset compilation is necessary for Careers. All selectors are
scoped to `.fs-careers`. The logo has fixed HTML dimensions in case the
stylesheet is temporarily unavailable. A page view may still expose an
independent Odoo webclient IndexedDB quota error; resolve that through
browser site storage and/or Odoo's own upstream fixes, not by modifying
applicant data.


### RC5 — minimal direct dependencies (19.0.1.0.4)

The direct manifest dependency is only `hr_recruitment` (no direct `web` or `website` entry). Note: the core `web` addon is **still installed transitively** through official `hr` dependencies. See `QA_RC5.md`.
