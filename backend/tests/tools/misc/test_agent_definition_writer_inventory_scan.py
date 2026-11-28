"""The writer scan fails every known escape pattern of an aggregate write and does not flag modules that only read the aggregate."""

from __future__ import annotations

import pytest

from tests.support.agent_definition_writer_scan_support import (
    REASON_BULK_WRITE,
    REASON_CONSTRUCTS,
    REASON_MUTATES,
    REASON_RELATIONSHIP_WRITE,
    REASON_SESSION_DELETE,
    REASON_SETATTR,
    scan_source,
)

ESCAPE_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (
        "direct_constructor",
        REASON_CONSTRUCTS,
        """
from app.models import AgentDefinition

async def rogue(db):
    db.add(AgentDefinition(id="x", owner_id="u", name="n"))
""",
    ),
    (
        "in_place_mutation",
        REASON_MUTATES,
        """
from sqlalchemy import select
from app.models import AgentDefinition

async def rogue(db):
    row = (await db.execute(select(AgentDefinition))).scalars().first()
    row.system_prompt = "rewritten"
""",
    ),
    (
        "mutation_through_a_subscript",
        REASON_MUTATES,
        """
from sqlalchemy import select
from app.models import AgentStep

async def rogue(db):
    loaded = (await db.execute(select(AgentStep))).scalars().all()
    loaded[0].instructions = "rewritten"
""",
    ),
    (
        "mutation_through_a_loop_variable",
        REASON_MUTATES,
        """
from sqlalchemy import select
from app.models import AgentStep

async def rogue(db):
    loaded = (await db.execute(select(AgentStep))).scalars().all()
    for index, item in enumerate(loaded, start=1):
        item.position = index
""",
    ),
    (
        "mutation_of_an_annotated_parameter",
        REASON_MUTATES,
        """
from app.models import AgentDefinition

def rogue(candidate: AgentDefinition) -> None:
    candidate.goal = "rewritten"
""",
    ),
    (
        "reflective_setattr_on_a_loaded_row",
        REASON_SETATTR,
        """
from app.models import AgentDefinition

async def rogue(db):
    row = await db.get(AgentDefinition, "x")
    setattr(row, "name", "rewritten")
""",
    ),
    (
        "reflective_setattr_on_a_row_from_an_opaque_helper",
        REASON_SETATTR,
        """
from app.models import AgentDefinition  # noqa: F401
from app.tools.admin_impl._admin_common import _resolve_agent_definition

async def rogue(context, params):
    row, _error = await _resolve_agent_definition(context, params["agent_id"])
    for field in ("name", "goal", "system_prompt"):
        setattr(row, field, params[field])
""",
    ),
    (
        # The real shape of the closure blocker: no aggregate class is named anywhere.
        "mutation_through_a_relationship_traversal",
        REASON_RELATIONSHIP_WRITE,
        """
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import AgentGroup


async def rogue(db, group_id):
    group = (
        await db.execute(
            select(AgentGroup)
            .options(selectinload(AgentGroup.agents))
            .where(AgentGroup.id == group_id)
        )
    ).scalar_one_or_none()
    for agent in group.agents or []:
        agent.group_id = None
    await db.delete(group)
""",
    ),
    (
        "core_bulk_update",
        REASON_BULK_WRITE,
        """
from sqlalchemy import update
from app.models import AgentDefinition

async def rogue(db):
    await db.execute(update(AgentDefinition).values(system_prompt="rewritten"))
""",
    ),
    (
        "orm_delete",
        REASON_SESSION_DELETE,
        """
from app.models import AgentDefinition

async def rogue(db):
    row = await db.get(AgentDefinition, "x")
    await db.delete(row)
""",
    ),
)


NON_WRITER_SOURCES: tuple[tuple[str, str], ...] = (
    (
        "reading_the_aggregate",
        """
from sqlalchemy import select
from app.models import AgentDefinition

async def read(db):
    rows = (await db.execute(select(AgentDefinition))).scalars().all()
    return [row.name for row in rows]
""",
    ),
    (
        "serializing_the_aggregate",
        """
from app.models import AgentDefinition

def serialize(agent: AgentDefinition) -> dict:
    payload = {"id": agent.id, "name": agent.name}
    payload["steps"] = [step.name for step in agent.steps]
    return payload
""",
    ),
    (
        # Counting the members of a group is the same traversal, without a write.
        "reading_through_a_relationship",
        """
from app.models import AgentGroup  # noqa: F401


def serialize(group):
    return {"id": group.id, "agentCount": len(group.agents or [])}
""",
    ),
    (
        "setattr_of_a_field_that_is_not_an_aggregate_column",
        """
from app.models import AgentDefinition  # noqa: F401

def annotate(provider, counts):
    setattr(provider, "model_count", counts.get(provider.id, 0))
""",
    ),
)


@pytest.mark.parametrize(
    ("label", "reason", "source"), ESCAPE_PATTERNS, ids=[p[0] for p in ESCAPE_PATTERNS]
)
def test_the_scan_fails_every_escape_pattern(label: str, reason: str, source: str):
    reasons = scan_source(source, filename=f"<{label}>")
    assert reason in reasons, f"{label} escaped the writer scan (found {sorted(reasons)})"


@pytest.mark.parametrize(
    ("label", "source"), NON_WRITER_SOURCES, ids=[p[0] for p in NON_WRITER_SOURCES]
)
def test_the_scan_does_not_flag_readers(label: str, source: str):
    assert not scan_source(source, filename=f"<{label}>"), label
