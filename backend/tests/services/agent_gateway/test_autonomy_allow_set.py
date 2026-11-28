"""The agent's autonomy set comes from the platform, not from a file, so commands like `python -c` and
`git commit` do not wait minutes for a phone approval each."""

from __future__ import annotations

from app.services.agent_gateway.policy import build_policy
from app.services.agent_gateway.policy_keys import AUTONOMY_ALLOW, BASELINE_POLICY
from app.services.agent_gateway.policy_normalize import normalize_agent_gateway_policy as normalize_policy


def test_the_baseline_lets_the_agent_test_read_and_commit_but_never_push():
    policy = build_policy(normalize_policy(BASELINE_POLICY), source="baseline")
    allowed = set(policy.allow_permissions)
    assert {"Bash(git commit:*)", "Bash(.venv/bin/python:*)", "Bash(pytest:*)", "TodoWrite"} <= allowed
    assert not any("push" in rule or rule.startswith("Bash(rm") or "curl" in rule for rule in allowed)


def test_a_workspace_list_replaces_the_set_and_a_policy_without_one_keeps_it():
    own = build_policy(normalize_policy({"client_permissions": {"deny": [], "ask": [], "allow": ["Bash(make:*)"]}}),
                       source="workspace")
    assert own.allow_permissions == ("Bash(make:*)",)
    none = build_policy(normalize_policy({"client_permissions": {"deny": [], "ask": [], "allow": []}}),
                        source="workspace")
    assert none.allow_permissions == ()
    older = build_policy(normalize_policy({"client_permissions": {"deny": [], "ask": []}}), source="workspace")
    assert older.allow_permissions == AUTONOMY_ALLOW
