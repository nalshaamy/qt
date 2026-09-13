# FlexSys POS Device Access — Odoo 19

Store app name: **POS Device Access**  
Brand: **FlexSys**

Version: **19.0.1.0.1**  
Commercial package status: **Release Candidate**

FlexSys POS Device Access pairs a cashier browser to one Odoo POS configuration while preserving Odoo's native employee PIN verification.

## Core flow

1. A POS manager creates a device record.
2. FlexSys validates the target POS and the existing Linked POS User selected by the administrator.
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
- Administrator-selected existing Linked POS User
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

Copy the `flexsys_pos_device_access` directory into an Odoo addons path, update the Apps list, and install **POS Device Access**.

See `docs/USER_GUIDE.md` for installation, setup, pairing, and runtime acceptance.

## Administration

From **Point of Sale → Configuration → Device Access**:

- Create and bind a device to one POS
- Select an existing compatible internal Odoo user with Point of Sale access
- Test configuration before pairing
- Generate/rotate a one-time Pairing Link
- Reset Pairing when replacing a browser/device
- Revoke or disable a device
- Review Access Logs

See `docs/USER_GUIDE.md`.

## Data and privacy

The module does not send customer or device data to FlexSys or another external service. Device metadata and audit events remain in the customer's Odoo database.

Persistent device records do **not** store raw Pairing Tokens or raw Device Credentials. A generated Pairing URL is surfaced to the administrator in a modal, but the raw URL/token is not written to either persistent records or transient wizard rows; only the hash is stored on the device record.

Employee PIN values are not received or stored by the FlexSys gateway. Native Odoo POS (`pos_hr`) owns the cashier verification flow; FlexSys records a post-login cashier audit event only.

## Security boundary

V1.1 binds a **browser profile**, not physical hardware with TPM/MDM attestation. Copying a Pairing Link after successful pairing does not work. Theft/export of the paired browser's cookie store requires endpoint controls outside this module.

See `SECURITY.md` for the security model and operational response guidance.


## Documentation

- `docs/USER_GUIDE.md` — installation, device setup, pairing, daily use, and production acceptance
- `SECURITY.md` — security model, threat boundary, and operational response
- `docs/PUBLISHING_CHECKLIST.md` — final Odoo Apps release checklist
- `CHANGELOG.md` — release history

## Versioning

`19.0.1.0.1` is the first approved commercial release candidate. It keeps the V1.1 Device Pairing architecture while tightening secret handling and making cashier audit wording technically precise.

## Support

Official FlexSys support email: **info@flexsyssa.com**

## License

The module license remains the value currently declared in `__manifest__.py`. It was intentionally not changed as part of this commercial packaging pass.

## Multi-database hosts

The first pairing URL starts from Odoo's server-wide login route:

`/web/login?db=<database>#flexsys_pair=<one-time-secret>`

This lets Odoo select the originating database for a completely fresh browser before the custom module route is used. The one-time secret is kept in the URL fragment during database selection, so it is not sent to `/web/login`. After the database is selected, a small frontend bootstrap forwards the browser to the database-bound pairing route automatically.

Device credential cookies are namespaced per database, so two databases served from the same hostname do not overwrite each other's paired-device credential.
