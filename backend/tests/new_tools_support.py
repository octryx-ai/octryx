"""Tests for code intelligence tools, snapshot service, PTY service, and tool improvements.

Each test is self-contained – it uses tmp_path for file I/O and a minimal
ToolContext so no real database is required.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── Minimal ToolContext stub ──────────────────────────────────────────────────


@dataclass
class _Ctx:
    workspace_root: str | None = None
    session_id: str | None = None
    db: Any = None
    project_config: dict = field(default_factory=dict)
    user_id: str | None = None
    project_ids: list = field(default_factory=list)
    roles: list = field(default_factory=list)
    system_context: str | None = None
    parent_session_id: str | None = None
    sub_agent_depth: int = 0
    agent_definition: Any = None
