# Security Notes

## Threat model

The Secure Token is an authentication credential for a physical POS device. Anyone who obtains the raw URL can establish the configured technical user's Odoo session until the token is revoked or expires. Therefore:

- Always use HTTPS.
- Use a dedicated, least-privilege internal POS user.
- Never bind an Administrator/System user.
- Rotate immediately if a device is lost or the URL is exposed.
- Prefer kiosk/managed browser deployment on branch devices.
- Consider Cloudflare/WAF rate limiting in front of Odoo.sh in addition to the module's database-backed limit.
- Consider an IP/CIDR allowlist only after confirming the client IP seen by Odoo.sh.

## Why cashier PIN is preserved

The device token identifies the workstation and selects its POS configuration. It does not identify the human operator. Odoo's native employee lock/PIN screen remains the second verification layer and provides cashier accountability.

## Session implementation

Odoo 19's own `Session.finalize()` stores `db`, `login`, `uid`, user context and a session token derived from the session id and user security state. This module mirrors that final session structure only after the device token has been successfully validated, then redirects to the standard Point of Sale route.
