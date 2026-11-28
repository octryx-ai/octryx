"""The workflow catalog: exactly the published phased workflows."""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import FlowDefinition, FlowDefinitionVersion, Project
from ..platform_agents.catalog import CLASS_ORDER, class_rank

WORKFLOW_RUN_REQUIRED = "workflow_run_required"
EXECUTION_KIND_PHASED = "phased"
RUN_REQUIRED_MESSAGE = ("'{key}' runs as a workflow run for a Work item, not inside a chat turn: start it from the "
                        "Work item (Start a workflow run) or confirm the proposal with a Work item.")


def _phases(definition: dict[str, Any]) -> list[dict[str, Any]]:
    return [node for node in definition.get("nodes") or [] if isinstance(node, dict) and node.get("type") == "phase"]


def highest_class(definition: dict[str, Any]) -> str:
    classes = [str(dict(dict(node.get("config") or {}).get("workflow_contract") or {}).get("capability_class")
                   or "read_only") for node in _phases(definition)]
    return CLASS_ORDER[max((class_rank(item) for item in classes), default=0)]


# ``publish_metadata`` flag of a workflow the platform publishes for its own tests (``attention.fixtures``): never
# offered to people: the composer would otherwise list them next to the real workflows.
TEST_FIXTURE_FLAG = "test_fixture"


def hidden_from_people(flow: FlowDefinition, version: FlowDefinitionVersion) -> bool:
    from ..workflow_runs.start_trigger import STARTED_BY_PULL_REQUEST, started_by

    if dict(version.publish_metadata or {}).get(TEST_FIXTURE_FLAG):
        return True
    return started_by(dict(version.definition_json or {})) == STARTED_BY_PULL_REQUEST


async def published_phased_workflows(db: AsyncSession, *, project_id: str | None,
                                     include_hidden: bool = False) -> list[dict[str, Any]]:
    scope = or_(FlowDefinition.project_id.is_(None), FlowDefinition.project_id == project_id) if project_id else (
        FlowDefinition.project_id.is_(None))
    rows = (await db.execute(
        select(FlowDefinition, FlowDefinitionVersion)
        .join(FlowDefinitionVersion, FlowDefinitionVersion.id == FlowDefinition.current_version_id)
        # A workflow of an archived Workspace stays published but is offered to nobody.
        .outerjoin(Project, Project.id == FlowDefinition.project_id)
        .where(FlowDefinition.status == "published", FlowDefinition.is_active.is_(True),
               FlowDefinitionVersion.status == "published", scope,
               or_(FlowDefinition.project_id.is_(None), Project.is_active.is_not(False))))).all()
    entries: dict[str, dict[str, Any]] = {}
    for flow, version in sorted(rows, key=lambda row: (0 if row[0].project_id else 1, row[0].key)):
        definition = dict(version.definition_json or {})
        if definition.get("execution_kind") != EXECUTION_KIND_PHASED or flow.key in entries:
            continue
        if not include_hidden and hidden_from_people(flow, version):
            continue
        capability_class = highest_class(definition)
        entries[flow.key] = {
            "key": flow.key,
            "title": flow.name,
            "description": flow.description or "",
            # The definition's own short routing text (seeded, versioned with the definition) wins: the flow's
            # description is written once at creation and cut to 240 characters in the proposal catalog, which
            # can route "idea -> spec -> 2 stories -> implement" to the wrong workflow.
            "when_to_use": str(definition.get("when_to_use") or "").strip() or flow.description or "",
            "capability": "diagnosis" if capability_class == "read_only" else "change",
            "capability_class": capability_class,
            "steps": [{"title": str(node.get("label") or node.get("id") or "")} for node in _phases(definition)],
            "workflow_id": None,
            "workflow_class": EXECUTION_KIND_PHASED,
            "project_id": flow.project_id,
            "source": EXECUTION_KIND_PHASED,
            "execution_kind": EXECUTION_KIND_PHASED,
            "requires_work_item": True,
            "version": version.version,
        }
    return sorted(entries.values(), key=lambda item: str(item["key"]))


async def phased_key(db: AsyncSession, key: str, *, project_id: str | None) -> bool:
    from ..workflow_runs.engine import published_phased_flow

    return bool(key) and await published_phased_flow(db, key, project_id) is not None


def workflow_run_required_resolution(base: dict[str, Any], key: str) -> dict[str, Any]:
    return {**base, "status": WORKFLOW_RUN_REQUIRED, "workflow_key": key, "execution_kind": EXECUTION_KIND_PHASED,
            "unmatched_reason": RUN_REQUIRED_MESSAGE.format(key=key)}
