# Security Operations Guide

## Recommended production baseline

- HTTPS enabled
- Pairing Link validity: 10 minutes
- Managed POS Service User with no system-administrator rights
- Employee Login enabled and PIN assigned to cashiers
- Audit-log retention appropriate to the customer's policy (default: 90 days)
- Endpoint OS account protected
- Browser profile dedicated to the cashier device where practical

## Incident: Pairing Link exposed before use

Rotate the Pairing Link immediately. The previous unused link becomes invalid.

## Incident: Cashier device lost or stolen

Revoke Access for the device record. Do not rely only on changing the employee PIN.

## Incident: Browser cookies cleared

The browser loses its Device Credential. Reset Pairing from Odoo and pair the intended browser again.

## Incident: Device replacement

Reset Pairing on the old record or revoke the old device and create a new device record, depending on the audit/history policy.

## Reviewing suspicious activity

Filter Access Logs for failed events, especially:

- Invalid Pairing Token
- Pairing Reuse Rejected
- Invalid Device Credential
- IP Denied
- Backend Access Blocked
- Other POS Access Blocked
- Stale Device Session Blocked


## FlexSys Support

info@flexsyssa.com
