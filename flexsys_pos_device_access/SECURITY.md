# Security Model — FlexSys POS Device Access 19.0.1.1.0

- Pairing tokens are 256-bit URL-safe random secrets and are short-lived.
- Pairing tokens are stored only as SHA-256 hashes.
- Pairing is serialized with a database row lock so only one concurrent browser can win first-device binding.
- Successful pairing creates a different 256-bit device credential.
- Raw device credentials are stored only in a host-scoped `Secure`, `HttpOnly`, `SameSite=Lax` cookie.
- Odoo stores only the device credential SHA-256 hash.
- Reset/Revoke increments `credential_version`; already-authenticated POS service-user sessions carry the old version and are blocked immediately on their next guarded navigation/PIN audit.
- Employee PINs are never received or stored by the device gateway. Native `pos_hr` verifies the employee PIN.
- The POS service user must be internal, non-system, company-scoped and limited to POS access.
- Device sessions are confined to the configured `pos.config`; Backend navigation and POS switching are blocked and audited.
- Optional IP/CIDR allowlists and public-endpoint rate limiting are supported.
- Access logs never store raw pairing tokens, raw device credentials, or employee PINs.

## Threat-model boundary

V1.1 binds a browser profile, not TPM/MDM-backed physical hardware. Copying the Pairing Link after it has been consumed will not work. Theft/export of the paired browser's cookie store requires endpoint-level controls outside this module (OS account security, kiosk mode, MDM, disk encryption, etc.).
