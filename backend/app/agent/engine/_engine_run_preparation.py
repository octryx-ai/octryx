"""Run-preparation wiring for the engine: repository bootstrap on session start."""

from __future__ import annotations

import logging
from typing import Any

from ...services.repository_bootstrap import (
    ensure_workspace_repository,
    get_repository_bootstrap_config,
    has_explicit_repository_bootstrap_config,
)

logger = logging.getLogger(__name__)


async def bootstrap_workspace_repository_if_configured(
    *,
    workspace_root: Any,
    project_config: dict | None,
    session_id: str,
) -> None:
    """Bootstrap the workspace repository when the project explicitly opts in."""
    bootstrap_config = get_repository_bootstrap_config(project_config)
    if has_explicit_repository_bootstrap_config(project_config) and bootstrap_config.get(
        "auto_bootstrap_on_session_start"
    ):
        try:
            bootstrap_result = await ensure_workspace_repository(
                workspace_root=workspace_root,
                project_config=project_config,
                session_id=session_id,
                reason="session_start",
            )
        except Exception as exc:
            bootstrap_result = {"status": "error", "error": str(exc)}
        logger.info(
            "agent.run.repository_bootstrap",
            extra={
                "session_id": session_id,
                "status": bootstrap_result.get("status"),
                "provider": bootstrap_result.get("provider"),
                "repo_path": bootstrap_result.get("repo_path"),
            },
        )
