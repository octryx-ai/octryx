"""The baseline translator — goldens, determinism, schema validity, escaping and approximations.

Goldens live in ``tests/fixtures/policy_engine``; ``UPDATE_POLICY_GOLDENS=1`` rewrites them (review the diff).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.services.agent_gateway.policy import build_policy
from app.services.agent_gateway.policy_keys import BASELINE_POLICY
from app.services.agent_gateway.policy_normalize import normalize_agent_gateway_policy
from app.services.data_classification.policy_rules import ClassificationPolicy
from app.services.data_classification.policy_validation import normalize_policy_levels
from app.services.policy_engine.cedar_text import glob_to_like, literal
from app.services.policy_engine.engine import compile_policy_set, validate_policy_text
from app.services.policy_engine.translator import (
    WorkspaceSources,
    instance_baseline,
    workspace_gateway_policies,
    workspace_model_policies,
)

GOLDENS = Path(__file__).parent / "fixtures" / "policy_engine"
WORKSPACE = "11111111-2222-3333-4444-555555555555"
MODEL_POLICY = {"allowed_aliases": ["octryx-sonnet", " octryx-opus ", ""], "denied_aliases": ["octryx-legacy"]}


def _gateway(extra: dict | None = None):
    return build_policy(normalize_agent_gateway_policy({**BASELINE_POLICY, **(extra or {})}), source="workspace")


def _configured_matrix() -> ClassificationPolicy:
    overrides = normalize_policy_levels([
        {"level": "internal", "rules": {"connectors": {"kubernetes": "none", "jira": "read"}}},
        {"level": "confidential", "rules": {"reranker_allowed": False, "log_masking_required": True}},
        {"level": "public", "rules": {"requires_governed_routing": True, "remote_embeddings_allowed": False}},
    ])
    # The per-level model lists are derived from the Model catalog clearance, never stored.
    derived = {"internal": ("octryx-sonnet",), "confidential": ()}
    return ClassificationPolicy(state="configured", overrides=overrides, derived_model_aliases=derived)


def _golden(name: str, text: str) -> None:
    path = GOLDENS / name
    if os.environ.get("UPDATE_POLICY_GOLDENS") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert path.read_text(encoding="utf-8") == text, f"golden {name} differs (UPDATE_POLICY_GOLDENS=1 to review)"


CASES = {
    "default_matrix_baseline_workspace.cedar": lambda: instance_baseline(
        ClassificationPolicy(state="default"), [WorkspaceSources(WORKSPACE, _gateway(), MODEL_POLICY)]
    ),
    "configured_matrix_two_workspaces.cedar": lambda: instance_baseline(
        _configured_matrix(),
        [
            WorkspaceSources("ws-b", None, {"allow_all_admitted_aliases": True}),
            WorkspaceSources("ws-a", _gateway({"client_permissions": {
                "deny": ["Bash(kubectl delete:*)", "Read(./secrets/**)", "WebFetch(domain:example.com)"],
                "ask": ["Bash(git push:*)"],
            }}), {}),
        ],
    ),
    "invalid_matrix.cedar": lambda: instance_baseline(ClassificationPolicy(state="invalid"), []),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_baseline_matches_its_golden_and_validates_against_the_schema(name):
    text = CASES[name]()
    _golden(name, text)
    assert validate_policy_text(text) == []
    assert len(compile_policy_set(text).handle) > 0


@pytest.mark.parametrize("name", sorted(CASES))
def test_baseline_is_deterministic(name):
    assert CASES[name]() == CASES[name]()


def test_workspace_order_does_not_change_the_text():
    first = WorkspaceSources("ws-a", _gateway(), {})
    second = WorkspaceSources("ws-b", None, MODEL_POLICY)
    matrix = ClassificationPolicy(state="default")
    assert instance_baseline(matrix, [first, second]) == instance_baseline(matrix, [second, first])


def test_model_policy_is_normalized_like_the_legacy_decision():
    text = "\n".join(item.text for item in workspace_model_policies("ws", MODEL_POLICY))
    assert '["octryx-opus", "octryx-sonnet"]' in text and '["octryx-legacy"]' in text
    assert workspace_model_policies("ws", {"allow_all_admitted_aliases": "yes"}) == []  # only ``is True`` grants


def test_ids_and_values_cannot_break_out_of_their_strings():
    hostile = 'x" };\npermit (principal, action, resource);//'
    translation = workspace_gateway_policies(hostile, _gateway({"tool_rules": [
        {"id": "r1", "kind": "command_prefix_denied", "prefix": ['a"b', "c\\d"]},
    ]}))
    text = "\n".join(item.text for item in translation.policies)
    compiled = compile_policy_set(text)
    assert len(compiled.handle) == len(translation.policies)  # nothing injected
    assert literal('a"b\n') == '"a\\"b\\n"'


@pytest.mark.parametrize(("glob", "pattern", "approximate"), [
    ("**/.env", '"**/.env"', False),
    ("~/.aws/**", '"~/.aws/**"', False),
    ("*.pe?", '"*.pe*"', True),
    ("[!a]*.key", '"**.key"', True),
    ("unclosed[", '"unclosed["', False),
])
def test_globs_become_like_patterns_and_flag_approximations(glob, pattern, approximate):
    result = glob_to_like(glob)
    assert (result.text, result.approximate) == (pattern, approximate)


def test_an_approximate_glob_is_annotated_and_noted():
    translation = workspace_gateway_policies("ws", _gateway({"tool_rules": [
        {"id": "keys", "kind": "path_denied", "tools": ["Read"], "glob": "*.pe?"},
    ]}))
    assert '@translation("approximate")' in translation.policies[0].text
    assert translation.notes == ["tool rule keys: glob widened to a Cedar like pattern"]


def test_command_unparseable_rule_only_with_command_rules():
    with_rules = workspace_gateway_policies("ws", _gateway())
    path_only = workspace_gateway_policies("ws", _gateway({"tool_rules": [
        {"id": "env", "kind": "path_denied", "tools": ["Read"], "glob": "**/.env"},
    ]}))
    assert any(item.policy_id == "workspace:ws:command-unparseable" for item in with_rules.policies)
    assert not any(item.policy_id.endswith("command-unparseable") for item in path_only.policies)
