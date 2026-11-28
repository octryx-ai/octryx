"""What the agent reads of a long test run: the summary and its failures, the full report stays with the platform."""

from __future__ import annotations

from typing import Any

from ..engineering_knowledge.stacks import built_in, test_runners
from .test_output import ERROR, FAILED, PASSED, SKIPPED, parse

FULL_REPORT = "The full report is with the platform."


def settings(command: str, stacks: dict[str, Any] | None = None) -> dict[str, Any] | None:
    from .test_results import DEFAULT_TEST_PREFIXES

    words = command.split()
    starts = [i for i, word in enumerate(words) if i == 0 or words[i - 1] in ("&&", ";", "||")]
    data = stacks or built_in()
    base = dict(dict(data.get("general") or {}).get("test_brief") or {})
    runners = [(tuple(prefix), dict(runner.get("brief") or {})) for runner in test_runners(data)
               for prefix in runner.get("commands") or []]
    runners += [(tuple(prefix), {}) for prefix in DEFAULT_TEST_PREFIXES]
    for start in starts:
        for prefix, own in runners:
            if tuple(words[start:start + len(prefix)]) == prefix:
                return {**base, **own}
    return None


def brief(command: str, output: str, stacks: dict[str, Any] | None = None) -> str:
    limits = settings(command, stacks)
    if limits is None or len(output) < int(limits.get("min_chars") or 0):
        return ""
    parsed = parse(output, command=command)
    outcomes = [str(value.get("outcome")) for value in parsed.results.values()]
    outcomes += [str(item.get("outcome")) for item in parsed.unresolved]
    counts = {name: outcomes.count(name) for name in (PASSED, FAILED, ERROR, SKIPPED) if outcomes.count(name)}
    passed = counts.get(PASSED, 0) or parsed.suite_passed
    if passed:
        counts[PASSED] = passed
    summary = ", ".join(f"{number} {name}" for name, number in counts.items()) or "no test result could be read"
    failing = [(test_id, value) for test_id, value in parsed.results.items() if value.get("outcome") in (FAILED, ERROR)]
    failing += [(str(item.get("raw") or ""), item) for item in parsed.unresolved
                if item.get("outcome") in (FAILED, ERROR)]
    lines = [f"Test run ({len(output)} characters of output, cut for you): {summary}. {FULL_REPORT}"]
    width = int(limits.get("message_chars") or 0)
    for test_id, value in failing[:int(limits.get("max_failures") or 0)]:
        message = " ".join(str(value.get("message") or "").split())[:width]
        lines.append(f"- {value.get('outcome')}: {test_id}" + (f": {message}" if message else ""))
    if len(failing) > int(limits.get("max_failures") or 0):
        lines.append(f"- … and {len(failing) - int(limits.get('max_failures') or 0)} more failing")
    return "\n".join(lines)[:int(limits.get("max_chars") or 4000)]


async def hook_brief(db: Any, workspace_id: str, hook_input: dict[str, Any]) -> str:
    tool_input = hook_input.get("tool_input") if isinstance(hook_input.get("tool_input"), dict) else {}
    response = hook_input.get("tool_response") if isinstance(hook_input.get("tool_response"), dict) else {}
    command = str(tool_input.get("command") or "")
    if hook_input.get("tool_name") != "Bash" or settings(command) is None:
        return ""
    from ...models import Project
    from ..engineering_knowledge.stacks import for_project

    stacks = await for_project(db, await db.get(Project, workspace_id))
    return brief(command, f"{response.get('stdout') or ''}\n{response.get('stderr') or ''}", stacks)


__all__ = ["brief", "hook_brief", "settings"]
