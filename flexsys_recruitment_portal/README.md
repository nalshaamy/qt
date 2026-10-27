# FlexSys Recruitment Portal — Odoo 19

**Release candidate:** `19.0.1.0.1` · **Website:** `https://qtcafe.sa/careers`

## Deployment

1. Place the `flexsys_recruitment_portal/` folder inside an Odoo.sh Git repository addons path.
2. Update the Odoo apps list and install **FlexSys Recruitment Portal**; dependencies include Website and Recruitment.
3. In the standalone **General Applications** menu, open **Configuration**, choose the website attached to `qtcafe.sa`. The installation hook creates one config and Talent Pool for each existing website.
4. Check the selected company, Talent Pool and career categories. The hook seeds English initial categories per company and they can be translated or renamed.
5. Enter your **reviewed, accurate Arabic/English privacy notice** and retention policy before collecting live personal data.
6. Upload a Candidate Logo. Choose Automatic / Custom / Automatic with Overrides. Click **Generate Brand Preview** → **Open Visual Preview** → **Publish Brand**.
7. Open `https://qtcafe.sa/careers` and `/careers/apply`. No DNS or CNAME changes are necessary **only if** qtcafe.sa already routes to this Odoo.sh instance.
8. Run actual tests on Staging before any Production deployment.

## Features included

- Public `/careers`, `/careers/apply`, `/careers/submit`, `/careers/success`, `/careers/privacy` routes and isolated frontend assets.
- Creation of `hr.applicant` with `job_id=False`, native Talent Pool linkage, protected CV file, generated reference, and duplicate marker.
- Submitted request ledger with PostgreSQL UNIQUE constraint and idempotent response to repeated request IDs.
- Saudi mobile normalization, typed server validations and allowed career categories per website company.
- PDF structural screening, DOCX structural screening available but **disabled by default** pending approved malware scanning. Default CV size 5 MiB.
- Cross-company configuration constraints; HR permissions and private submissions.
- Hash-only request attempt logging, 20 attempts / 30 minutes and 5 recorded submissions / 30 minutes per requester + company; daily purge for attempt metadata.
- Basic queued email acknowledgement when the applicant provides an address.
- Company/website-bound logo-to-color extraction, WCAG-targeted contrast, publish-only brand preview, overrides via validated JSON and CSS token scoping.
- Arabic translation catalogue (may require translation verification with installed website languages).

## Important production limitations / open acceptance items

This bundle was built and checked **without a local Odoo runtime**. Independent tests run in `offline_tests`, but install, end-to-end HTTP, Odoo ACL, Odoo.sh and native Talent Pool transitions must be tested on Odoo 19 Staging. A release candidate is **not** a production-certified build.

- Antivirus / advanced PDF malware inspection is not bundled. Do not permit public PDF/DOCX uploads in production until a suitable scanning and quarantine policy is approved and integrated. DOCX remains disabled by default.
- The retention period is for **review**, not automatic erasure; counsel and a privacy owner must approve handling and deletion procedures.
- The Backend dashboard uses standard Odoo list/graph/pivot analysis, not a bespoke KPI card dashboard.
- Configuration changes to newly created websites require manually creating a careers config and a talent pool.
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
