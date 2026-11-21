"""Wired LSP client: real process spawning, binary resolution, and logging."""

from __future__ import annotations

import logging
import shutil
from typing import Any

from ..execution_runtime import ExecutionRuntimeUnavailableError
from ..persistent_process_runtime import spawn_persistent_stdio_process
from .protocol import _LSP_SERVERS
from .service import LspClient as _LspClientImpl
from .service import LspClientManager as _LspClientManagerImpl

log = logging.getLogger(__name__)
root_log = logging.getLogger()


def _log_warning(message: str, *args: object) -> None:
    log.warning(message, *args)
    if log.disabled or not log.propagate:
        root_log.warning(message, *args)


class LspClient(_LspClientImpl):
    def __init__(
        self,
        language: str,
        workspace_root: str,
        *,
        db: Any | None = None,
        project_config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            language,
            workspace_root,
            db=db,
            project_config=project_config,
            which_resolver=shutil.which,
            process_spawner=spawn_persistent_stdio_process,
        )

    async def start(self) -> bool:
        try:
            return await super().start()
        except (ExecutionRuntimeUnavailableError, OSError, ValueError) as exc:
            command = _LSP_SERVERS.get(self.language) or [self.language]
            _log_warning("Failed to start LSP server %s: %s", command, exc)
            return False


class LspClientManager(_LspClientManagerImpl):
    def __init__(self) -> None:
        super().__init__(client_factory=LspClient)


lsp_manager = LspClientManager()


__all__ = [
    "LspClient",
    "LspClientManager",
    "lsp_manager",
]
