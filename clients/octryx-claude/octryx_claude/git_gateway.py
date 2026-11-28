"""The run's branch through the platform for a launcher without git credentials (a server runner). The run-bound
token goes to git only via ``GIT_CONFIG_*`` of the launcher's own call, never argv, a URL or ``.git/config``."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from .platform import SessionContext, call_control_plane
from .state import LocalState

TOKEN_TIMEOUT = 30

#: The run's git URL on the platform and the environment that authenticates a fetch from it, or ``None``.
GatewaySource = Callable[[], "tuple[str, dict[str, str]] | None"]


def fetch_env(url: str, token: str, base: dict[str, str] | None = None) -> dict[str, str]:
    source = os.environ if base is None else base
    raw = str(source.get("GIT_CONFIG_COUNT") or "").strip()
    index = int(raw) if raw.isdigit() else 0
    return {"GIT_CONFIG_COUNT": str(index + 1), f"GIT_CONFIG_KEY_{index}": f"http.{url}.extraHeader",
            f"GIT_CONFIG_VALUE_{index}": f"Authorization: Bearer {token}"}


def source_for(state: LocalState, context: SessionContext, path: str, *, http: Any) -> GatewaySource:
    def source() -> tuple[str, dict[str, str]] | None:
        answer = call_control_plane(state, context, "POST", "/sessions/git-token", http=http, timeout=TOKEN_TIMEOUT)
        token = str(answer.body.get("token") or "") if answer.outcome == "ok" else ""
        if not token or answer.body.get("path") != path:
            return None
        url = f"{context.base_url}{path}"
        return url, fetch_env(url, token)

    return source


__all__ = ["GatewaySource", "fetch_env", "source_for"]
