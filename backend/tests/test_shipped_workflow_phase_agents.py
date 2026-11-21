"""Every phase of the shipped workflows names a platform agent."""

from __future__ import annotations

from app.services.workflow_runs.seeding import phased_seeds


def test_every_phase_of_the_shipped_workflows_names_a_platform_agent():
    for seed in phased_seeds():
        for node in seed["definition"]["nodes"]:
            if node["type"] == "phase":
                assert node["config"].get("agent") in {"assistant", "engineer"}, (seed["key"], node["id"])
