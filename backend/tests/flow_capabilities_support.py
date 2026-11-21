"""Shared helpers for the test_flow_capabilities_* modules."""

from sqlalchemy import select

from app.models import FlowDefinition, FlowDefinitionVersion, User
from app.tools.context import ToolContext


def _make_draft_flow(
    db,
    *,
    created_by: str,
    flow_id: str = "flow-cap",
    version_id: str = "version-cap",
    project_id: str | None = None,
):
    flow = FlowDefinition(
        id=flow_id,
        key="person-research",
        name="Person Research",
        description="Research a person from governed sources.",
        status="draft",
        is_active=True,
        project_id=project_id,
        created_by=created_by,
    )
    version = FlowDefinitionVersion(
        id=version_id,
        flow_id=flow.id,
        version=1,
        status="draft",
        definition_json={
            "schema_version": "2.0",
            "nodes": [
                {
                    "id": "input",
                    "type": "trigger",
                    "config": {
                        "schema": {
                            "type": "object",
                            "properties": {"request": {"type": "object"}},
                            "required": ["request"],
                        }
                    },
                },
                {"id": "out", "type": "output"},
            ],
            "edges": [
                {
                    "source_node_id": "input",
                    "target_node_id": "out",
                    "source_field": "request",
                    "target_field": "result",
                }
            ],
            "evidence_contract": {"required": ["source_references"]},
        },
        created_by=created_by,
    )
    db.add(flow)
    db.add(version)
    return flow, version


async def _admin_user(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


def _tool_context(db, *, project_id: str | None = None, user_id: str = "admin") -> ToolContext:
    return ToolContext(
        user_id=user_id,
        project_ids=[project_id] if project_id else [],
        roles=[],
        session_id="session-capability",
        project_config={},
        db=db,
        capability_type="change",
    )
