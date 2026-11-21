"""Split a turn's input tokens by what filled the context: system prompt and tool definitions, the phase prompt, tool
results (per tool), conversation history, subagents; output apart. Pure, no database.

The API counts a call's input as a whole (uncached + cache read + cache write); what is in it follows from the order
of the turn:

- measured (a ``token_profile`` from the launcher): per main-thread call, the fixed start (the session's smallest
  call minus the prompt: system prompt and tool definitions), the prompt, every tool result asked for by an earlier
  call since the last compaction (its full size), and the rest as history. A result is paid again in every later call
  that carries it: 69 KB of test output read early costs its size in each following call;
- estimated (a turn without a ``token_profile``: the launcher sends none when it finds no transcript stream): one
  call per tool use plus one, the job's first context reading as the fixed start, tool results as stored (cut at
  4 KB: a lower bound), the prompt inside the history.

When the parts would exceed the measured input, tool results are scaled down first, then the fixed start: the
measured total always wins.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .catalog import tokens_of

CATEGORY_KEYS = ("system_and_tools", "prompt", "tool_results", "history", "subagents", "output")


@dataclass
class Call:
    input: int = 0
    cache_read: int = 0
    cache_write: int = 0
    output: int = 0
    subagent: bool = False

    @property
    def total_input(self) -> int:
        return self.input + self.cache_read + self.cache_write


@dataclass
class ToolResult:
    tool: str
    chars: int
    call: int
    key: str = ""
    path_key: str = ""
    label: str = ""
    clipped: bool = False
    error: bool = False

    @property
    def tokens(self) -> int:
        return tokens_of(self.chars)


@dataclass
class Turn:
    job_id: str
    turn_id: str
    node_id: str = ""
    measured: bool = False
    calls: list[Call] = field(default_factory=list)
    tools: list[ToolResult] = field(default_factory=list)
    compactions: list[int] = field(default_factory=list)
    prompt_chars: int = 0
    # Estimated turns: the turn's usage totals and the job's first context reading.
    usage: Call = field(default_factory=Call)
    first_context: int = 0

    @property
    def main_calls(self) -> list[Call]:
        return [call for call in self.calls if not call.subagent]


@dataclass
class Split:
    categories: dict[str, int] = field(default_factory=lambda: dict.fromkeys(CATEGORY_KEYS, 0))
    by_tool: dict[str, int] = field(default_factory=dict)
    carried: list[int] = field(default_factory=list)  # per tool result of the turn, the tokens it cost in all
    cache: dict[str, int] = field(default_factory=lambda: dict.fromkeys(("read", "write", "uncached", "output"), 0))
    calls: int = 0


def fixed_start(turns: list[Turn]) -> int:
    """System prompt and tool definitions of one job's session: its smallest call minus that turn's prompt."""
    sizes = [call.total_input - tokens_of(turn.prompt_chars) for turn in turns if turn.measured
             for call in turn.main_calls[:1]]
    return max(min(sizes), 0) if sizes else 0


def _fit(total: int, fixed: int, prompt: int, results: list[int]) -> tuple[int, int, list[int], int]:
    """The parts scaled into ``total``: results first, then the fixed start and prompt; the rest is history."""
    used = sum(results)
    if fixed + prompt + used > total:
        room = max(total - fixed - prompt, 0)
        results = [value * room // used for value in results] if used else results
        used = sum(results)
    if fixed + prompt > total:
        scale = total / (fixed + prompt) if fixed + prompt else 0
        fixed, prompt = int(fixed * scale), int(prompt * scale)
    return fixed, prompt, results, max(total - fixed - prompt - used, 0)


def _visible(result: ToolResult, call_index: int, compactions: list[int]) -> bool:
    since = max((index for index in compactions if index <= call_index), default=0)
    return since <= result.call < call_index


def _measured(turn: Turn, fixed: int, split: Split) -> None:
    prompt = tokens_of(turn.prompt_chars)
    split.carried = [0] * len(turn.tools)
    for index, call in enumerate(turn.main_calls):
        shown = [position for position, result in enumerate(turn.tools)
                 if _visible(result, index, turn.compactions)]
        part_fixed, part_prompt, results, history = _fit(call.total_input, fixed, prompt,
                                                         [turn.tools[position].tokens for position in shown])
        split.categories["system_and_tools"] += part_fixed
        split.categories["prompt"] += part_prompt
        split.categories["history"] += history
        for position, value in zip(shown, results, strict=True):
            split.carried[position] += value
    split.categories["subagents"] = sum(call.total_input for call in turn.calls if call.subagent)
    split.calls = len(turn.calls)


def _estimated(turn: Turn, split: Split) -> None:
    calls = len(turn.tools) + 1
    results = [result.tokens * max(calls - result.call - 1, 0) for result in turn.tools]
    part_fixed, _prompt, results, history = _fit(turn.usage.total_input, turn.first_context * calls, 0, results)
    split.categories["system_and_tools"] = part_fixed
    split.categories["history"] = history
    split.carried = results
    split.calls = calls


def split_turn(turn: Turn, fixed: int = 0) -> Split:
    split = Split()
    if turn.measured:
        _measured(turn, fixed, split)
        calls = turn.calls
    else:
        _estimated(turn, split)
        calls = [turn.usage]
    split.categories["tool_results"] = sum(split.carried)
    for result, value in zip(turn.tools, split.carried, strict=True):
        split.by_tool[result.tool] = split.by_tool.get(result.tool, 0) + value
    split.categories["output"] = sum(call.output for call in calls)
    split.cache = {"read": sum(call.cache_read for call in calls), "write": sum(call.cache_write for call in calls),
                   "uncached": sum(call.input for call in calls), "output": split.categories["output"]}
    return split


__all__ = ["CATEGORY_KEYS", "Call", "Split", "ToolResult", "Turn", "fixed_start", "split_turn"]


def hit_rate(cache: dict[str, int]) -> float | None:
    """The share of input tokens read from the prompt cache: read / (read + write + uncached); ``None`` without
    input. The order of a request decides it: what stays the same between calls belongs first, what changes last."""
    total = cache.get("read", 0) + cache.get("write", 0) + cache.get("uncached", 0)
    return round(cache.get("read", 0) / total, 4) if total else None
