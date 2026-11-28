"""Record which platform process owns a session's running turn."""

from __future__ import annotations

from typing import Any

from ..runtime_ownership.process_identity import current_process_id


def claim_turn_ownership(session: Any) -> None:
    session.turn_owner_process_id = current_process_id()


__all__ = ["claim_turn_ownership"]
