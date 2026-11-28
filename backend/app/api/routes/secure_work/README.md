# Secure Work routes

The Secure Work REST: Work items, Change Units and plans, intake, coding pipelines, ServiceNow and the explicit Close.
The rules live in `services/secure_work`.

## Invariants

- Every Secure Work route that names Workspace data is bound to the caller's Workspaces before its handler runs: the
  router dependency `_secure_work_scope.require_secure_work_scope` on the Secure Work routers, and
  `services/secure_work/access.work_scope_project_ids` in the Change Plan reads (`secure_work_change_plans.py`).
