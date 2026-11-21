"""Governed policy lists: code-owned seeds, admin-editable live values (W22b).

Product policy a customer may want to change is data. Its seed lives in code; the live value is
a versioned, audited ``system_config`` record an admin edits with closed validation:

- ``default_tool_set.<capability>``: the governed default tool set per capability class;
- ``weak_coding_model_families``: model families that are not coding-capable by default;
- ``model_capabilities``: the capabilities a definition may require and a runtime target carry;
- ``workflow_proposal_settings``: the proposal timeout (a settings object on the same mechanism).

Runtime code reads :func:`live.live_policy_lists`; admin code goes through :mod:`.admin`.
"""
