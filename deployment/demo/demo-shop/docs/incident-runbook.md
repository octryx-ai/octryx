# Incident runbook (Demo Shop, fictional)

## Severity

| Level | Meaning | First response |
|---|---|---|
| SEV1 | Customers cannot place an order | within 15 minutes, page the on-call engineer |
| SEV2 | A feature is degraded (for example wrong totals or shipping fees) | within 1 hour |
| SEV3 | Cosmetic or internal only | next working day |

## Steps

1. Acknowledge the alert and open an incident note with the start time.
2. Check the last release: a rollback is the default answer to a SEV1 caused by a release.
3. Write a status update every 30 minutes until the incident is resolved.
4. For wrong order totals, list the affected orders so they can be corrected afterwards.
