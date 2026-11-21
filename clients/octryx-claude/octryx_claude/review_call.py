"""The independent reviewer's call on this device's seat: one tool-less model call.

The platform cannot reach a person's subscription by itself (the seat routes only pass on the ``Authorization`` the
device's own Claude Code or Codex sends). A workflow run's review on the seat therefore runs here, as a device job
turn whose offer carries ``review_call``:

1. the turn's session is registered with the job's id, so the platform knows it is the reviewer's (it denies every
   tool call of it at the PreToolUse check);
2. the request (system text, task, screenshots) is fetched from the platform
   (``GET /api/v1/agent-gateway/review-request``); it never travels in the offer;
3. one call with **no tools**, in an empty temporary folder, with no history:
   - Claude Code: ``claude -p --tools "" --setting-sources "" --strict-mcp-config`` with an empty MCP config, the
     reviewer's system prompt and the task (and screenshots as image blocks) as one stream-json user message;
   - Codex: ``codex exec --ephemeral --sandbox read-only`` in the empty folder, the screenshots as ``--image``; Codex
     always offers its shell, so the platform's PreToolUse check (``review_tool_not_allowed``) and the read-only
     sandbox in an empty folder are what keep it tool-less;
     with the platform's ``seat_traffic`` on ``device`` its call leaves from this device through the turn's own
     loopback seat proxy (``codex_seat_proxy``), like any Codex seat turn (the relay route refuses it with
     ``codex_seat_traffic_device``);
4. the answer and its usage go back (``POST /api/v1/agent-gateway/review-answer``); the turn reports only that it
   answered, never the answer itself in the chat.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger("octryx_claude.device.review")

EMPTY_MCP = json.dumps({"mcpServers": {}})
STREAM_LIMIT = 64 * 1024 * 1024
# Clearly below the platform's wait for the answer (review.seat.CALL_TIMEOUT_SECONDS 300 s, counted from the
# request; this one from the offer's arrival and the CLI start).
CALL_TIMEOUT_SECONDS = 240
REQUEST_PATH = "/review-request"
ANSWER_PATH = "/review-answer"
_SUFFIXES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}

# ``control(method, path, body)`` → ``(ok, body or reason)``: the platform's control plane with this session's headers.
Control = Callable[[str, str, dict[str, Any] | None], tuple[bool, Any]]


class ReviewCallError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def claude_command(prepared: Any, *, system: str, model: str) -> list[str]:
    """``claude -p`` for one tool-less call: no tools, no MCP server, no settings of the folder or the person."""
    args = [prepared.cli_path, "-p", "--output-format", "stream-json", "--verbose", "--input-format", "stream-json",
            "--settings", str(prepared.settings_path), "--setting-sources", "", "--mcp-config", EMPTY_MCP,
            "--strict-mcp-config", "--tools", "", "--disable-slash-commands", "--no-chrome",
            "--permission-mode", "default", "--system-prompt", system, "--session-id", prepared.session_key]
    return [*args, "--model", model] if model else args


def claude_message(user: str, images: list[dict[str, Any]]) -> str:
    """The one user message: the task, then each screenshot after its name."""
    content: list[dict[str, Any]] = [{"type": "text", "text": user}]
    for image in images:
        content.append({"type": "text", "text": f"Screenshot: {image.get('name') or ''}"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": str(image.get("media_type")),
                                                    "data": str(image.get("data") or "")}})
    return json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n"


def claude_result(lines: list[str]) -> dict[str, Any]:
    """The answer, usage and model from ``claude -p --output-format stream-json`` lines."""
    model, result = "", None
    for line in lines:
        with contextlib.suppress(ValueError):
            row = json.loads(line)
            if not isinstance(row, dict):
                continue
            if row.get("type") == "system" and row.get("subtype") == "init":
                model = str(row.get("model") or "")
            elif row.get("type") == "result":
                result = row
    if result is None or result.get("is_error"):
        raise ReviewCallError("review_call_failed")
    usage = dict(result.get("usage") or {})
    tokens_in = sum(int(usage.get(key) or 0) for key in
                    ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    return {"text": str(result.get("result") or ""), "model": model,
            "usage": {"input_tokens": tokens_in, "output_tokens": int(usage.get("output_tokens") or 0)}}


def codex_command(codex: str, *, cwd: str, model: str, images: list[str], answer_file: str) -> list[str]:
    args = [codex, "exec", "--json", "--ephemeral", "--skip-git-repo-check", "--dangerously-bypass-hook-trust",
            "--sandbox", "read-only", "-C", cwd, "-o", answer_file]
    for image in images:
        args += ["--image", image]
    return [*args, *(["-m", model] if model else []), "-"]


def codex_prompt(system: str, user: str) -> str:
    """Codex takes no system prompt of its own here: the reviewer's instructions come first."""
    return f"{system}\n\nYou have no tools in this session: answer from this message alone.\n\n{user}"


def codex_usage(lines: list[str]) -> dict[str, int]:
    tokens_in = tokens_out = 0
    for line in lines:
        with contextlib.suppress(ValueError):
            row = json.loads(line)
            usage = row.get("usage") if isinstance(row, dict) and row.get("type") == "turn.completed" else None
            if isinstance(usage, dict):
                tokens_in += int(usage.get("input_tokens") or 0)
                tokens_out += int(usage.get("output_tokens") or 0)
    return {"input_tokens": tokens_in, "output_tokens": tokens_out}


def codex_failure(lines: list[str]) -> str:
    """A failed Codex review call: the seat's limit as its fixed code (``usage_limit`` / ``rate_limit``, so the
    platform waits for the reset), else ``""``. Codex's own error text goes to the device log only, so a
    ``review_call_failed`` can be traced there."""
    from .seat_status import codex_limit_code  # noqa: PLC0415

    for line in lines:
        with contextlib.suppress(ValueError):
            row = json.loads(line)
            if not isinstance(row, dict) or row.get("type") not in ("turn.failed", "error"):
                continue
            limit = codex_limit_code(row)
            if limit:
                return limit
            error = row.get("error") if isinstance(row.get("error"), dict) else {}
            message = str(error.get("message") or row.get("message") or "")[:500]
            logger.warning("review call: codex reported %s", message)
    return ""


def write_images(folder: Path, images: list[dict[str, Any]]) -> list[str]:
    paths = []
    for number, image in enumerate(images, 1):
        path = folder / f"screen-{number}{_SUFFIXES.get(str(image.get('media_type')), '.png')}"
        path.write_bytes(base64.b64decode(str(image.get("data") or "")))
        paths.append(str(path))
    return paths


async def _run(args: list[str], *, cwd: str, env: dict[str, str], stdin: str,
               started: Callable[[Any], None] | None = None) -> tuple[int, list[str]]:
    process = await asyncio.create_subprocess_exec(*args, cwd=cwd, env=env, stdin=asyncio.subprocess.PIPE,
                                                   stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                                                   limit=STREAM_LIMIT)
    if started is not None:
        started(process)
    try:
        out, _ = await asyncio.wait_for(process.communicate(stdin.encode()), CALL_TIMEOUT_SECONDS)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        raise ReviewCallError("review_call_timed_out") from None
    return int(process.returncode or 0), out.decode(errors="replace").splitlines()


class ReviewCallDriver:
    """The device turn of a ``review_call`` offer (same interface as the other drivers)."""

    def __init__(self, control: Control, *, engine: str = "", proxy_factory: Any = None) -> None:
        self._control = control
        self._engine = engine
        self._process: Any = None
        # Builds the turn's seat proxy (``codex_seat_proxy.SeatProxy``) from the platform URL; a seam for tests.
        self._proxy_factory = proxy_factory

    def _started(self, process: Any) -> None:
        self._process = process

    async def run_turn(self, prepared: Any, *, cwd: str, prompt: str, resume: str | None, fork: bool = False,
                       decide: Any = None, emit: Any = None) -> dict[str, Any]:
        del cwd, prompt, resume, fork, decide  # the request is the platform's; the folder is never read
        ok, request = await asyncio.to_thread(self._control, "GET", REQUEST_PATH, None)
        if not ok or not isinstance(request, dict) or not request.get("turn_id"):
            return {"status": "error", "error": "review_request_unavailable"}
        folder = Path(tempfile.mkdtemp(prefix="octryx-review-"))
        try:
            answered = await (self._codex(prepared, request, folder) if self._engine == "codex"
                              else self._claude(prepared, request, folder))
        except ReviewCallError as error:
            return {"status": "error", "error": error.code}
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        ok, _ = await asyncio.to_thread(self._control, "POST", ANSWER_PATH, {"turn_id": request["turn_id"],
                                                                             **answered})
        if not ok:
            return {"status": "error", "error": "review_answer_not_recorded"}
        if emit is not None:
            with contextlib.suppress(Exception):
                await emit({"kind": "text", "text": "The independent review answered."})
        return {"status": "success", "result_text": "The independent review answered.", "model": answered["model"],
                "usage": answered["usage"]}

    async def _claude(self, prepared: Any, request: dict[str, Any], folder: Path) -> dict[str, Any]:
        from .plain_session import environment  # noqa: PLC0415

        model = str(request.get("model") or prepared.model or "")
        args = claude_command(prepared, system=str(request.get("system") or ""), model=model)
        message = claude_message(str(request.get("user") or ""), list(request.get("images") or []))
        code, lines = await _run(args, cwd=str(folder), env=environment(prepared), stdin=message,
                                 started=self._started)
        answered = claude_result(lines)
        if code != 0 and not answered["text"]:
            raise ReviewCallError("review_call_failed")
        return {**answered, "model": answered["model"] or model}

    async def _codex(self, prepared: Any, request: dict[str, Any], folder: Path) -> dict[str, Any]:
        from .codex_config import (
            environment,
            prepare_home,  # noqa: PLC0415
        )

        work = folder / "empty"
        work.mkdir()
        model = str(request.get("model") or prepared.model or "")
        answer_file = folder / "answer.txt"
        args = codex_command(prepared.cli_path, cwd=str(work), model=model,
                             images=write_images(folder, list(request.get("images") or [])),
                             answer_file=str(answer_file))
        proxy = await self._start_proxy(prepared)
        try:
            home = prepare_home(prepared, sandboxed=True, seat_proxy=proxy.url if proxy is not None else "")
            env = environment(prepared, home, proxy_token=proxy.token if proxy is not None else "")
            code, lines = await _run(args, cwd=str(work), env=env, started=self._started,
                                     stdin=codex_prompt(str(request.get("system") or ""),
                                                        str(request.get("user") or "")))
        finally:
            if proxy is not None:
                await proxy.stop()
        text = answer_file.read_text(encoding="utf-8") if answer_file.exists() else ""
        if not text:
            raise ReviewCallError(codex_failure(lines) or ("review_call_failed" if code else "review_call_empty"))
        return {"text": text, "model": model, "usage": codex_usage(lines)}

    async def _start_proxy(self, prepared: Any) -> Any:
        """The turn's loopback seat proxy when the seat's calls leave from this device (``seat_traffic: device``)."""
        from .codex_seat import sends_from_device  # noqa: PLC0415

        if not sends_from_device(prepared.extra):
            return None
        from .codex_seat_proxy import SeatProxy  # noqa: PLC0415

        base_url = str((prepared.extra.get("gateway") or {}).get("base_url") or "")
        try:
            return await (self._proxy_factory or SeatProxy)(base_url).start()
        except OSError:
            raise ReviewCallError("codex_seat_proxy_unavailable") from None

    async def interrupt(self) -> None:
        if self._process is not None and self._process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self._process.kill()

    async def disconnect(self) -> None:
        await self.interrupt()


def runs_review(offer: dict[str, Any]) -> bool:
    return offer.get("review_call") is True


__all__ = ["ReviewCallDriver", "ReviewCallError", "claude_command", "claude_message", "claude_result", "codex_command",
           "codex_failure", "runs_review"]
