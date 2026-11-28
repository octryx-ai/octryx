"""The generated baseline decides exactly like the legacy decision at every enforcement point: over a wide
input grid plus a seeded command fuzz, every shadow outcome is ``match``."""

from __future__ import annotations

import itertools
import random

import pytest

from app.services.agent_gateway.policy import build_policy
from app.services.agent_gateway.policy_keys import BASELINE_POLICY
from app.services.agent_gateway.policy_normalize import normalize_agent_gateway_policy
from app.services.agent_gateway.seat_policy import seat_decision_for
from app.services.agent_gateway.tool_check import DECISION_DENY, evaluate_tool_check
from app.services.classification_tool_policy import CLASSIFICATION_TOOL_POLICY_KEY, classification_tool_decision
from app.services.data_classification.policy_rules import CONNECTOR_FAMILIES, LevelRules
from app.services.model_gateway.data_policy.classification import (
    CLASSIFICATION_SOURCE_PROJECT_CONFIG,
    CLASSIFICATION_SOURCE_UNRESOLVED,
    DATA_CLASSIFICATION_ORDER,
    WorkspaceDataClassification,
)
from app.services.model_gateway.data_policy.gate import data_policy_decision
from app.services.model_gateway.litellm.project_admission import build_project_model_admission
from app.services.policy_engine.entities import principal_entities
from app.services.policy_engine.gateway_point import gateway_query
from app.services.policy_engine.points import (
    POINT_GATEWAY_TOOL_CHECK,
    POINT_REMOTE_MODEL,
    model_query,
    remote_query,
)
from app.services.policy_engine.shadow import OUTCOME_MATCH, LegacyDecision, decision_counters, shadow_decision
from app.tools.definitions import get_all_definitions

UNRESOLVED = WorkspaceDataClassification("", CLASSIFICATION_SOURCE_UNRESOLVED, "workspace_data_classification_missing")


def _classified(level: str) -> WorkspaceDataClassification:
    return WorkspaceDataClassification(level, CLASSIFICATION_SOURCE_PROJECT_CONFIG, "")


def _only_matches(point: str, minimum: int) -> None:
    counters = decision_counters().get(point, {})
    assert {outcome: count for outcome, count in counters.items() if count and outcome != OUTCOME_MATCH} == {}
    assert counters.get(OUTCOME_MATCH, 0) >= minimum


def _gateway(extra: dict | None = None):
    return build_policy(normalize_agent_gateway_policy({**BASELINE_POLICY, **(extra or {})}), source="workspace")


def test_seat_decisions_match_for_every_level_rule_and_switch():
    switches = [{}, {"seat_mode": "allowed"}, {"seat_mode": "forbidden"},
                {"seat_mode": "allowed", "requires_governed_routing": True},
                {"seat_mode": "allowed", "requires_governed_routing": False}]
    count = 0
    for raw, level, seat_allowed, governed in itertools.product(
        switches, DATA_CLASSIFICATION_ORDER, (True, False), (True, False)
    ):
        policy = _gateway(raw)
        rules = LevelRules(seat_allowed=seat_allowed, requires_governed_routing=governed)
        seat_decision_for(policy, rules, workspace_id="ws", level=level)
        seat_decision_for(policy, None, workspace_id="ws")
        seat_decision_for(policy, None, workspace_id="ws", level=level)  # a level without rules stays unresolved
        count += 3
    _only_matches("seat", count)


ALIASES = ["octryx-a", "octryx-b", "octryx-x", "", "  octryx-a  ", None]
MODEL_POLICIES = [
    {}, {"allowed_aliases": ["octryx-a"]}, {"allowed_aliases": ["octryx-a", "octryx-b"], "denied_aliases": ["octryx-b"]},
    {"allow_all_admitted_aliases": True}, {"allow_all_admitted_aliases": True, "denied_aliases": ["octryx-x"]},
    {"allow_all_admitted_aliases": "true"}, {"allowed_aliases": "octryx-a"},
]
LEVEL_LISTS = [None, {}, {"internal": frozenset({"octryx-a"})}, {"internal": frozenset()},
               {"confidential": frozenset({"octryx-b"})}]


def test_model_admission_matches_for_grants_denials_levels_and_unverified_context():
    count = 0
    for model_policy, lists, classification in itertools.product(
        MODEL_POLICIES, LEVEL_LISTS, [UNRESOLVED, _classified("internal"), _classified("confidential")]
    ):
        admission = build_project_model_admission(
            project_id="ws", project_config={"model_policy": model_policy}, source="test",
            data_classification=classification, level_model_aliases=lists,
        )
        unverified = build_project_model_admission(project_id="", project_config={}, source="",
                                                   data_classification=classification)
        for alias in ALIASES:
            admission.decide(alias)
            unverified.decide(alias)
            count += 2
    _only_matches("model_admission", count)


def test_an_unverified_admission_is_denied_by_its_named_platform_policy():
    unverified = build_project_model_admission(project_id="", project_config={}, source="",
                                               data_classification=_classified("internal"))
    comparison = shadow_decision(
        "model_admission", LegacyDecision(False, "project_policy_context_unverifiable"),
        lambda: model_query(unverified, "octryx-a"),
    )
    assert comparison.determining == ("platform:model-admission-unverified",)


def test_remote_model_admission_matches_the_data_policy_gate_and_the_level_rule():
    count = 0
    classes = [None, "", "public", "internal", "confidential", "restricted", "secret", "bogus"]
    for classification, alias_class, kind, allowed in itertools.product(
        [UNRESOLVED, *(_classified(level) for level in DATA_CLASSIFICATION_ORDER)], classes,
        ("reranker", "embeddings"), (True, False),
    ):
        rules = LevelRules(seat_allowed=True, reranker_allowed=allowed, remote_embeddings_allowed=allowed)
        gate = data_policy_decision(classification, alias_class)
        legacy = gate.allowed and allowed
        reason = gate.reason if not gate.allowed else ("" if allowed else "forbidden")
        shadow_decision(
            POINT_REMOTE_MODEL, LegacyDecision(legacy, reason),
            lambda c=classification, a=alias_class, k=kind, r=rules, g=gate: remote_query(
                project_id="ws", classification=c, data_policy_class=a, model_kind=k, rules=r if g.allowed else None
            ),
        )
        count += 1
    _only_matches(POINT_REMOTE_MODEL, count)


def _section(level: str | None, access: str, log_masking: bool) -> dict:
    if level is None:
        return {CLASSIFICATION_TOOL_POLICY_KEY: {"level": None}}
    return {CLASSIFICATION_TOOL_POLICY_KEY: {
        "level": level, "workspace_id": "ws", "connectors": dict.fromkeys(CONNECTOR_FAMILIES, access),
        "log_masking_required": log_masking,
    }}


CALLS = [
    ("run_kubectl", {"args": "apply -f x.yaml"}), ("run_kubectl", {"args": ["logs", "pod"]}),
    ("run_kubectl", {"args": "get pods"}), ("run_kubectl", {"args": "label 'unbalanced"}),
    ("run_kubectl", {"args": "edit deploy/x"}), ("run_kubectl", {}),
    ("aws_read_operation", {"service": "logs"}), ("aws_read_operation", {"service": " LOGS "}),
    ("aws_read_operation", {"service": "ec2"}), ("get_pod_logs", {"pod": "x"}),
]


def test_tool_admission_matches_for_every_tool_level_access_and_log_masking_rule():
    names = sorted(get_all_definitions())
    sections = [_section(None, "read_write", False)] + [
        _section(level, access, log_masking)
        for level, access, log_masking in itertools.product(("internal", "secret"), ("none", "read", "read_write"),
                                                    (True, False))
    ]
    count = 0
    for config in sections:
        for name in names:
            classification_tool_decision(name, config)
            count += 1
        for name, params in CALLS:
            classification_tool_decision(name, config, params)
            count += 1
        classification_tool_decision("unknown_tool_xyz", config, {})
        count += 1
    assert len(names) > 50
    _only_matches("tool_admission", count)


COMMANDS = [
    "kubectl get pods", "kubectl --context risk get pods", "kubectl get pods --context=risk",
    "/usr/local/bin/kubectl get pods", "sudo kubectl get pods", "env A=1 kubectl get ns --context x",
    "FOO=bar kubectl get ns", "echo hi | kubectl apply -f -", "kubectl get pods; kubectl --context x get ns",
    "bash -c 'kubectl get pods'", "echo $(kubectl get pods)", "echo `git push origin main`",
    "git push origin main", "git push origin main --dry-run", "git push origin master", "git push origin feature",
    "git push --force origin feature", "git push -f", "git push --force-with-lease", "git push origin main:main",
    "git  push   origin main", "'git push' origin main", "git 'push origin' main", "git push 'origin main'",
    "cat <<EOF\ngit push origin main\nEOF", "echo \"unterminated", "", "   ", "ls -la && pwd",
    "kubectl", "kubectl --context", "kubectl --context= get", "git push origin main 2>&1 | tee log",
    "eval git push origin main", "nohup git push -f &", "time kubectl get pods",
]
PATHS = [
    ("Read", {"file_path": ".env"}), ("Read", {"file_path": "/repo/sub/.env"}), ("Read", {"file_path": "../.env"}),
    ("Read", {"file_path": ".env.local"}), ("Edit", {"file_path": "/home/u/.aws/credentials"}),
    ("Write", {"file_path": "~/.aws/config"}), ("MultiEdit", {"file_path": "repo/.aws/x"}),
    ("NotebookEdit", {"notebook_path": ".env"}), ("Grep", {"path": ".env"}), ("Read", {"path": "/x/.aws/y"}),
    ("Read", {"file_path": 7}), ("Glob", {}), ("Bash", {"command": "cat .env", "file_path": ".env"}),
]
EXTRA_RULES = {"tool_rules": [*BASELINE_POLICY["tool_rules"],
                              {"id": "no-rollout", "kind": "command_argument_denied", "command": ["kubectl", "rollout"],
                               "argument": "restart"},
                              {"id": "no-helm", "kind": "command_prefix_denied", "prefix": ["helm"]},
                              {"id": "grep-env", "kind": "path_denied", "tools": ["Grep", "Bash"],
                               "glob": "*.env"}]}


def _fuzz_commands(count: int) -> list[str]:
    words = ["kubectl", "git", "push", "origin", "main", "master", "--context", "--context=x", "-f", "--force",
             "get", "pods", "rollout", "restart", "helm", "sudo", "env", "A=1", "&&", "|", ";", "'quoted arg'",
             "$(git push origin main)", "/bin/kubectl", "x=y=z", "--", "-"]
    generator = random.Random(1204)
    return [" ".join(generator.choice(words) for _ in range(generator.randint(1, 8))) for _ in range(count)]


@pytest.mark.parametrize("extra", [None, EXTRA_RULES], ids=["baseline", "extra-rules"])
def test_gateway_tool_rules_match_for_commands_paths_and_fuzz(extra):
    gateway = _gateway(extra)
    principal, records = principal_entities("u1", roles=["member"], session_id="s1", profile="governed",
                                            client="octryx-claude")
    inputs = [{"tool_name": "Bash", "tool_input": {"command": command}, "cwd": "/repo"}
              for command in [*COMMANDS, *_fuzz_commands(400)]]
    inputs += [{"tool_name": tool, "tool_input": tool_input, "cwd": "/repo"} for tool, tool_input in PATHS]
    inputs.append({"tool_name": "Bash", "tool_input": "not-a-dict"})
    for hook_input in inputs:
        legacy = evaluate_tool_check(gateway, hook_input)
        shadow_decision(
            POINT_GATEWAY_TOOL_CHECK, LegacyDecision(legacy.decision != DECISION_DENY, legacy.rule_id or legacy.reason),
            lambda h=hook_input: gateway_query(workspace_id="ws", gateway=gateway, hook_input=h, principal=principal,
                                               principal_records=records),
        )
    _only_matches(POINT_GATEWAY_TOOL_CHECK, len(inputs))
