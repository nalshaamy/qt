# FlexSys POS Device Access — Odoo 19

Version: **19.0.1.1.0**

## V1.1 Device Pairing

FlexSys POS Device Access binds a cashier browser to one Odoo POS configuration while preserving Odoo's native employee PIN verification.

Flow:

1. Manager creates a device record and generates a short-lived **one-time Pairing Link**.
2. The first browser that opens the link becomes paired.
3. The pairing link is consumed immediately and cannot pair another browser/device.
4. FlexSys generates a separate 256-bit device credential, stores only its SHA-256 hash in Odoo, and places the raw credential in a **Secure + HttpOnly + SameSite=Lax** host cookie.
5. Daily entry uses `/flexsys/pos/device/start`.
6. The device credential establishes the minimum-permission POS service-user session and opens the fixed `/pos/ui/<config>/login` route.
7. The cashier must still enter their native Odoo POS employee PIN.
8. Backend navigation and attempts to switch to another POS are blocked for device sessions.

## Administration

- Generate / rotate one-time Pairing Link
- Reset Pairing (invalidates current browser credential and open device sessions)
- Revoke Access
- Disable device
- Optional IP/CIDR restriction
- Credential expiry policy
- Audit logs
- Managed minimum-permission POS service user

## Upgrade from 19.0.1.0.x

Existing V1.0 Secure Links are treated as **legacy one-time pairing links** after upgrade. A legacy link can be consumed once to pair the browser, after which it is invalidated. Managers can instead generate a new V1.1 Pairing Link.

## Security note

The pairing mechanism binds the **browser profile** through an HttpOnly credential cookie. It prevents copying the Pairing Link to another device after first use. It is not hardware attestation; an attacker with the ability to export browser secrets/cookies from the paired workstation is outside this V1.1 threat model.
