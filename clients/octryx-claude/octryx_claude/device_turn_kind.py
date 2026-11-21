"""The kind of a device turn and what follows from it: a lean phase or chat turn, a whole-story session, a plain
story session; their built-in tools, system prompts, settings sources, web use and the window they compact at
(``device_sdk``)."""

from __future__ import annotations

from typing import Any

# Tools a take-over runs without asking the phone (they read; WebSearch and WebFetch read the web,
# allow by default, block as an admin option); everything else asks.
LOCAL_READ_TOOLS = frozenset({"Read", "Glob", "Grep", "LS", "NotebookRead", "TodoWrite", "TodoRead", "Task", "Agent",
                              "BashOutput", "ExitPlanMode", "EnterPlanMode", "AskUserQuestion", "ToolSearch",
                              "WebSearch", "WebFetch"})
SETTING_SOURCES = ["user", "project", "local"]
# A workflow run's own turn stays under 10k tokens: no user/project settings (their plugins,
# skills, CLAUDE.md and their listing in the prompt), Claude Code's built-in tools limited to the lean set below,
# no slash commands, and a short system prompt. The platform's hooks come from ``settings`` and still decide every
# tool call; the run contract (workflow_run_status) says what the phase is.
# Plus a task list and sub-agents for phase and chat turns alike (allow by
# default, block as an admin option).
LEAN_TOOLS = "Read,Edit,Write,Bash,Grep,Glob,TodoWrite,Agent"
WEB_TOOLS = ",WebSearch,WebFetch"
# Pre-approved in a turn with the web: Claude Code asks before every WebSearch / WebFetch even in acceptEdits, and a
# run has nobody to answer (an unanswered prompt is denied after 5 minutes). The platform's PreToolUse hook still
# decides each call.
WEB_ALLOWED = ("WebSearch", "WebFetch")
# A run turn whose phase opted in to sub-agents (``"subagents": true``, carried in the job offer) is a whole-story
# session (story-delivery): Claude Code's own system prompt and its full built-in tool set, with Agent
# (``Task`` is Claude Code's alias for it) and TodoWrite, plus the platform's run paragraph
# (``run.device.story_session_prompt``; an epic's plain story session ``run.device.plain_session_prompt``). Its
# sub-agents' tool calls go through the same PreToolUse hook and ``can_use_tool`` as the main session's.
# Thinking as ``claude -p`` asks for it: adaptive, its text omitted (``--thinking-display omitted``); an SDK session
# without ``display: omitted`` produces far more output tokens for the same story.
PLAIN_THINKING = {"type": "adaptive", "display": "omitted"}
# No ``run_in_background`` for Bash and Agent, no auto-backgrounding (a story session's turn).
DISABLE_BACKGROUND_ENV = "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"
# Claude Code tools that wait for a person at the keyboard: a run turn has none, so the story session never offers them.
INTERACTIVE_TOOLS = ["AskUserQuestion", "EnterPlanMode", "ExitPlanMode"]
# A lean turn outside a workflow run (governed models): the same lean tools, the repository's own
# project settings and CLAUDE.md, none of the user's plugins or MCP servers.
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
# Every other model's run turn compacts as if it had the 100K step too, so no run session (a coordinator's plan
# session resumed across replans, wakes and stories included) grows without bound.
RUN_TURN_TOKENS = 100_000


def run_compact_window(prepared: Any) -> int:
    """The window a turn compacts at: the device's (``context_window``), and for a workflow run's turn at most
    ``tier + TIER_COMPACT_MARGIN`` (the model's price tier, else :data:`RUN_TURN_TOKENS`: every model, coordinators
    included).

    The window is the tier plus the margin, not the tier itself: a window at the tier compacts at about two thirds
    of it and leaves little room for work between compactions, while ~92K leaves about 58K. A chat turn keeps the
    device's window: a person decides there."""
    window = prepared.extra.get("context_window")
    window = window if isinstance(window, int) and window > 0 else 0
    if prepared.extra.get("workflow_run") is not True:
        return window
    compact = prepared.extra.get("compact_window")
    if type(compact) is int and compact > 0:
        # The run class's cap: Claude Code compacts there itself instead of a fresh session.
        # It only lowers the window: the price-tier window below stays the ceiling.
        window = min(window, compact) if window else compact
    if story_session(prepared):
        # The story session works with the device's normal window (200K), like plain Claude Code: with its
        # subagents it needs the room, and a run window would compact it repeatedly; its calls above a price step
        # pay the higher rate.
        return window
    model = str(prepared.model or prepared.env.get("ANTHROPIC_MODEL") or "").lower()
    tiers = [size for name, size in PRICE_TIERS.items() if name in model]
    tier_window = min(tiers or [RUN_TURN_TOKENS]) + TIER_COMPACT_MARGIN
    return min(window, tier_window) if window else tier_window


def _run_turn(prepared: Any) -> bool:
    """A lean turn of a workflow run (the run contract decides) rather than a lean chat turn."""
    return prepared.extra.get("workflow_run") is not False


def story_session(prepared: Any) -> bool:
    """A run turn whose phase opted in to sub-agents: the whole story in one Claude Code session with its full tool set
    (the platform's ``story_prompt``), not the lean six-tool phase turn."""
    return _run_turn(prepared) and prepared.extra.get("subagents") is True


def plain_session(prepared: Any) -> bool:
    """A story session of epic-delivery: plain Claude Code with its own settings sources (user, project, local) like
    a ``claude -p`` (variant a2); the platform's hooks and deny rules still come with the session's flag settings."""
    return story_session(prepared) and prepared.extra.get("plain") is True


def _platform_text(prepared: Any, key: str) -> str:
    """The platform's prompt text the offer carried (``run.device.*``, ``workflow_runs.octryx.turn_tools``); a run
    turn without it does not start."""
    text = str(prepared.extra.get(key) or "")
    if not text:
        from .device_sdk import DriverStartError  # noqa: PLC0415

        raise DriverStartError("run_prompt_missing")
    return text


def _lean_prompt(prepared: Any) -> Any:
    """The system prompt of a lean turn: a story session keeps Claude Code's own prompt (it teaches the model its
    tools, the Agent tool included) with the platform's run paragraph appended; a phase turn gets the platform's
    short one and a chat turn the launcher's."""
    if story_session(prepared):
        append = _platform_text(prepared, "plain_prompt" if plain_session(prepared) else "story_prompt")
        return {"type": "preset", "preset": "claude_code", "append": append}
    if _run_turn(prepared):
        return _platform_text(prepared, "system_prompt")
    return LEAN_CHAT_PROMPT


def web_turn(prepared: Any) -> bool:
    """The turn may use the web: the offer's ``web`` (the platform decides it per Workspace and phase)."""
    return prepared.extra.get("web") is True


def open_network_host(prepared: Any, tool_name: str, tool_input: Any) -> bool:
    """The sandbox asks for a host outside its lists and the Workspace's ``sandbox.network`` is ``open``: allowed
    without asking, except a host the session denies (the platform's; ``launch.sandbox_settings``)."""
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
    """The built-in tools of a lean phase or chat turn (a story session passes no ``--tools`` at all: Claude Code's
    full set). A turn with the web (:func:`web_turn`) also gets Claude Code's own WebSearch and WebFetch: they leave
    from this device, so the session has web access even when the platform's web tools cannot leave the server."""
    own = [str(name) for name in prepared.extra.get("builtin_tools") or [] if _run_turn(prepared)]
    tools = ",".join(own) if own else LEAN_TOOLS  # the phase's or its size class's list (``octryx.turn_tools``)
    return tools + WEB_TOOLS if web_turn(prepared) else tools


def _lean_sources(prepared: Any) -> list[str]:
    """A run turn reads no settings at all; a lean chat turn keeps the repository's own (CLAUDE.md, project)."""
    return [] if _run_turn(prepared) else ["project"]
