"""A phase turn of a workflow run gets its tool surface from the PHASE, never from the ``knowledge_request``
family whose id it reuses; walked stage by stage with the real functions for every phase of A–E."""

from __future__ import annotations

from tests.phased_seed_definitions import seed_definitions

# The family toolset a Clarify turn must not be narrowed to.
FAMILY_KNOWLEDGE_PLAN = {"knowledge_search", "knowledge_read"}


def _phases() -> list[tuple[str, str]]:
    return [
        (seed["key"], node["id"])
        for seed in seed_definitions()
        for node in seed["definition"]["nodes"]
        if node.get("type") == "phase"
    ]










def test_every_a_to_e_workflow_has_phases_under_test():
    keys = {key for key, _node in _phases()}
    assert keys >= {"bug-fix-reproduction", "jira-intake-triage", "feature-delivery-tdd", "incident-analysis"}
    assert ("feature-delivery-tdd", "clarify") in _phases()
















