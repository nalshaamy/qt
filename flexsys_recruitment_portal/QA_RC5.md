# FlexSys Recruitment Portal — RC5 minimal direct dependencies

**Version:** 19.0.1.0.4 (RC5 — for Staging)  
**Based on:** 19.0.1.0.3 RC4 (CSS Hotfix)

## Change

- Removed `web` from this addon's **direct** `__manifest__.py` dependencies; only `hr_recruitment` remains.
- Continued to omit the `website` addon (since RC3).
- Kept standalone QWeb HTTP routes and direct CSS/JS static links. Bumped their query-version to `19.0.1.0.4` without changing their contents.
- Added static dependency regression tests; updated CSS regression test for the new asset URL version.
- No candidate data, database tables, access rules or business workflows were intentionally changed in RC5.

## Important: Odoo's web addon remains installed

This is **not** a complete removal of Odoo's `web` application or core browser infrastructure. In Odoo 19, the official dependency chain includes `hr_recruitment` → `hr` → `web`, so `web` remains a **transitive** dependency regardless of the direct manifest change. The Odoo web client is also required for the standard Recruitment backend. Do not attempt to uninstall `web` from an existing Odoo database.

This change alone **does not resolve** IndexedDB `IDBQuotaExceededError`, which is a browser-side storage issue reported on the staging host.

## Staging upgrade

1. Replace the complete `flexsys_recruitment_portal` addon folder in the staging Git branch with RC5.
2. Build the branch; run **Upgrade** (if installed) or **Install** (if not).
3. Open `/careers`, `/careers/apply`, and `/careers/privacy`; confirm direct CSS and JS URLs return HTTP 200, and the page is styled properly.
4. Submit a **synthetic** test application (do not use real candidate information); verify access rules, CV privacy, Talent Pool links, and absence of duplicate records on retry.
5. Reconfirm compatibility with other installed addons and validate the 38 acceptance cases on staging.

## Local verification actually completed

- 58/58 independent regression tests passed (validated against the RC5 manifest and asset version).
- 3/3 new dependency-focused standalone tests passed.
- 4/4 standalone CSS/asset tests passed.
- 9/9 XML files parsed successfully.
- 16/16 Arabic translation entries were parsed and had module markers.
- 21 Python files parsed successfully; `compileall` passed.
- JavaScript passed `node --check`.
- The final ZIP passed CRC/integrity checks.

**Total independent test assertions by suite: 65/65 passed.** The other static validations are not added to that test count.

## Verification limits

Static/standalone tests are not a substitute for Odoo 19 registry load, module upgrade and live HTTP tests. RC5 is not approved for Production until those pass.
