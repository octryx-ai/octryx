"""One turn put together from its job events (pure): the launcher's ``token_profile`` parts (measured), else the
stored tool uses and results (estimated). Shared by the Tokens view (``turns``) and the counters (``metrics``)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .split import Call, ToolResult, Turn

PROFILE_KIND = "token_profile"  # octryx-claude token_profile.KIND
SUBAGENT_LABEL = "in a subagent"
CLIPPED_CHARS = 4_000  # devices.jobs.MAX_TOOL_RESULT_CHARS: a stored result this long was cut
KINDS = ("tool_use", "tool_result", "context", "compaction", PROFILE_KIND)


def positive(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def usage_call(usage: Any) -> Call:
    usage = usage if isinstance(usage, dict) else {}
    return Call(positive(usage.get("input_tokens")), positive(usage.get("cache_read_input_tokens")),
                positive(usage.get("cache_creation_input_tokens")), positive(usage.get("output_tokens")))


class TurnFacts:
    def __init__(self, job_id: str, turn_id: str, started: datetime | None = None) -> None:
        self.turn = Turn(job_id=job_id, turn_id=turn_id)
        self.started = started
        self.finished = False
        self.asked: dict[str, tuple[str, str, int]] = {}
        self.stored: list[ToolResult] = []
        self.parts: dict[int, dict[str, Any]] = {}

    def add(self, body: dict[str, Any]) -> None:
        kind = body.get("kind")
        if kind == "tool_use":
            tool_use_id = str(body.get("tool_use_id") or "")
            self.asked[tool_use_id] = (str(body.get("tool") or ""), str(body.get("input_preview") or ""),
                                       len(self.asked))
        elif kind == "tool_result":
            tool, preview, call = self.asked.get(str(body.get("tool_use_id") or ""), ("", "", len(self.asked)))
            output = body.get("output") if isinstance(body.get("output"), str) else ""
            key = f"{tool}\n{preview}"
            self.stored.append(ToolResult(tool=tool, chars=len(output), call=call, key=key,
                                          path_key=key if tool == "Read" else "", label=preview,
                                          clipped=len(output) >= CLIPPED_CHARS, error=body.get("is_error") is True))
        elif kind == "compaction":
            self.turn.compactions.append(len(self.asked))
        elif kind == PROFILE_KIND:
            self.parts[positive(body.get("part"))] = body

    def build(self) -> Turn:
        turn = self.turn
        if self.parts:
            labels = {tool_use_id: preview for tool_use_id, (_tool, preview, _call) in self.asked.items()}
            turn.measured = True
            first = self.parts.get(0, {})
            turn.prompt_chars = positive(first.get("prompt_chars"))
            turn.compactions = [positive(index) for index in first.get("compactions") or []]
            parts = [part for _index, part in sorted(self.parts.items())]
            for part in parts:
                turn.calls += [Call(*(positive(value) for value in row[:4]), subagent=bool(row[4]))
                               for row in part.get("calls") or [] if isinstance(row, list) and len(row) >= 5]
            for part in parts:
                for row in part.get("tools") or []:
                    if not isinstance(row, list) or len(row) < 7:
                        continue
                    tool_use_id, tool, chars, digest, path_digest, call, error = row[:7]
                    call = positive(call)
                    # A subagent's tool uses never reach the platform as events, so there is no preview to show.
                    nested = call < len(turn.calls) and turn.calls[call].subagent
                    label = labels.get(str(tool_use_id), "") or (SUBAGENT_LABEL if nested else "")
                    turn.tools.append(ToolResult(tool=str(tool), chars=positive(chars), call=call,
                                                 key=f"{tool}\n{digest}", path_key=str(path_digest or ""),
                                                 label=label, error=bool(error)))
        else:
            turn.tools = self.stored
        return turn


__all__ = ["CLIPPED_CHARS", "KINDS", "PROFILE_KIND", "TurnFacts", "positive", "usage_call"]
