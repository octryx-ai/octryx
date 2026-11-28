# Policy routes

The Cedar policy engine admin API, the classification policy and its governed versions, data classification
settings and the platform approval rule. The rules live in `services/policy_engine`,
`services/data_classification` and `services/governance`.

## Invariants

- The policy engine admin routes are for platform admins only (`policy_engine.require_admin`).
- The classification policy has no direct write route: it changes only through a governed version
  (`classification_policy.py`, `classification_policy_versions.py`).
