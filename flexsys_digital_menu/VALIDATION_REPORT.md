# FlexSys Digital Menu — Validation Report

Version: 19.0.1.0.3

## Implemented change

- Reworked the product **Digital Menu** tab to match the simple FlexSys Operations UX pattern.
- One user-facing master checkbox only: **Show in Digital Menu**.
- Removed the product-level availability selector from the normal UI; availability remains engine-driven.
- Added simple proxy controls over the canonical `flexsys.menu.product` assignment: Menu, Menu Category, Display Order.
- Kept multi-menu / branch / price / availability / schedule overrides behind **Advanced Settings**.
- Simple assignments are menu-wide and inherit the menu's branches.
- Existing branch-only assignments remain visible in simple mode and are promoted to a base/menu-wide rule when edited in simple mode.
- Creating a `flexsys.menu.product` assignment automatically turns on **Show in Digital Menu**.
- **Show in Digital Menu** is now the master visibility switch.
- Simplified the Main Menu → Products list; technical override columns are hidden by default.

## Static validation

- Python compile: PASS
- XML well-formed parse: PASS
- JavaScript syntax (`node --check`): PASS
- Manifest version: PASS (`19.0.1.0.3`)
- Odoo 19 search-view compatibility fix retained: PASS
- Product detail large image: PRESENT
- Conditional description box: PRESENT
- Automatic one-product recommendation: PRESENT
- Single product-level public visibility checkbox: PRESENT

## Runtime status

The previous `19.0.1.0.2` build installed successfully on the user's Odoo.sh Odoo 19 staging database. This `19.0.1.0.3` build changes backend UX/model proxy behavior and therefore still requires a normal module **Upgrade** on staging and browser acceptance before release-candidate status.
