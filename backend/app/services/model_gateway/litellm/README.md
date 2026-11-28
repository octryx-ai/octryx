# LiteLLM gateway client

The governed client of the cluster LiteLLM data plane.

## Invariants

- A project is granted an alias only through its `model_policy`; `denied_aliases` wins, and without a grant the alias
  is denied (`policy.model_alias_access_decision`).
- The unverified project admission denies every alias (`project_admission.py`).
- `entry_admission.admitted_alias_entry` returns an alias entry only after the project grant, the alias catalog and the
  data policy all admit it.
- The client runs with `trust_env=False` and without redirects (`client.py`).
- The content-logging posture is admitted only with prompt, response and header retention `disabled`
  (`content_logging.py`).
