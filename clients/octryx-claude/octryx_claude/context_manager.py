"""The context manager: what a session keeps when Claude Code compacts it (can be turned off)."""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

from .state import LocalState, read_json, write_private_json

MAX_TRANSCRIPT_BYTES = 16 * 1024 * 1024
MAX_INSTRUCTIONS = 6000
MAX_REQUESTS = 6
MAX_FILES = 30
MAX_TESTS = 4
CHANGE_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
TEST_RUNNER = re.compile(r"^(pytest|python3? -m pytest|uv run pytest|poetry run pytest|npm (run )?test|"
                         r"pnpm (run )?test|yarn test|npx (vitest|jest)|vitest|jest|node --test|"
                         r"(\./)?mvnw?( -\S+)* (test|verify)|(\./)?gradlew?( -\S+)* test|go test|cargo test|"
                         r"make test|dotnet test|tox|rspec|bundle exec rspec)(\s|$)")


def is_test_command(command: str) -> bool:
    if "<<" in command:
        command = command.split("\n", 1)[0]  # a heredoc's body is data (a file being written), not commands
    segments = re.split(r"[;\n]|&&|\|\|?", command)
    return any(TEST_RUNNER.match(_program_basename(_ENV_PREFIX.sub("", segment.strip()))) for segment in segments)


def _program_basename(segment: str) -> str:
    first, _, rest = segment.partition(" ")
    if "/" in first and not first.startswith("./"):
        first = first.rsplit("/", 1)[-1]
    return f"{first} {rest}".strip()


_ENV_PREFIX = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]*=(?:\$\([^)]*\)|\S*)\s+)+")
_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
RECENCY = 0.85  # each older request counts this much less when the decision model ranks them


def enabled(state: LocalState) -> bool:
    if os.environ.get("OCTRYX_CONTEXT_MANAGER", "").strip().lower() in ("0", "off", "false", "no"):
        return False
    return state.config().get("context_manager") is not False


def own_transcript(state: LocalState, hook_input: dict[str, Any]) -> Path | None:
    from .digest import transcript_inside  # noqa: PLC0415

    raw = str(hook_input.get("transcript_path") or "")
    for root in (state.claude_config_dir, state.claude_config_dir_for("seat")):
        found = transcript_inside(raw, root)
        if found is not None:
            return found
    return None


def _tail_lines(path: Path) -> list[str]:
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - MAX_TRANSCRIPT_BYTES))
        data = handle.read()
    lines = data.decode("utf-8", errors="replace").splitlines()
    return lines[1:] if size > MAX_TRANSCRIPT_BYTES else lines  # the first line may be cut


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(part.get("text") or "") for part in content
                         if isinstance(part, dict) and part.get("type") == "text")
    return ""


def extract(lines: list[str]) -> dict[str, Any]:
    requests: list[str] = []
    files: list[str] = []
    tests: list[dict[str, Any]] = []
    pending_tests: dict[str, str] = {}
    todos: list[str] = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("isCompactSummary"):
            continue
        origin = entry.get("origin") if isinstance(entry.get("origin"), dict) else {}
        if entry.get("type") == "user" and origin.get("kind") == "peer" and isinstance(origin.get("body"), str):
            # A message from the phone (the live relay) or another session: a request like a typed one.
            sender = str(origin.get("name") or "another session")[:40]
            requests.append(f"(from {sender}) {origin['body'].strip()[:600]}")
            continue
        if entry.get("isMeta"):
            continue
        message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
        content = message.get("content")
        if entry.get("type") == "user":
            text = _text(content).strip()
            if text and not text.startswith("<") and not text.startswith("Caveat:"):
                requests.append(text[:600])
            for part in content if isinstance(content, list) else []:
                if isinstance(part, dict) and part.get("type") == "tool_result" and \
                        part.get("tool_use_id") in pending_tests:
                    tests.append({"command": pending_tests.pop(part["tool_use_id"]),
                                  "passed": not part.get("is_error")})
        elif entry.get("type") == "assistant":
            for part in content if isinstance(content, list) else []:
                if not isinstance(part, dict) or part.get("type") != "tool_use":
                    continue
                tool_input = part.get("input") if isinstance(part.get("input"), dict) else {}
                name = part.get("name")
                if name in CHANGE_TOOLS:
                    path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
                    if path:
                        files = [item for item in files if item != path] + [path]
                elif name == "Bash" and is_test_command(str(tool_input.get("command") or "")):
                    pending_tests[str(part.get("id") or "")] = str(tool_input.get("command"))[:200]
                elif name == "TodoWrite" and isinstance(tool_input.get("todos"), list):
                    todos = [str(item.get("content") or "")[:200] for item in tool_input["todos"]
                             if isinstance(item, dict) and item.get("status") != "completed" and item.get("content")]
    return {"goal": requests[0] if requests else "", "requests": requests[-12:][::-1], "files": files[-MAX_FILES:],
            "tests": tests[-MAX_TESTS:], "todos": todos[:12]}


async def _rank(requests: list[str], state: LocalState) -> list[str]:
    from . import device_state  # noqa: PLC0415
    from .local_model import D1_2B, LocalModel, chosen_model, find_llama_server, model_path, usable  # noqa: PLC0415

    # Only the decision model answers these choice questions, and it is under the LFM licence: only when the person
    # chose and accepted it and the platform last said restricted licences are allowed (never loaded by default).
    device = device_state.load_device(state)
    permissive_only = device.get("local_models_permissive_only") is not False
    if chosen_model(device) != D1_2B or not usable(D1_2B, device, permissive_only=permissive_only):
        return requests
    models_dir = state.root / "models"
    if not requests or not find_llama_server() or model_path(models_dir, spec=D1_2B) is None:
        return requests
    model = LocalModel(models_dir, spec=D1_2B)
    scored: list[tuple[float, int, str]] = []
    try:
        for index, request in enumerate(requests):
            answer = await model.ask("/v1/systemone", {
                "state": f"A request the person made earlier in a coding session: {request[:1500]}",
                "questions": {"keep": {"type": "choice",
                                       "instructions": "Does this request matter for continuing the work later?",
                                       "criteria": {"important": "a goal, a decision, a constraint or open work",
                                                    "minor": "small talk, a done one-off, a typo fix, an ack"}}}})
            probability = float((((answer.get("answers") or {}).get("keep") or {}).get("probabilities") or {})
                                .get("important") or 0)
            scored.append((probability * RECENCY ** index, -index, request))
    except Exception:  # noqa: BLE001 - the ranking is a bonus; recency is the fallback
        return requests
    finally:
        await model.stop()
    return [request for _, _, request in sorted(scored, reverse=True)]


def facts_text(facts: dict[str, Any], *, heading: str) -> str:
    parts = [heading]
    if facts.get("goal"):
        parts.append(f"Earliest request in view (the session's goal): {facts['goal']}")
    if facts.get("requests"):
        parts.append("Requests that matter for continuing (most important first):")
        parts.extend(f"- {item}" for item in facts["requests"][:MAX_REQUESTS])
    if facts.get("todos"):
        parts.append("Open todo items:")
        parts.extend(f"- {item}" for item in facts["todos"])
    if facts.get("files"):
        parts.append("Files changed in this session: " + ", ".join(facts["files"]))
    if facts.get("tests"):
        parts.append("Test runs (latest last): " + "; ".join(
            f"`{item['command']}` {'passed' if item['passed'] else 'FAILED'}" for item in facts["tests"]))
    return "\n".join(parts)[:MAX_INSTRUCTIONS]


def _facts_path(state: LocalState, session_id: str) -> Path | None:
    return state.root / "context" / f"{session_id}.json" if _SESSION_ID.match(session_id or "") else None


def pre_compact(state: LocalState, hook_input: dict[str, Any], *, rank: bool = True) -> str:
    if not enabled(state):
        return ""
    transcript = own_transcript(state, hook_input)
    try:
        facts = extract(_tail_lines(transcript)) if transcript is not None and transcript.is_file() else {}
    except OSError:
        facts = {}
    if not any(facts.values()):
        return ""
    if rank:
        facts["requests"] = asyncio.run(_rank(facts.get("requests") or [], state))
    path = _facts_path(state, str(hook_input.get("session_id") or ""))
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_private_json(path, facts)
    return facts_text(facts, heading=(
        "octryx context manager: in the summary, keep the following complete and verbatim (paths, commands, results, "
        "decisions). Drop exploration that led nowhere, repeated file contents and long tool output."))


def session_start(state: LocalState, hook_input: dict[str, Any]) -> dict[str, Any] | None:
    if hook_input.get("source") != "compact" or not enabled(state):
        return None
    path = _facts_path(state, str(hook_input.get("session_id") or ""))
    facts = read_json(path) if path is not None and path.exists() else {}
    if not isinstance(facts, dict) or not any(facts.values()):
        return None
    return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": facts_text(
        facts, heading="Restored by octryx after the compaction (the facts kept from before it):")}}


__all__ = ["enabled", "extract", "facts_text", "pre_compact", "session_start"]
