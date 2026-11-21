"""Shared helpers for the test_research_phases_* modules."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from tests.phased_workflow_fixtures import PHASE

SEEDS = Path(__file__).resolve().parents[1] / "app/services/workflow_runs/seeds/phased_workflows.json"


SOURCES = ["https://www.coffee.example/research/protocols", "https://wiki.example.org/wiki/Coffee_roasting",
           "https://www.coffee-prices.example.org/prices/po-production.pdf"]


def _seed(key: str) -> dict:
    return next(item for item in json.loads(SEEDS.read_text(encoding="utf-8")) if item["key"] == key)["definition"]


def _draft_definition() -> dict:
    draft = copy.deepcopy(PHASE)
    draft["workflow_contract"].update(capability_class="change", when_to_use="Write SPEC.md.", checks=[
        {"type": "tool_called", "params": {"tools": ["edit_workspace_file"]}, "blocking": True,
         "description": "The specification file was written"}])
    draft["tool_policy"] = {"allowlist": ["read_workspace_file", "edit_workspace_file"], "denylist": ["web_fetch"]}
    return {"execution_kind": "phased",
            "nodes": [{"id": "start", "type": "start"},
                      {"id": "draft", "type": "phase", "label": "Write the specification", "config": draft},
                      {"id": "done", "type": "outcome", "config": {"outcome": "done"}}],
            "edges": [{"id": "1", "source_node_id": "start", "target_node_id": "draft"},
                      {"id": "2", "source_node_id": "draft", "target_node_id": "done"}]}


async def _list(db, workspace_id: str, phases: list[str], **extra) -> None:
    from app.models import Project

    project = await db.get(Project, workspace_id)
    config = dict(project.config or {})
    policy = dict(config.get("agent_gateway_policy") or {})
    policy["device_runs"] = {"enabled": True, "research_phases": phases, **extra}
    config["agent_gateway_policy"] = policy
    project.config = config
    await db.flush()


def _patch(path: str, lines: list[str]) -> str:
    body = "\n".join(f"+{line}" for line in lines)
    return (f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n+++ b/{path}\n"
            f"@@ -0,0 +1,{len(lines)} @@\n{body}\n")
