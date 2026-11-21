"""Seed the three platform agents once from code.

- A missing agent is created global and published (bootstrap writer: revision 1 is published).
- A changed seed updates the row only while it is still an earlier shipped seed (``SHIPPED_SEED_CHECKSUMS``);
  a row an admin edited keeps its content and gets the new seed as a draft revision for review.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_definition_revision_store import insert_revision, load_definition_steps

from ...models import AgentDefinition, AgentDefinitionRevision, User
from ...models.agent.agent_definition_revision import REVISION_STATUS_DRAFT
from ...time_utils import utc_now
from ..agent_definition_authoring import governs_agent_definition_write
from ..agent_definition_revisions import next_revision_number
from ..agent_definition_snapshot import build_definition_snapshot, compute_snapshot_checksum
from ..agent_definition_writers import AgentDefinitionWriter
from .seeds import PLATFORM_AGENT_SEEDS, SHIPPED_SEED_CHECKSUMS, PlatformAgentSeed

logger = logging.getLogger(__name__)

SEED_FIELDS = ("name", "description", "goal", "agent_type", "tool_surface", "capability_ceiling",
               "runtime_preference", "chat_selectable")


def _apply(row: AgentDefinition, seed: PlatformAgentSeed) -> None:
    for field in SEED_FIELDS:
        setattr(row, field, getattr(seed, field))
    row.system_prompt = seed.instructions
    row.output_prompt = ""
    row.thinking_level = "light"
    row.branch_prefix = "octryx"
    row.require_self_review = False
    row.project_id = None
    row.group_id = None
    row.default_workflow_key = None
    row.execution_mode = None
    row.skill_preferences = {}
    row.is_active = True


def seed_checksum(seed: PlatformAgentSeed) -> str:
    """The snapshot checksum the seed produces on a fresh row (no steps)."""
    row = AgentDefinition(builtin_key=seed.key)
    _apply(row, seed)
    return compute_snapshot_checksum(build_definition_snapshot(row, []))


async def _draft_for_review(db: AsyncSession, row: AgentDefinition, seed: PlatformAgentSeed, actor_id: str) -> str:
    """``draft`` when the seed content is new to this agent's history, else ``admin_owned`` (already offered)."""
    draft = AgentDefinition(builtin_key=seed.key)
    _apply(draft, seed)
    snapshot = build_definition_snapshot(draft, [])
    checksum = compute_snapshot_checksum(snapshot)
    pending = (await db.execute(select(AgentDefinitionRevision.id).where(
        AgentDefinitionRevision.definition_id == row.id, AgentDefinitionRevision.checksum == checksum))).first()
    if pending is not None:
        return "admin_owned"
    revision = AgentDefinitionRevision(
        id=str(uuid.uuid4()), definition_id=row.id, revision_number=await next_revision_number(db, row.id),
        status=REVISION_STATUS_DRAFT, checksum=checksum, created_by=actor_id, created_at=utc_now())
    revision.snapshot = snapshot
    await insert_revision(db, revision)
    logger.info("Platform agent %s is admin-owned; the changed seed waits as a draft revision", seed.key)
    return "draft"


@governs_agent_definition_write(AgentDefinitionWriter.BOOTSTRAP_PLATFORM_AGENTS, actor_param="admin_user")
async def seed_platform_agents(db: AsyncSession, *, admin_user: User) -> dict[str, str]:
    """Create or upgrade the Assistant, Engineer and Reviewer; returns ``{key: outcome}``."""
    outcomes: dict[str, str] = {}
    for seed in PLATFORM_AGENT_SEEDS:
        row = (await db.execute(
            select(AgentDefinition).where(AgentDefinition.builtin_key == seed.key))).scalar_one_or_none()
        if row is None:
            row = AgentDefinition(id=str(uuid.uuid4()), owner_id=admin_user.id, builtin_key=seed.key)
            _apply(row, seed)
            db.add(row)
            await db.flush()
            outcomes[seed.key] = "created"
            continue
        current = compute_snapshot_checksum(build_definition_snapshot(row, await load_definition_steps(db, row.id)))
        if current == seed_checksum(seed):
            outcomes[seed.key] = "unchanged"
        elif current in SHIPPED_SEED_CHECKSUMS.get(seed.key, frozenset()):
            _apply(row, seed)
            await db.flush()
            outcomes[seed.key] = "upgraded"
        else:
            outcomes[seed.key] = await _draft_for_review(db, row, seed, admin_user.id)
    return outcomes
