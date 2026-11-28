"""The phased definitions the suite looks up by key: the shipped workflows and the unshipped base of the accepted-spec
engineering graph, the richest test-first graph the engine runs."""

from __future__ import annotations

from typing import Any


def seed_definitions() -> list[dict[str, Any]]:
    from app.services.workflow_runs.seeding import phased_seeds
    from tests.specification_engineering_graph_support import base_seed

    return [*phased_seeds(), base_seed()]


def seed_definition(key: str) -> dict[str, Any]:
    return next(item for item in seed_definitions() if item["key"] == key)
