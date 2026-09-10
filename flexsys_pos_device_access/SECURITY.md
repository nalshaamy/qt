# Security Model — FlexSys POS Device Access 19.0.1.0.0

## Security properties

- Pairing tokens use 256-bit URL-safe randomness and are short-lived.
- Persistent device records store Pairing Token hashes, not raw Pairing Tokens.
- Pairing is serialized with a database row lock so only one concurrent browser can win first-device binding.
- Successful pairing creates a separate 256-bit Device Credential.
- Odoo stores only the Device Credential SHA-256 hash on the persistent device record.
- The raw Device Credential is delivered to the paired browser in a host-scoped `Secure`, `HttpOnly`, `SameSite=Lax` cookie.
- Reset/Revoke increments `credential_version`; already-authenticated POS service-user sessions with an older version are blocked on their next guarded navigation/PIN-audit request.
- Employee PINs are verified by native Odoo `pos_hr`; the device gateway does not receive or persist PIN values.
- The POS Service User must be internal, non-system, company-scoped, and limited to POS access.
- Device sessions are confined to their configured `pos.config`.
- Backend navigation and POS switching are blocked server-side and audited.
- Optional IP/CIDR allowlists are supported.
- Invalid token/credential attempts are rate-limited using recent audit events.
- Access logs never store raw Pairing Tokens, raw Device Credentials, or employee PIN values.

## Pairing-link handling

The one-time Pairing URL contains the raw Pairing Token and is shown to the administrator through a transient Odoo wizard during setup. The persistent device record stores only the hash. Treat the URL as a short-lived secret until it is consumed or expires.

## Threat-model boundary

V1.1 binds a browser profile, not TPM/MDM-backed physical hardware. Copying the Pairing Link after it has been consumed will not work. Theft/export of the paired browser's cookie store is outside the module's threat model and should be mitigated with endpoint controls such as:

- OS account protection
- full-disk encryption
- browser/kiosk policies
- MDM where applicable
- restricted local administrator access

## Operational recommendations

- Use HTTPS only in production.
- Keep Pairing Link validity at 10 minutes unless operations require otherwise.
- Pair from the cashier terminal's normal browser profile, not Private/Incognito mode.
- Use Reset Pairing when replacing a browser or workstation.
- Revoke devices that are lost, retired, or suspected compromised.
- Review failed pairing and blocked-navigation events periodically.
- Apply IP/CIDR restrictions only where branch networking is stable and predictable.
