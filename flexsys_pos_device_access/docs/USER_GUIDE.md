# User Guide — FlexSys POS Device Access

## Prerequisites

- Odoo 19
- Point of Sale installed
- Employee Login (`pos_hr`) enabled on each target POS
- HTTPS in production
- An existing internal Odoo user with Point of Sale access to use as the **Linked POS User**

FlexSys does **not** create a `res.users` record automatically.

## Installation

1. Copy `flexsys_pos_device_access` into an Odoo addons path.
2. Restart or redeploy Odoo if required by your environment.
3. Update the Apps list.
4. Install **POS Device Access**.
5. Confirm **Point of Sale → Configuration → Device Access** is visible to POS Managers.

## Create a device

Go to **Point of Sale → Configuration → Device Access → Devices** and create a record.

Set:

- Device name
- Company
- Point of Sale
- **Linked POS User** — select an existing internal Odoo user with Point of Sale access
- Optional IP/CIDR restriction
- Pairing Link validity
- Credential expiry policy

Saving a device without a Linked POS User must be blocked.

## Test before pairing

Click **Test Device Access**. Resolve any reported problems before generating a Pairing Link.

The selected Linked POS User must:

- be active
- be an internal user
- have access to the device company
- have Point of Sale access
- not be a system administrator

## Pair a cashier browser

1. Click **Generate Pairing Link**.
2. Copy the one-time URL.
3. Open it on the intended cashier terminal using the normal browser profile.
4. Do not pair from Private/Incognito mode.
5. On multi-database hosts, Odoo first selects the originating database automatically.
6. The first successful browser becomes paired and the Pairing Link is consumed.
7. The browser is redirected to the assigned POS login screen.
8. The cashier enters their normal Odoo employee PIN.

The same consumed Pairing Link must not work on a second browser/device.

## Daily use

The paired browser can start at:

`/flexsys/pos/device/start`

The Device Credential identifies the trusted browser. The employee PIN identifies the cashier.

## Replace a device or browser

Use **Reset Pairing**, then generate a new Pairing Link and pair the replacement browser.

## Disable vs revoke

- **Disable**: temporarily stops the device while preserving the record.
- **Revoke Access**: invalidates the current credential and pairing material. Use for retired, lost, or compromised devices.

## Audit logs

Open **Access Logs** from the Device record or Device Access menu.

Typical events include:

- pairing success
- device access success
- rejected Pairing Token / credential attempts
- reset / revoke
- blocked Backend access
- blocked POS switching
- cashier-login metadata

## Production acceptance

Before publishing or deploying broadly, verify:

- Clean Install succeeds
- Arabic and English UI load correctly
- Browser A pairs successfully
- Browser B cannot reuse the consumed link
- Employee PIN remains mandatory
- Device reaches only its assigned POS
- Backend navigation is blocked for the paired device session
- Cross-POS navigation is blocked
- Reset Pairing invalidates the current browser credential
- Re-pair succeeds after reset
- Revoke Access blocks the device
- Multi-database pairing opens the intended database
- Uninstall → Install succeeds on a clean test database

## Support

**FlexSys**  
info@flexsyssa.com
