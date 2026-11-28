"""Guard: every node-id-valued config key the workflow runtime reads is in ``fragments.node_refs``."""

from __future__ import annotations

import re
from pathlib import Path

from app.services.workflow_runs.fragments.node_refs import DEFINITION_NODE_REF_KEYS, NODE_REF_KEYS

ROOT = Path(__file__).resolve().parents[1] / "app" / "services" / "workflow_runs"
READ = re.compile(r"""config(?:\.get\(|\[)\s*["']([A-Za-z_][A-Za-z0-9_]*)["']""")
DEFINITION_READ = re.compile(r"""definition(?:\.get\(|\[)\s*["']([A-Za-z_][A-Za-z0-9_]*)["']""")
NOT_NODE_REFS = frozenset({
    "action", "advance", "agent", "arguments", "bitbucket_url", "bitbucket_username", "capability_class", "checks", "child_checksum", "child_version_id",
    "conditions", "confluence_url", "decider", "deputy", "documentation_contract", "documentation_status", "handoff",
    "handoff_inputs", "inputs", "iterations", "jenkins_token", "jenkins_url", "jenkins_username", "jira_project_key",
    "kind", "max_parallel", "mode", "options", "outcome", "params", "question", "repository", "rubric_version",
    "runtime_target", "safety_constraints", "shows", "sub_agents", "subject", "title", "tool", "tool_policy",
    "unlocks", "work_state", "workflow_class", "workflow_contract", "workflow_id", "workflow_key",
    "check", "field", "operator", "value",
    "tasks", "brief", "always_deny_patterns", "checklist", "assumptions", "suggestions", "walkthrough", "model", "screens",
    "output", "roles", "parallel", "result_values", "revise_on", "triage_routing",
    "reviewer", "route",
    "enabled", "confirm", "root_cause",
    "acceptance",
    "generic_actions",
    "refusals",
})
NOT_DEFINITION_NODE_REFS = frozenset({"budget", "edges", "execution_kind", "failure_policy", "nodes"})


def _reads(pattern: re.Pattern[str]) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in sorted(ROOT.rglob("*.py")):
        if "fragments" in path.relative_to(ROOT).parts:
            continue
        for key in pattern.findall(path.read_text(encoding="utf-8")):
            found.setdefault(key, set()).add(str(path.relative_to(ROOT)))
    return found


def test_every_node_config_key_read_is_classified():
    node_refs = {key for _kind, key in NODE_REF_KEYS}
    found = _reads(READ)
    unknown = {key: sorted(paths) for key, paths in found.items() if key not in node_refs | NOT_NODE_REFS}
    assert not unknown, (f"New node config keys {unknown}: add a node-id-valued one to fragments.node_refs."
                         "NODE_REF_KEYS (the compiler renames it), any other to NOT_NODE_REFS.")
    assert node_refs <= set(found), "a NODE_REF_KEYS key is no longer read: keep the table closed and current"


def test_every_definition_level_key_read_is_classified():
    found = _reads(DEFINITION_READ)
    keys = {key for key in found if key in DEFINITION_NODE_REF_KEYS | NOT_DEFINITION_NODE_REFS}
    assert DEFINITION_NODE_REF_KEYS <= keys
    node_valued = {key for key in found if key.endswith("_node") or key.endswith("_node_id")}
    assert node_valued <= DEFINITION_NODE_REF_KEYS, f"new definition-level node keys: {sorted(node_valued)}"


def test_the_table_is_the_contracts_closed_set():
    assert NODE_REF_KEYS == {("gate", "phase"), ("decision", "source"), ("review", "producer"), ("review", "phase"),
                             ("review", "screens_node"), ("user_confirmation", "payload_from")}
    assert DEFINITION_NODE_REF_KEYS == {"plan_node"}


def test_a_review_in_a_fragment_keeps_pointing_at_its_own_nodes():
    from app.services.workflow_runs.fragments.node_refs import external_refs, rewrite_node_refs

    review = {"id": "review", "type": "review", "config": {"phase": "implement", "screens_node": "pipeline"}}
    renamed = rewrite_node_refs(review, lambda node_id: f"frag.{node_id}")
    assert renamed["config"] == {"phase": "frag.implement", "screens_node": "frag.pipeline"}
    assert external_refs(review, {"implement"}) == ["pipeline"]
