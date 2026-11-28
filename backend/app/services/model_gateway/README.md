# Model gateway

Policy, admission, credentials, budget and audit for governed model calls. Subpackages: `data_policy` (classification
gate), `inbound` (external coding agents), `litellm` (the governed LiteLLM client); each has its own README.

## Invariants

- An unregistered dispatch owner key gets no admission (`dispatch_owners.dispatch_owner`);
  `tests/model_gateway/test_dispatch_owner_inventory.py` fails on a dispatch site missing from the inventory.
- Workspace admission reads each project's own row; no caller passes a policy or config, an empty scope is
  `needs_configuration`, and a missing or inactive project is denied (`dispatch_admission.resolve_workspace_admission`).
- A governed cost source is read only from the `litellm_gateway` driver, and a `gateway_reported` turn without a
  positive reported cost settles as `gateway_cost_not_reported` (`cost_contract.resolve_governed_usage_cost`).
