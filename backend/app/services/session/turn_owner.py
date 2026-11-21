"""Record which platform process owns a session's running turn.

A chat turn runs as an in-process task, so its owner is the process that started it.
Starting a turn stamps ``sessions.turn_owner_process_id`` with this process's boot id;
the stamp is a column, not session metadata, so no caller that rewrites the metadata
dict can drop it. The stamp is never cleared: it always names the last process that
started a turn here, and only matters while the session is ``running``.
"""

from __future__ import annotations

from typing import Any

from ..runtime_ownership.process_identity import current_process_id


def claim_turn_ownership(session: Any) -> None:
    """Mark this process as the owner of the turn starting on ``session``."""
    session.turn_owner_process_id = current_process_id()


__all__ = ["claim_turn_ownership"]
