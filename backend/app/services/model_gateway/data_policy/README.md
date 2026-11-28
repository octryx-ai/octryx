# Data policy

A Workspace's data classification, compared with a model alias' `data_policy_class`.

## Invariants

- The effective classification is the project row's `config["data_policy"]["classification"]`, raised only by a more
  sensitive session value. A missing project value or an unknown value denies; no default replaces it
  (`classification.resolve_data_classification`).
- `source.py` reads the project row itself; the session value comes from the `session_metadata` its caller passes.
- A dispatch is permitted only when the effective classification ranks at or below the alias' `data_policy_class`
  (`gate.py`).
