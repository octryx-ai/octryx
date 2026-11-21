"""A device turn on the pi coding agent instead of Claude Code (try it once with the pi agent).

Octryx AI should run an existing harness and make onboarding easy, not be a harness of its own. pi
(``@mariozechner/pi-coding-agent``) is a deliberately small one: read, bash, edit and write, no sub-agents, no MCP, no
permission prompts. This driver runs one chat turn of a device job on it, with the same interface as ``SdkDriver``:

- the model goes through the platform's gateway like a Claude Code turn: ``models.json`` in a per-session pi config
  directory names the gateway (Anthropic Messages API), the session headers and the device's ``apiKeyHelper`` command
  as the key, so no credential is written to disk;
- pi's JSON event stream (``--mode json``) becomes the chat's job events (text, tool use and result, usage);
- the pi session id is the turn's ``claude_session_id``, so the next turn of the thread continues it.

pi has no permission hook: the platform's PreToolUse decisions, the Workspace's deny/ask rules and the sandbox do not
apply. It is therefore opt-in per device (``harness.json``, ``{"harness": "pi"}``), only for chat turns on the
governed profile, never for a workflow run's own turn (its phase checks need the platform's hooks).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from .device_sdk import DriverStartError
from .device_sdk_events import input_preview

PI_PROVIDER = "octryx"
HARNESS_FILE = "harness.json"
MAX_TEXT = 16000
MAX_RESULT = 4000
LINE_LIMIT = 8 * 1024 * 1024


def chosen_harness(state_root: Path) -> dict[str, Any]:
    """The device's harness choice (``harness.json`` in the state directory); ``{}`` means Claude Code."""
    try:
        value = json.loads((Path(state_root) / HARNESS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) and value.get("harness") == "pi" else {}


def uses_pi(state_root: Path, offer: dict[str, Any]) -> bool:
    return bool(chosen_harness(state_root)) and not offer.get("workflow_run") and offer.get("profile") == "governed"


def pi_executable(choice: dict[str, Any]) -> str:
    path = str(choice.get("pi_path") or "").strip() or shutil.which("pi") or ""
    if not path or not os.access(path, os.X_OK):
        raise DriverStartError("pi_not_installed")
    return path


def _headers(env: dict[str, str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in str(env.get("ANTHROPIC_CUSTOM_HEADERS") or "").splitlines():
        name, _, value = line.partition(":")
        if name.strip() and value.strip():
            headers[name.strip()] = value.strip()
    return headers


def models_config(env: dict[str, str], *, model: str, key_command: str, context_window: int) -> dict[str, Any]:
    """pi's ``models.json``: one provider, the platform's gateway; the key is the device's helper command."""
    return {"providers": {PI_PROVIDER: {
        "baseUrl": str(env.get("ANTHROPIC_BASE_URL") or ""),
        "api": "anthropic-messages",
        "apiKey": f"!{key_command}" if key_command else "none",
        "headers": _headers(env),
        "models": [{"id": model, "name": model, "reasoning": False, "input": ["text"],
                    "contextWindow": context_window, "maxTokens": 16000,
                    "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}}],
    }}}


def _texts(message: dict[str, Any]) -> str:
    return "".join(str(block.get("text") or "") for block in message.get("content") or []
                   if isinstance(block, dict) and block.get("type") == "text")


def _clip(value: Any, limit: int = MAX_RESULT) -> str:
    if not isinstance(value, str):
        if isinstance(value, dict) and isinstance(value.get("content"), list):
            value = "".join(str(item.get("text") or "") for item in value["content"] if isinstance(item, dict))
        else:
            value = json.dumps(value, ensure_ascii=False, default=str)
    return value if len(value) <= limit else value[:limit] + "…"


class Usage:
    def __init__(self) -> None:
        self.input = self.output = self.cache_read = self.cache_write = self.context = 0
        self.cost = 0.0

    def add(self, usage: Any) -> None:
        if not isinstance(usage, dict):
            return
        self.input += int(usage.get("input") or 0)
        self.output += int(usage.get("output") or 0)
        self.cache_read += int(usage.get("cacheRead") or 0)
        self.cache_write += int(usage.get("cacheWrite") or 0)
        self.context = int(usage.get("totalTokens") or 0) or self.context
        cost = usage.get("cost")
        if isinstance(cost, dict):
            self.cost += float(cost.get("total") or 0)

    def as_claude(self) -> dict[str, int]:
        return {"input_tokens": self.input, "output_tokens": self.output,
                "cache_read_input_tokens": self.cache_read, "cache_creation_input_tokens": self.cache_write}


def map_event(event: dict[str, Any], usage: Usage, last: dict[str, str]) -> list[dict[str, Any]]:
    """One pi JSON event → the job events the chat sees."""
    kind = event.get("type")
    if kind == "session" and event.get("id"):
        return [{"kind": "session", "claude_session_id": str(event["id"])}]
    if kind == "message_update":
        delta = event.get("assistantMessageEvent") or {}
        if isinstance(delta, dict) and delta.get("type") == "text_delta" and delta.get("delta"):
            return [{"kind": "text_delta", "text": str(delta["delta"])}]
        return []
    if kind == "message_end":
        message = event.get("message") or {}
        if not isinstance(message, dict) or message.get("role") != "assistant":
            return []
        usage.add(message.get("usage"))
        text = _texts(message)
        if text:
            last["text"] = text
            return [{"kind": "text", "text": _clip(text, MAX_TEXT)}]
        return []
    if kind == "tool_execution_start":
        name, args = str(event.get("toolName") or ""), event.get("args") if isinstance(event.get("args"), dict) else {}
        return [{"kind": "tool_use", "tool": name, "tool_use_id": str(event.get("toolCallId") or ""),
                 "input_preview": input_preview(name, args)}]
    if kind == "tool_execution_end":
        return [{"kind": "tool_result", "tool_use_id": str(event.get("toolCallId") or ""),
                 "is_error": bool(event.get("isError")), "output": _clip(event.get("result"))}]
    if kind == "auto_retry_start":
        return [{"kind": "api_retry"}]
    if kind == "compaction_end":
        return [{"kind": "compaction", "trigger": str(event.get("reason") or "")[:20], "pre_tokens": 0,
                 "post_tokens": 0}]
    return []


class PiDriver:
    """Runs one turn on pi; ``interrupt``/``disconnect`` may be called from another task while it runs."""

    def __init__(self, state_root: Path, choice: dict[str, Any]) -> None:
        self.state_root = Path(state_root)
        self.choice = choice
        self._process: asyncio.subprocess.Process | None = None

    def _config_dir(self, prepared: Any) -> tuple[Path, Path]:
        root = self.state_root / "pi" / str(prepared.session_key)
        sessions = self.state_root / "pi" / "sessions"
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        sessions.mkdir(parents=True, exist_ok=True, mode=0o700)
        settings = {}
        with contextlib.suppress(OSError, ValueError):
            settings = json.loads(Path(prepared.settings_path).read_text(encoding="utf-8"))
        model = str(prepared.model or prepared.env.get("ANTHROPIC_MODEL") or "")
        window = prepared.extra.get("context_window")
        config = models_config(prepared.env, model=model, key_command=str(settings.get("apiKeyHelper") or ""),
                               context_window=window if isinstance(window, int) and window > 0 else 200000)
        path = root / "models.json"
        path.write_text(json.dumps(config, indent=1), encoding="utf-8")
        path.chmod(0o600)
        return root, sessions

    def command(self, prepared: Any, *, prompt: str, resume: str | None, sessions: Path) -> list[str]:
        model = str(prepared.model or prepared.env.get("ANTHROPIC_MODEL") or "")
        args = [pi_executable(self.choice), "--mode", "json", "-p", "--model", f"{PI_PROVIDER}/{model}",
                "--session-dir", str(sessions)]
        if resume:
            args += ["--session", resume]
        return [*args, prompt]

    async def run_turn(self, prepared: Any, *, cwd: str, prompt: str, resume: str | None, fork: bool = False,
                       decide: Any = None, emit: Any) -> dict[str, Any]:
        """Run the prompt to its end; returns ``{status, result_text, cost_usd, usage, claude_session_id}``."""
        config_dir, sessions = self._config_dir(prepared)
        env = {**os.environ, **{key: value for key, value in prepared.env.items() if value != ""},
               "PI_CODING_AGENT_DIR": str(config_dir)}
        try:
            self._process = await asyncio.create_subprocess_exec(
                *self.command(prepared, prompt=prompt, resume=resume, sessions=sessions), cwd=cwd, env=env,
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                limit=LINE_LIMIT)
        except OSError as exc:
            raise DriverStartError("pi_not_started") from exc
        usage, last = Usage(), {"text": ""}
        result: dict[str, Any] = {"status": "error", "result_text": "", "claude_session_id": resume}
        ended = False
        assert self._process.stdout is not None
        async for raw in self._process.stdout:
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            for item in map_event(event, usage, last):
                if item["kind"] == "session":
                    result["claude_session_id"] = item["claude_session_id"]
                await emit(item)
            if event.get("type") == "agent_end":
                ended = True
        stderr = (await self._process.stderr.read()).decode("utf-8", "replace") if self._process.stderr else ""
        code = await self._process.wait()
        self._process = None
        if usage.context:
            await emit({"kind": "context", "tokens": usage.context})
        result.update({"status": "success" if ended and code == 0 else "error", "result_text": last["text"],
                       "cost_usd": round(usage.cost, 6), "usage": usage.as_claude()})
        if result["status"] == "error":
            result["error"] = (stderr.strip().splitlines() or [f"pi exited {code}"])[-1][:300]
        return result

    async def interrupt(self) -> None:
        if self._process is not None and self._process.returncode is None:
            self._process.terminate()

    async def disconnect(self) -> None:
        if self._process is not None and self._process.returncode is None:
            self._process.kill()


__all__ = ["HARNESS_FILE", "PiDriver", "chosen_harness", "map_event", "models_config", "uses_pi"]
