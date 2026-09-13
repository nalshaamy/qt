# Security Model — FlexSys POS Device Access 19.0.1.0.1

## Security properties

- Pairing tokens use 256-bit URL-safe randomness and are short-lived.
- Odoo database records, including transient wizard rows, never store raw Pairing Tokens. Persistent device records store only Pairing Token hashes.
- Pairing is serialized with a database row lock so only one concurrent browser can win first-device binding.
- Successful pairing creates a separate 256-bit Device Credential.
- Odoo stores only the Device Credential SHA-256 hash on the persistent device record.
- The raw Device Credential is delivered to the paired browser in a host-scoped `Secure`, `HttpOnly`, `SameSite=Lax` cookie.
- Reset/Revoke increments `credential_version`; already-authenticated POS service-user sessions with an older version are blocked on their next guarded navigation/PIN-audit request.
- Employee PINs are verified by native Odoo `pos_hr`; the device gateway does not receive or persist PIN values.
- The Linked POS User must be an existing internal, non-system, company-scoped Odoo user with POS access. FlexSys never creates a res.users record automatically.
- Device sessions are confined to their configured `pos.config`.
- Backend navigation and POS switching are blocked server-side and audited.
- Optional IP/CIDR allowlists are supported.
- Invalid token/credential attempts are rate-limited using recent audit events.
- Access logs never store raw Pairing Tokens, raw Device Credentials, or employee PIN values.

## Pairing-link handling

The one-time Pairing URL contains the raw Pairing Token and is delivered only in the action context used to render the administrator modal. It is not written to persistent or transient Odoo model fields. Treat the URL as a short-lived secret until it is consumed or expires.

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

## Backend confinement

FlexSys blocks normal Odoo Backend navigation and cross-POS navigation for paired device sessions and keeps the selected Linked POS User intentionally restricted. This is application-level confinement for the POS device flow; it is not advertised as a general-purpose network or RPC sandbox. Odoo POS still uses the Odoo APIs required for normal POS operation.

## Security operations

### Recommended production baseline

- HTTPS enabled
- Pairing Link validity: 10 minutes unless operations require otherwise
- Administrator-selected existing Linked POS User with no system-administrator rights
- Employee Login enabled and PIN assigned to cashiers
- Audit-log retention aligned with the customer's policy
- Endpoint OS account protected
- Dedicated cashier browser profile where practical

### Pairing Link exposed before use

Rotate the Pairing Link immediately. The previous unused link becomes invalid.

### Cashier device lost or stolen

Revoke Access for the device record. Do not rely only on changing the employee PIN.

### Browser cookies cleared

The browser loses its Device Credential. Reset Pairing from Odoo and pair the intended browser again.

### Device replacement

Reset Pairing on the old record or revoke the old device and create a new device record, depending on the customer's audit/history policy.

### Reviewing suspicious activity

Review failed events such as:

- Invalid Pairing Token
- Pairing Reuse Rejected
- Invalid Device Credential
- IP Denied
- Backend Access Blocked
- Other POS Access Blocked
- Stale Device Session Blocked

## Support

**FlexSys**  
info@flexsyssa.com


### Device-company session scope

A Linked POS User may have access to multiple Odoo companies. FlexSys scopes only the generated device-bound session to the company of the assigned POS. It does not modify the user's default company on `res.users`. This keeps Odoo's POS record rules and company-dependent data aligned with the assigned terminal.
