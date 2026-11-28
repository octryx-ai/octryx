# Platform routes

Platform operations: Operations › Live and the emergency stop, problems, data transfer and the prompt catalog. The
rules live in `services/operations`, `services/problems` and `services/prompt_catalog`.

## Invariants

- An emergency stop that names a Workspace the caller cannot see answers 404 `project_not_found` before anything
  else, for every caller (`operations_live._stop_scope`, `services/access_control.require_visible_workspace`).
