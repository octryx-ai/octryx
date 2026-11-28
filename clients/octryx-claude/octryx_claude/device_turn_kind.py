"""The kind of a device turn (lean phase or chat turn, whole-story or plain story session) and its built-in tools,
system prompt, settings sources, web use and compact window."""

from __future__ import annotations

from typing import Any

# Tools a take-over runs without asking the phone; everything else asks.
LOCAL_READ_TOOLS = frozenset({"Read", "Glob", "Grep", "LS", "NotebookRead", "TodoWrite", "TodoRead", "Task", "Agent",
                              "BashOutput", "ExitPlanMode", "EnterPlanMode", "AskUserQuestion", "ToolSearch",
                              "WebSearch", "WebFetch"})
SETTING_SOURCES = ["user", "project", "local"]
# A run turn stays under 10k tokens: no user/project settings, the lean built-in tools, no slash commands and a
# short system prompt; the platform's hooks still decide every tool call.
LEAN_TOOLS = "Read,Edit,Write,Bash,Grep,Glob,TodoWrite,Agent"
WEB_TOOLS = ",WebSearch,WebFetch"
# Claude Code asks before every WebSearch / WebFetch even in acceptEdits, and a run has nobody to answer.
WEB_ALLOWED = ("WebSearch", "WebFetch")
# Without ``display: omitted`` an SDK session produces far more output tokens for the same story.
PLAIN_THINKING = {"type": "adaptive", "display": "omitted"}
DISABLE_BACKGROUND_ENV = "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"
# Claude Code tools that wait for a person at the keyboard: a run turn has none, so the story session never offers them.
INTERACTIVE_TOOLS = ["AskUserQuestion", "EnterPlanMode", "ExitPlanMode"]
LEAN_CHAT_PROMPT = (
    "You are a software engineer working in this repository. Follow the repository's CLAUDE.md and the user's "
    "request. Work like an experienced developer: look at what exists before you write; for work with several "
    "steps keep a task list (TodoWrite); when something is unclear, ask instead of guessing. Use Read, Grep and Glob "
    "to look, Edit and Write to change files, Bash to run tests and commands. Keep answers short."
)


# Models whose input price steps up above a prompt size (list price: Haiku 5.5 is 0.10 $/M up to 100K tokens, 0.50 $
# beyond, output likewise ×5): a run turn kept below the step pays the lower rate.
PRICE_TIERS = {"haiku-5-5": 100_000}
# Claude Code compacts about 33K below its window (20K kept for the summary, 13K margin). A window 25K above the
# tier compacts at ~92K, so the calls stay below the tier and the compaction call itself mostly too.
TIER_COMPACT_MARGIN = 25_000
# Other models' run turns compact at the same step, so no run session grows without bound.
RUN_TURN_TOKENS = 100_000


def run_compact_window(prepared: Any) -> int:
    window = prepared.extra.get("context_window")
    window = window if isinstance(window, int) and window > 0 else 0
    if prepared.extra.get("workflow_run") is not True:
        return window
    compact = prepared.extra.get("compact_window")
    if type(compact) is int and compact > 0:
        # The run class's cap only lowers the window; the price-tier window stays the ceiling.
        window = min(window, compact) if window else compact
    if story_session(prepared):
        # Like plain Claude Code, the story session keeps the device's window: its subagents need the room.
        return window
    model = str(prepared.model or prepared.env.get("ANTHROPIC_MODEL") or "").lower()
    tiers = [size for name, size in PRICE_TIERS.items() if name in model]
    tier_window = min(tiers or [RUN_TURN_TOKENS]) + TIER_COMPACT_MARGIN
    return min(window, tier_window) if window else tier_window


def _run_turn(prepared: Any) -> bool:
    return prepared.extra.get("workflow_run") is not False


def story_session(prepared: Any) -> bool:
    return _run_turn(prepared) and prepared.extra.get("subagents") is True


def plain_session(prepared: Any) -> bool:
    return story_session(prepared) and prepared.extra.get("plain") is True


def _platform_text(prepared: Any, key: str) -> str:
    text = str(prepared.extra.get(key) or "")
    if not text:
        from .device_sdk import DriverStartError  # noqa: PLC0415

        raise DriverStartError("run_prompt_missing")
    return text


def _lean_prompt(prepared: Any) -> Any:
    if story_session(prepared):
        append = _platform_text(prepared, "plain_prompt" if plain_session(prepared) else "story_prompt")
        return {"type": "preset", "preset": "claude_code", "append": append}
    if _run_turn(prepared):
        return _platform_text(prepared, "system_prompt")
    return LEAN_CHAT_PROMPT


def web_turn(prepared: Any) -> bool:
    return prepared.extra.get("web") is True


def open_network_host(prepared: Any, tool_name: str, tool_input: Any) -> bool:
    from .launch_sandbox import (
        SANDBOX_NETWORK_ASK_TOOL,
        SANDBOX_NETWORK_OPEN,  # noqa: PLC0415
    )

    if tool_name != SANDBOX_NETWORK_ASK_TOOL or prepared.extra.get("sandbox_network") != SANDBOX_NETWORK_OPEN:
        return False
    host = str((tool_input or {}).get("host") or "").strip().lower().strip("[]") if isinstance(tool_input, dict) else ""
    denied = {str(name).lower() for name in prepared.extra.get("denied_hosts") or []}
    return bool(host) and host not in denied


def _lean_tools(prepared: Any) -> str:
    own = [str(name) for name in prepared.extra.get("builtin_tools") or [] if _run_turn(prepared)]
    tools = ",".join(own) if own else LEAN_TOOLS
    return tools + WEB_TOOLS if web_turn(prepared) else tools


def _lean_sources(prepared: Any) -> list[str]:
    return [] if _run_turn(prepared) else ["project"]
