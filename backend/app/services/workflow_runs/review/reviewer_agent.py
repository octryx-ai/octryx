"""The ``review`` node runs as the platform Reviewer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import UsageEvent, WorkflowRun
from ...platform_agents.catalog import REVIEWER
from ..phase_agents import agent_refusal, platform_agent
from .model import DISPATCH_OWNER


@dataclass(frozen=True, slots=True)
class ReviewerSetup:
    definition_id: str
    instructions: str
    runtime_preference: str
    author_model: str
    revision_id: str | None = None
    revision_number: int | None = None
    checksum: str | None = None


async def _author_model(db: AsyncSession, run: WorkflowRun) -> str:
    from ..records import main_session_id

    session_id = await main_session_id(db, run)
    if not session_id:
        return ""
    model = (await db.execute(
        select(UsageEvent.model).where(UsageEvent.session_id == session_id,
                                       UsageEvent.dispatch_owner.is_distinct_from(DISPATCH_OWNER))
        .order_by(UsageEvent.created_at.desc()).limit(1))).scalar_one_or_none()
    return str(model or "")


async def reviewer_setup(db: AsyncSession, run: WorkflowRun) -> ReviewerSetup | str:
    row = await platform_agent(db, REVIEWER)
    reason = agent_refusal(row)
    if reason:
        return f"reviewer_{reason}"
    # The published revision's instructions and runtime preference, never the live row's draft.
    return ReviewerSetup(definition_id=row.definition_id, instructions=row.instructions,
                         runtime_preference=row.runtime_preference,
                         author_model=await _author_model(db, run), revision_id=row.revision_id,
                         revision_number=row.revision_number, checksum=row.checksum)


def order_review_runtimes(admitted: list[dict[str, Any]], setup: ReviewerSetup | None, *, model: str = ""
                          ) -> tuple[list[dict[str, Any]], bool]:
    if model:
        chosen = [runtime for runtime in admitted if str(runtime.get("model") or "") == model]
        if chosen:
            rest, _ = order_review_runtimes([r for r in admitted if r not in chosen], setup)
            shared = bool(setup is not None and setup.author_model == model)
            return chosen + rest, shared
    tagged = [runtime for runtime in admitted
              if "coding" in {str(tag).lower() for tag in runtime.get("use_case_tags") or ()}]
    if setup is None:
        return tagged or admitted, False
    ordered = (tagged + [r for r in admitted if r not in tagged]) if setup.runtime_preference == "coding" else admitted
    if not setup.author_model:
        return ordered, False
    others = [runtime for runtime in ordered if str(runtime.get("model") or "") != setup.author_model]
    if not others:
        return ordered, True
    # Another model first; the author's own model last instead of no review at all.
    return others + [runtime for runtime in ordered if runtime not in others], False
