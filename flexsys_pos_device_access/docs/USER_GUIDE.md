# User Guide — FlexSys POS Device Access

## Create a device

Go to **Point of Sale → Configuration → Device Access → Devices** and create a record.

Set:

- Device name
- Company
- Point of Sale
- POS Service User (or use the FlexSys-managed user)
- Optional IP/CIDR restriction
- Pairing Link validity
- Credential expiry policy

## Test before pairing

Click **Test Device Access**. Resolve any reported problems before generating a Pairing Link.

## Pair a cashier browser

1. Click **Generate Pairing Link**.
2. Copy the one-time URL.
3. Open it on the intended cashier terminal using the normal browser profile.
4. Do not pair from Private/Incognito mode.
5. The browser is paired and redirected to the target POS login screen.
6. The cashier enters their normal employee PIN.

## Daily use

The paired browser can start at:

`/flexsys/pos/device/start`

The Device Credential identifies the trusted browser. The employee PIN identifies the cashier.

## Replace a device/browser

Use **Reset Pairing**, then generate a new Pairing Link and pair the replacement browser.

## Disable vs revoke

- **Disable**: temporarily stops the device while preserving the record.
- **Revoke Access**: invalidates the current credential and pairing material. Use for retired or compromised devices.

## Audit logs

Open **Access Logs** from the Device record or Device Access menu. Typical events include pairing success, device access success, rejected token/credential attempts, reset/revoke, blocked Backend access, blocked POS switching, and cashier PIN-success metadata.


## FlexSys Support

info@flexsyssa.com
