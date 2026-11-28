"""The coding engine the platform decided for this person in a Workspace (Claude Code or Codex)."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

import httpx

from .platform import SessionContext, call_control_plane

TIMEOUT = 5.0
PATH = "/engine"
CLAUDE_CODE = "claude_code"
CODEX = "codex"
NAMES = {CLAUDE_CODE: "Claude Code", CODEX: "Codex"}
SOURCES = {"person": "your choice", "workspace": "Workspace default", "platform": "platform default"}


@dataclass(frozen=True)
class EngineSetting:
    engine: str
    source: str
    allowed: tuple[str, ...]
    known: bool  # False: the platform could not say (unreachable or older than the engine setting)

    def allows(self, engine: str) -> bool:
        return engine in self.allowed

    def line(self) -> str:
        if not self.known:
            return "Claude Code (the platform does not report an engine setting)"
        others = ", ".join(NAMES.get(name, name) for name in self.allowed)
        return f"{NAMES.get(self.engine, self.engine)} ({SOURCES.get(self.source, self.source)}; allowed: {others})"


UNKNOWN = EngineSetting(engine=CLAUDE_CODE, source="", allowed=(CLAUDE_CODE,), known=False)


def fetch(state, context: SessionContext, *, http: httpx.Client) -> EngineSetting:
    result = call_control_plane(state, context, "GET", f"{PATH}?workspace_id={quote(context.workspace_id, safe='')}",
                                http=http, timeout=TIMEOUT)
    body = result.body if result.outcome == "ok" and isinstance(result.body, dict) else {}
    allowed = tuple(name for name in body.get("allowed") or () if name in NAMES)
    engine = str(body.get("engine") or "")
    if engine not in NAMES or not allowed:
        return UNKNOWN
    return EngineSetting(engine=engine, source=str(body.get("source") or ""), allowed=allowed, known=True)


def refusal(setting: EngineSetting, engine: str) -> str:
    if setting.allows(engine):
        return ""
    return f"denied: engine_not_allowed_in_workspace ({NAMES[engine]} is not allowed in this Workspace)"


__all__ = ["CLAUDE_CODE", "CODEX", "EngineSetting", "UNKNOWN", "fetch", "refusal"]
