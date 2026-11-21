"""The team block of an item contract: who works on the story next to the item, and how they talk (design section 5).

An item agent sees ``{coordinator, story, items: [{id, role, status, paths, agent_hash}], rules}``. It is rebuilt at
every hook from ``context.work``, so an item that started after this one shows its agent hash as soon as its session
bound (the device executor records it on the item). The rules are the ones the board needs to replace waiting:

- post with ``work_item_id`` = the story, so the whole conversation is one thread the coordinator reads at replan;
- ask the owner of a path (its agent hash), never edit a path another item owns;
- never wait for an answer: when blocked, post a ``question`` to the coordinator and finish with
  ``submit_phase_result("blocked")``; the coordinator answers and reopens the item.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from . import work_of
from .coordinator import coordinator_hash

RULES = (
    "Post on the board with work_item_id = the story ({story}) so the team's conversation stays one thread.",
    "Never edit a path another item owns: ask its owner (to_agent_hash) or the coordinator instead.",
    "Never wait for an answer. When you are blocked, board_post a question to the coordinator "
    "(to_agent_hash = {coordinator}) and finish with submit_phase_result value 'blocked'; the coordinator answers "
    "and reopens your item.",
)
NO_COORDINATOR = "the coordinator (no board address: say what blocks you in your blocked result)"


async def team_block(db: AsyncSession, run: WorkflowRun, *, item_key: str | None = None) -> dict[str, Any]:
    """The team as the item ``item_key`` sees it (``{}`` before a split exists)."""
    work = work_of(run)
    if not work.get("items"):
        return {}
    coordinator = await coordinator_hash(db, run)
    items = [{"id": str(key), "role": item.get("role"), "status": item.get("status"),
              "paths": list(item.get("paths") or []), "agent_hash": item.get("agent_hash"),
              **({"you": True} if str(key) == item_key else {})}
             for key, item in dict(work["items"]).items() if isinstance(item, dict)]
    story = run.work_item_id or ""
    return {"coordinator": coordinator, "story": story, "items": items,
            "rules": [rule.format(story=story or "the run's Work item", coordinator=coordinator or NO_COORDINATOR)
                      for rule in RULES]}


__all__ = ["RULES", "team_block"]
