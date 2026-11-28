"""The plain ``claude -p`` turn of a device job: its command line, environment and mapped stream-json events."""

from __future__ import annotations

import contextlib
import json
from typing import Any

from .device_sdk_events import _clip, change_diff, input_preview

# A few lines, like a2's prompt; the story itself, the test commands and the brief are the user prompt.
PLAIN_NOTE = (
    "You build a story of an Octryx epic in this repository; the story is in the user's message. "
    "Start your own subagents (Agent tool) for the story's independent parts, for example backend, frontend and "
    "system tests where the story has them, in one message so they run in parallel, without a model parameter (they "
    "run on this session's model); you integrate and verify. "
    "The frontend subagent owns the look at the screens: it takes and reads the screenshots, fixes what is wrong and "
    "reports back in a few lines (screens checked, findings, what it fixed); you do not read screenshots yourself. "
    "Run the declared test commands once at the end, and again only after a change. "
    "Before you end your turn, wait until your background agents and commands have finished. "
    "Wait for your background agents via their completion notices; never schedule long wakeups. "
    "The platform then runs the declared tests and an independent review and sends anything red back to this session. "
    "To look at a screen of the app you started, run `python -m playwright screenshot --viewport-size 1280,800 "
    "http://127.0.0.1:<your app's port>/<path> <file inside this repository>` (also at 390,844): only that form opens "
    "a browser here; your own Playwright scripts cannot start one in this sandbox."
)

# A phase that opted in to a browser of its own (``browser_mcp``): the screenshot line above would contradict the run
# contract's browser note, so this turn's note names the browser tools instead.
PLAIN_NOTE_BROWSER = PLAIN_NOTE.replace(
    "To look at a screen of the app you started, run `python -m playwright screenshot --viewport-size 1280,800 "
    "http://127.0.0.1:<your app's port>/<path> <file inside this repository>` (also at 390,844): only that form opens "
    "a browser here; your own Playwright scripts cannot start one in this sandbox.",
    "To look at the app you started, use the browser tools (mcp__playwright__browser_*) on "
    "http://127.0.0.1:<your app's port>/ only (other addresses are refused); check at 1280 and 390 px wide.")

def command(prepared: Any, *, resume: str | None) -> list[str]:
    # The prompt goes on stdin: a subagent's pkill -f on the story's app command would match every argv carrying it.
    mcp_config = str(prepared.mcp_path)
    note = PLAIN_NOTE
    browser_spec = prepared.extra.get("browser_mcp")
    if isinstance(browser_spec, dict):
        # The phase opted in to a browser of its own (``browser_mcp``): this turn's MCP config has it, no other.
        from . import browser_mcp  # noqa: PLC0415

        mcp_config = str(browser_mcp.browser_config(prepared.mcp_path, browser_spec))
        note = PLAIN_NOTE_BROWSER
    args = [prepared.cli_path, "-p", "--output-format", "json",
            "--settings", str(prepared.settings_path), "--mcp-config", mcp_config, "--strict-mcp-config",
            "--permission-mode", str(prepared.extra.get("permission_mode") or "default"),
            # Only json output sends ``"thinking": {"display": "omitted"}``; stream-json asks for updates even with
            # ``--thinking-display omitted``. The chat's live view reads the transcript instead.
            "--append-system-prompt", note, "--no-chrome"]
    if prepared.model:
        args += ["--model", prepared.model]
    args += ["--resume", resume] if resume else ["--session-id", prepared.session_key]
    effort = str(prepared.extra.get("effort") or "")
    if effort:
        args += ["--effort", effort]
    return args

# The launcher's switch for pre-release features also drops ``thinking.display`` and ``context_management`` from
# requests; without it a seat story session (forwarded unchanged) keeps Claude Code's own request shape.
EXPERIMENTAL_OFF = "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS"

def own_request_shape(prepared: Any) -> None:
    if prepared.profile != "seat":
        return
    with contextlib.suppress(OSError, ValueError):
        settings = json.loads(prepared.settings_path.read_text(encoding="utf-8"))
        if isinstance(settings.get("env"), dict) and settings["env"].pop(EXPERIMENTAL_OFF, None) is not None:
            prepared.settings_path.write_text(json.dumps(settings), encoding="utf-8")

# Every model alias a subagent may name resolves to the phase's model: the session never escalates itself to a more
# expensive model (a subagent started with ``model: "sonnet"`` maps through the session settings to Opus, which
# overrides CLAUDE_CODE_SUBAGENT_MODEL).
SUBAGENT_ALIAS_ENV = ("ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL",
                      "CLAUDE_CODE_SUBAGENT_MODEL")

def pin_subagent_models(prepared: Any) -> None:
    # The settings env outranks the process env, so the aliases are changed there.
    model = str(prepared.model or "")
    if not model:
        return
    with contextlib.suppress(OSError, ValueError):
        settings = json.loads(prepared.settings_path.read_text(encoding="utf-8"))
        env = settings.get("env") if isinstance(settings.get("env"), dict) else {}
        settings["env"] = {**env, **{key: model for key in SUBAGENT_ALIAS_ENV}}
        prepared.settings_path.write_text(json.dumps(settings), encoding="utf-8")

# The story session compacts where plain ``claude -p`` does: at the model's own window (Haiku 5.5: 1M), not at the
# device's 200K: ``CLAUDE_CODE_AUTO_COMPACT_WINDOW`` is inherited by every subagent, and a compacted agent re-reads
# the spec and re-plans.
AUTO_COMPACT_ENV = "CLAUDE_CODE_AUTO_COMPACT_WINDOW"

def environment(prepared: Any) -> dict[str, str]:
    from .hooks import DEFER_STOP_ENV  # noqa: PLC0415
    from .session_hooks import DEFER_SESSION_END_ENV

    env = {**dict(prepared.env), DEFER_STOP_ENV: "1", DEFER_SESSION_END_ENV: "1"}
    if prepared.profile == "seat":
        env.pop(EXPERIMENTAL_OFF, None)
    env.pop(AUTO_COMPACT_ENV, None)
    env.pop("CLAUDE_CODE_DISABLE_BACKGROUND_TASKS", None)
    if prepared.model:
        env.update({key: str(prepared.model) for key in SUBAGENT_ALIAS_ENV})
    return env

def map_line(row: dict[str, Any]) -> list[dict[str, Any]]:
    kind = row.get("type")
    if kind == "system":
        if row.get("subtype") == "init" and row.get("session_id"):
            event = {"kind": "session", "claude_session_id": str(row["session_id"])}
            if isinstance(row.get("model"), str) and row["model"]:
                event["model"] = row["model"][:200]
            return [event]
        if row.get("subtype") == "compact_boundary":
            meta = row.get("compact_metadata") if isinstance(row.get("compact_metadata"), dict) else {}
            return [{"kind": "compaction", "trigger": str(meta.get("trigger") or "")[:20],
                     "pre_tokens": int(meta.get("pre_tokens") or 0), "post_tokens": int(meta.get("post_tokens") or 0)}]
        if row.get("subtype") == "api_retry":
            return [{"kind": "api_retry"}]
        return []
    if kind not in ("assistant", "user") or row.get("parent_tool_use_id"):
        return []  # a subagent's own messages stay in its transcript, as in the SDK turn
    events: list[dict[str, Any]] = []
    for block in (row.get("message") or {}).get("content") or []:
        if not isinstance(block, dict):
            continue
        if kind == "assistant" and block.get("type") == "text" and block.get("text"):
            events.append({"kind": "text", "text": _clip(block["text"], 16000)})
        elif block.get("type") == "tool_use":
            tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
            event = {"kind": "tool_use", "tool": str(block.get("name")), "tool_use_id": str(block.get("id")),
                     "input_preview": input_preview(str(block.get("name")), tool_input)}
            if diff := change_diff(str(block.get("name")), tool_input):
                event["diff"] = diff
            events.append(event)
        elif block.get("type") == "tool_result":
            events.append({"kind": "tool_result", "tool_use_id": str(block.get("tool_use_id") or ""),
                           "is_error": bool(block.get("is_error")), "output": _clip(block.get("content", ""))})
    return events
