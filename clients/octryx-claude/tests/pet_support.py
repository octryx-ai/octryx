"""Shared clock and pet state helpers for the Octryx pet tests."""

from __future__ import annotations

from datetime import datetime

from octryx_claude.pet.model import PetItem, PetState

NOON = datetime(2026, 11, 6, 12, 0)


def _pet(state: str = "needs_you", *ids: str, **extra) -> PetState:
    items = tuple(PetItem(id=item, kind="question", title=f"Title {item}", url=f"/chat?session_id={item}")
                  for item in ids)
    return PetState(state=state, items=items, count=len(items), headline=items[0].title if items else "", **extra)
