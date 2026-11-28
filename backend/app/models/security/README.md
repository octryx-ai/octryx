# Security models

The stored state of policies and the data that controls access: the Cedar policy sets and their decision log,
the classification policy, content handling and routing, content trust, devices, mobile pairings, OAuth grants
and linked accounts.

## Invariants

- A published custom policy-set version or classification-policy version changes only by its move to `retired`,
  and a published or retired one is never deleted (`runtime/governed_revision.install_immutability_guard`, installed
  in `policy_engine.py` and `classification_policy.py`).
- A Workspace has at most one content-handling row per kind (`uq_workspace_content_handling`) and at most one
  governance alias (`WorkspaceContentGovernance`, keyed by the Workspace) (`content_handling.py`).
- Mobile pairing codes, scan secrets, claims and phone credentials are stored as SHA-256 hashes only (the `*_hash`
  columns in `mobile.py`).
- A device has exactly one owner (`UserDevice.owner_user_id`, not null, `device.py`).
