# Installation & Upgrade — FlexSys POS Device Access

## Prerequisites

1. Odoo 19 is running normally.
2. Point of Sale is installed.
3. Employee Login (`pos_hr`) is enabled on every POS that will use Device Access.
4. Production is served over HTTPS.

## Install

1. Copy `flexsys_pos_device_access` into an addons path.
2. Restart Odoo if required by the deployment method.
3. Update the Apps list.
4. Install **FlexSys POS Device Access**.
5. Confirm **Point of Sale → Configuration → Device Access** is visible to POS Managers.

## Upgrade

1. Back up the database before upgrading production.
2. Replace the previous module directory with the new version.
3. Restart/redeploy Odoo.
4. Upgrade `flexsys_pos_device_access` from Apps or with the normal Odoo upgrade command used by your environment.
5. Run **Test Device Access** on existing device records.
6. Test one device end-to-end before rolling out broadly.

## Production acceptance

- Pairing Link works only for the first successful browser.
- Reusing the consumed link is rejected.
- `/flexsys/pos/device/start` works on the paired browser.
- Employee PIN remains mandatory.
- Backend navigation is blocked.
- Switching to another POS is blocked.
- Reset Pairing invalidates the current browser credential.
- Revoke Access blocks the device.
- Audit events appear as expected.


## FlexSys Support

info@flexsyssa.com
