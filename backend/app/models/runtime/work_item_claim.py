"""Work-item claims with leases and fencing epochs (agent coordination board).

A claim says "this agent identity works on this Work Item until ``lease_until``". At most one claim per Work
Item is active (``released_at IS NULL``): a partial unique index enforces it on PostgreSQL and SQLite alike,
so two agents racing for an item have exactly one winner. ``epoch`` grows by one per item with every new
claim; an agent write carrying a stale epoch is fenced (``claim_lost``). The holder is an agent identity:
a gateway session (``gateway_session``) or an MCP grant (``mcp_session``), stored only as a hash.
"""

from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String, text

from ...db import Base
from ...time_utils import utc_now


class WorkItemClaim(Base):
    __tablename__ = "work_item_claim"
    __table_args__ = (
        Index(
            "uq_work_item_claim_active",
            "work_item_id",
            unique=True,
            postgresql_where=text("released_at IS NULL"),
            sqlite_where=text("released_at IS NULL"),
        ),
        Index("ix_work_item_claim_project_active", "project_id", "released_at"),
        Index("ix_work_item_claim_holder", "holder_kind", "holder_ref_hash"),
    )

    id = Column(String(36), primary_key=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    work_item_id = Column(String(36), ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False)
    holder_kind = Column(String(20), nullable=False)
    holder_ref_hash = Column(String(24), nullable=False)
    holder_user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    epoch = Column(Integer, nullable=False)
    lease_seconds = Column(Integer, nullable=False)
    lease_until = Column(DateTime, nullable=False)
    paths = Column(JSON, nullable=False, default=list)
    claimed_at = Column(DateTime, nullable=False, default=utc_now)
    released_at = Column(DateTime, nullable=True)
    release_reason = Column(String(20), nullable=True)
    # The last fenced agent write on the item under this claim (handoff nudge).
    last_write_at = Column(DateTime, nullable=True)
    # "Offer, never assign": the agent the item is offered to, since when, and who was offered before;
    # ``handed_off_at``: the holder itself handed the item over (``/handoff``, the trigger).
    offer_agent_hash = Column(String(24), nullable=True)
    offer_at = Column(DateTime, nullable=True)
    offer_history = Column(JSON, nullable=True)
    handed_off_at = Column(DateTime, nullable=True)


__all__ = ["WorkItemClaim"]
