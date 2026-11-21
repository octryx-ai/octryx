"""Shared fixtures for the Agent Definition revision tests.

One builder per row the revision contract needs, used by all four test modules
(service validation, service lifecycle, API authorization, API restore) so the
aggregate under test is described in exactly one place. The defaults are the ones
the assertions rely on — ``DEFINITION_NAME`` and ``DEFINITION_GOAL`` are asserted
after a restore, and the default step tool is a real registry entry so a fixture
definition validates cleanly unless a test deliberately breaks it.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AgentDefinition,
    AgentGroup,
    AgentStep,
    ControlPlaneRuntimeTarget,
    Project,
    User,
    UserProject,
)
from app.services.auth import create_access_token, hash_password

#: Header values a restore is asserted to put back on the live row.
DEFINITION_NAME = "Revision Fixture Agent"
DEFINITION_GOAL = "Prove the revision contract"

#: A real ``TOOL_REGISTRY`` identifier, so a fixture definition is publishable.
DEFAULT_STEP_TOOL = "knowledge_search"


async def admin_user(db: AsyncSession) -> User:
    """Return the seeded global admin."""
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def make_user(db: AsyncSession, *, label: str) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=str(uuid.uuid4()),
        username=f"{label}-{suffix}",
        email=f"{label}-{suffix}@example.com",
        password_hash=hash_password("testpass123"),
        display_name=label,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def make_project(db: AsyncSession) -> Project:
    project = Project(
        id=str(uuid.uuid4()),
        name=f"agent-rev-{uuid.uuid4().hex[:8]}",
        config={},
        is_active=True,
    )
    db.add(project)
    await db.flush()
    return project


async def make_member(
    db: AsyncSession, user: User, project: Project, role: str
) -> None:
    db.add(
        UserProject(
            user_id=user.id, project_id=project.id, role=role, granted_by=user.id
        )
    )
    await db.flush()


async def first_runtime_target(db: AsyncSession) -> ControlPlaneRuntimeTarget:
    return (
        (await db.execute(select(ControlPlaneRuntimeTarget).limit(1))).scalars().one()
    )


async def make_group(
    db: AsyncSession, *, owner: User, project_id: str | None = None
) -> AgentGroup:
    group = AgentGroup(
        id=str(uuid.uuid4()),
        owner_id=owner.id,
        project_id=project_id,
        name=f"group-{uuid.uuid4().hex[:8]}",
        slug=f"group-{uuid.uuid4().hex[:8]}",
        description="Fixture group",
        category="general",
        position=100,
        is_active=True,
    )
    db.add(group)
    await db.flush()
    return group


async def make_definition(
    db: AsyncSession,
    *,
    owner: User,
    project_id: str | None = None,
    runtime_target_id: str | None = None,
    name: str = DEFINITION_NAME,
    agent_type: str = "diagnosis",
    steps: int = 2,
) -> AgentDefinition:
    """Create a live definition with *steps* contiguous steps at positions 1..n."""
    definition = AgentDefinition(
        id=str(uuid.uuid4()),
        owner_id=owner.id,
        project_id=project_id,
        runtime_target_id=runtime_target_id,
        name=name,
        description="Fixture definition",
        goal=DEFINITION_GOAL,
        agent_type=agent_type,
        thinking_level="light",
        branch_prefix="octryx",
        system_prompt="Be precise.",
        output_prompt="Report findings.",
        require_self_review=False,
        is_active=True,
    )
    definition.skill_preferences = {}
    db.add(definition)
    await db.flush()
    for position in range(1, steps + 1):
        await make_step(db, definition, position=position, name=f"Step {position}")
    return definition


async def make_step(
    db: AsyncSession,
    definition: AgentDefinition,
    *,
    position: int,
    name: str,
    allowed_tools: list[str] | None = None,
) -> AgentStep:
    step = AgentStep(
        id=str(uuid.uuid4()),
        agent_id=definition.id,
        position=position,
        name=name,
        step_type="analysis",
        instructions=f"Do {name}",
        success_criteria="Done",
        is_enabled=True,
    )
    step.allowed_tools = (
        allowed_tools if allowed_tools is not None else [DEFAULT_STEP_TOOL]
    )
    step.step_config = {}
    db.add(step)
    await db.flush()
    return step


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def auth_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def error_body(response) -> dict:
    """Error payload without the per-request correlation id.

    Comparing two of these is how the tests prove an out-of-scope id and an
    unknown id are answered identically.
    """
    return {key: value for key, value in response.json().items() if key != "request_id"}


def definition_routes(definition_id: str) -> list[tuple[str, str]]:
    return [
        ("GET", f"/api/v1/agent-definitions/{definition_id}/revisions"),
        ("POST", f"/api/v1/agent-definitions/{definition_id}/revisions"),
    ]


def revision_routes(revision_id: str) -> list[tuple[str, str]]:
    base = f"/api/v1/agent-definitions/revisions/{revision_id}"
    return [
        ("GET", base),
        ("POST", f"{base}/validate"),
        ("POST", f"{base}/publish"),
        ("POST", f"{base}/restore"),
    ]


async def call(client: AsyncClient, method: str, url: str, **kwargs):
    return await client.request(method, url, **kwargs)
