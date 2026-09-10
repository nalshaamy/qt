# FlexSys POS Device Access — Odoo 19

Version: **19.0.1.0.0**  
Commercial package status: **Release Candidate**

FlexSys POS Device Access pairs a cashier browser to one Odoo POS configuration while preserving Odoo's native employee PIN verification.

## Core flow

1. A POS manager creates a device record.
2. FlexSys validates the target POS and the minimum-permission POS Service User.
3. The manager generates a short-lived, one-time Pairing Link.
4. The first browser that successfully opens the link becomes paired.
5. The Pairing Link is consumed immediately and cannot pair another browser/device.
6. FlexSys creates a separate 256-bit device credential and stores only its SHA-256 hash on the persistent device record.
7. The raw device credential is delivered to the paired browser through a Secure + HttpOnly + SameSite=Lax cookie.
8. Daily device entry uses `/flexsys/pos/device/start`.
9. The device session opens the fixed `/pos/ui/<config>/login` route.
10. The cashier must still enter their native Odoo POS employee PIN.
11. Backend navigation and attempts to switch to another POS are blocked for device sessions.

## Features

- One-time browser/device pairing
- Short-lived Pairing Links: 5, 10, 30, or 60 minutes
- Secure 256-bit device credentials
- Pairing and credential hashes on persistent records
- Secure + HttpOnly device credential cookie
- Native Odoo employee PIN verification remains mandatory
- Fixed POS binding per device
- Backend guard for device-authenticated sessions
- Cross-POS navigation guard
- Reset Pairing and Revoke Access
- Credential version invalidation for stale sessions
- Optional IP/CIDR restriction
- Optional credential expiry policy
- Managed minimum-permission POS Service User per company
- Device Access preflight test
- Audit logs with configurable retention
- Multi-company record rules
- Arabic UI translations

## Requirements

- Odoo 19
- `point_of_sale`
- `pos_hr` / Employee Login enabled on the target POS
- `web`
- HTTPS in production (required for the Secure device cookie)

No external service, activation server, or third-party API is required.

## Installation

Copy the `flexsys_pos_device_access` directory into an Odoo addons path, update the Apps list, and install **FlexSys POS Device Access**.

See `docs/INSTALLATION.md` for the complete checklist.

## Administration

From **Point of Sale → Configuration → Device Access**:

- Create and bind a device to one POS
- Use the FlexSys-managed POS Service User or assign a compatible limited internal user
- Test configuration before pairing
- Generate/rotate a one-time Pairing Link
- Reset Pairing when replacing a browser/device
- Revoke or disable a device
- Review Access Logs

See `docs/USER_GUIDE.md`.

## Data and privacy

The module does not send customer or device data to FlexSys or another external service. Device metadata and audit events remain in the customer's Odoo database.

Persistent device records do **not** store raw Pairing Tokens or raw Device Credentials. A generated Pairing URL is surfaced through an Odoo transient wizard so an administrator can copy it during setup; the persistent device record stores the hash only.

Employee PIN values are not received or stored by the FlexSys gateway. Native Odoo POS (`pos_hr`) performs the cashier PIN verification.

## Security boundary

V1.1 binds a **browser profile**, not physical hardware with TPM/MDM attestation. Copying a Pairing Link after successful pairing does not work. Theft/export of the paired browser's cookie store requires endpoint controls outside this module.

See `SECURITY.md` and `docs/SECURITY_OPERATIONS.md`.

## Upgrade from 19.0.1.0.x

Existing V1.0 Secure Links are treated as legacy one-time pairing links after upgrade. A legacy link can be consumed once to pair the browser, after which it is invalidated. A manager may instead generate a new V1.1 Pairing Link.

## Versioning

`19.0.1.0.0` is the commercial packaging and documentation release based on the tested V1.1 Device Pairing implementation. It does not change the Device Pairing architecture introduced in `19.0.1.1.0`.

## Support

Official FlexSys support email: **info@flexsyssa.com**

## License

The module license remains the value currently declared in `__manifest__.py`. It was intentionally not changed as part of this commercial packaging pass.
