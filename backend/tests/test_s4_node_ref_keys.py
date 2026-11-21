"""Guard: every node-id-valued config key the workflow runtime reads is in ``fragments.node_refs``.

The compiler renames only the keys of :data:`NODE_REF_KEYS` when it namespaces a fragment. A new runtime read of a
node config key that names another node would silently point a namespaced fragment at a missing (or a wrong) node.
So every ``config.get("<key>")`` / ``config["<key>"]`` read under ``app/services/workflow_runs`` is classified here:
either a node ref (in the table) or declared as a value that never names a node. A new key fails until it is
classified.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.services.workflow_runs.fragments.node_refs import DEFINITION_NODE_REF_KEYS, NODE_REF_KEYS

ROOT = Path(__file__).resolve().parents[1] / "app" / "services" / "workflow_runs"
READ = re.compile(r"""config(?:\.get\(|\[)\s*["']([A-Za-z_][A-Za-z0-9_]*)["']""")
DEFINITION_READ = re.compile(r"""definition(?:\.get\(|\[)\s*["']([A-Za-z_][A-Za-z0-9_]*)["']""")
# Config keys whose values never name a node of the graph (closed; review a new entry before adding it).
NOT_NODE_REFS = frozenset({
    "action", "advance", "agent", "arguments", "bitbucket_url", "bitbucket_username", "capability_class", "checks", "child_checksum", "child_version_id",
    "conditions", "confluence_url", "decider", "deputy", "documentation_contract", "documentation_status", "handoff",
    "handoff_inputs", "inputs", "iterations", "jenkins_token", "jenkins_url", "jenkins_username", "jira_project_key",
    "kind", "max_parallel", "mode", "options", "outcome", "params", "question", "repository", "rubric_version",
    "runtime_target", "safety_constraints", "shows", "sub_agents", "subject", "title", "tool", "tool_policy",
    "unlocks", "work_state", "workflow_class", "workflow_contract", "workflow_id", "workflow_key",
    # review.source is "local_output" | "accepted_handoff"; decision.source is a node ref (same key, other kind).
    # D2b2 field condition (decision ``check: "field"``): a check kind, a work item field, an operator, a value.
    "check", "field", "operator", "value",
    # Story auto-accept (``tasks``: false = no task proofs needed), the plain Claude Code brief marker, the device's
    # exec deny patterns, and the review's spec checklist, assumptions flag, the PR review bot's suggestions and
    # walkthrough flags, reviewer model and screens flag.
    "tasks", "brief", "always_deny_patterns", "checklist", "assumptions", "suggestions", "walkthrough", "model", "screens",
    # Teamwork: the plan's output kind, the roles map, the parallel flag, the item's result values, the severity
    # that triggers a revision; ``triage_routing`` is the Workspace setting (``Project.config``), not a node key.
    "output", "roles", "parallel", "result_values", "revise_on", "triage_routing",
    # The review node's reviewer per engine ({engine: {model, route}}) and its flat route ("seat" | "company")
    # (``review/choice.py``): model and route values, never a node.
    "reviewer", "route",
    # The hands-on test: switched off per node (``enabled``), the bug flow's reproduce check asking a
    # person (``confirm``), and the bug review's root-cause rule (``root_cause``): flags, never a node.
    "enabled", "confirm", "root_cause",
    # The PR review bot's acceptance table flag (stage E1, ``review/runner.py``): a flag, never a node.
    "acceptance",
    # The hands-on node's generic form buttons a feature scenario may click only where a changed screen shows them
    # (``hands_on/generate.py``; workflow data): texts, never a node.
    "generic_actions",
    # A phase's reactions to repeated refusals (``refusals``, top-10 #5): rules whose change_plan names a node of the
    # same workflow; a fragment does not namespace it (no seeded fragment carries refusals).
    "refusals",
})
NOT_DEFINITION_NODE_REFS = frozenset({"budget", "edges", "execution_kind", "failure_policy", "nodes"})


def _reads(pattern: re.Pattern[str]) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in sorted(ROOT.rglob("*.py")):
        if "fragments" in path.relative_to(ROOT).parts:
            continue  # the compiler reads the reference node's own config (fragment_key, ports, namespace)
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
    # A review names the phase it checks and, optionally, the node whose screenshots it shows (review/screens.py).
    assert NODE_REF_KEYS == {("gate", "phase"), ("decision", "source"), ("review", "producer"), ("review", "phase"),
                             ("review", "screens_node"), ("user_confirmation", "payload_from")}
    assert DEFINITION_NODE_REF_KEYS == {"plan_node"}


def test_a_review_in_a_fragment_keeps_pointing_at_its_own_nodes():
    """Namespacing a fragment renames the phase a review checks and the node whose screenshots it shows; a review
    that names a node outside the fragment is reported, like any other node reference."""
    from app.services.workflow_runs.fragments.node_refs import external_refs, rewrite_node_refs

    review = {"id": "review", "type": "review", "config": {"phase": "implement", "screens_node": "pipeline"}}
    renamed = rewrite_node_refs(review, lambda node_id: f"frag.{node_id}")
    assert renamed["config"] == {"phase": "frag.implement", "screens_node": "frag.pipeline"}
    assert external_refs(review, {"implement"}) == ["pipeline"]
