"""The phase in a few lines, before the agent starts (``phase.brief``)."""

from __future__ import annotations

from typing import Any

MAX_PATHS = 12  # a phase's own patterns stay short; a longer list is cut with an ellipsis


def _joined(items: list[str]) -> str:
    shown = [f"`{item}`" for item in items[:MAX_PATHS]]
    return ", ".join(shown) + (", …" if len(items) > MAX_PATHS else "")


def _environment(contract: dict[str, Any]) -> dict[str, Any]:
    value = dict(contract.get("preparation") or {}).get("environment")
    return dict(value) if isinstance(value, dict) else {}


def _test_lines(environment: dict[str, Any], phase: dict[str, Any]) -> list[str]:
    from ...engineering_knowledge.stacks import test_runners
    from ..run_texts import run_text
    from .declared_commands import declared_commands

    if not phase.get("how_to_run_tests") and phase.get("capability_class") == "read_only":
        return []
    folder = str(environment.get("app_folder") or ".")
    declared = declared_commands(environment)
    test = str(environment.get("test") or "").strip()
    lint = str(environment.get("lint") or "").strip()
    system = str(environment.get("system_test") or "").strip()
    # The system test starts a browser, which runs only outside the sandbox, and only a command that is the test run
    # alone goes there (inside a longer command it hung 20 minutes).
    alone = [run_text("brief.system_test_alone", command=system, folder=folder)] if declared and system else []
    if declared and test:
        lines = [run_text("brief.tests_declared", command=test, folder=folder)]
        return lines + ([run_text("brief.lint_declared", command=lint, folder=folder)] if lint else []) + alone
    hints = "; ".join(f"{runner.get('label') or 'tests'}: {runner['hint']}" for runner in test_runners()
                      if runner.get("hint"))
    return [run_text("brief.tests_undeclared", folder=folder, hints=hints)]


def _shell_lines(phase: dict[str, Any]) -> list[str]:
    from ..run_texts import run_text

    rules = dict(phase.get("path_rules") or {})
    if phase.get("capability_class") == "read_only" or rules.get("protect_confirmed_tests"):
        return [run_text("brief.shell_strict")]
    return []


def _file_lines(contract: dict[str, Any], phase: dict[str, Any]) -> list[str]:
    from ..run_texts import run_text

    if phase.get("capability_class") == "read_only":
        return [run_text("brief.read_only")]
    rules = dict(phase.get("path_rules") or {})
    write = [str(item) for item in rules.get("write") or []]
    create = [str(item) for item in rules.get("create") or []]
    lines = [run_text("brief.write_paths", paths=_joined(write)) if write else run_text("brief.write_any")]
    if create:
        lines.append(run_text("brief.create_paths", paths=_joined(create)))
    locked = [str(item) for item in phase.get("protected_files") or []]
    if rules.get("protect_confirmed_tests") and rules.get("write_tests"):
        lines.append(run_text("brief.tests_writable", files=_joined(locked) if locked else "none yet"))
    elif rules.get("protect_confirmed_tests"):
        lines.append(run_text("brief.tests_locked", files=_joined(locked) if locked else "none yet"))
    pin = str(phase.get("contract_file") or "")
    if pin and not phase.get("allow_contract_change"):
        lines.append(run_text("brief.contract_file", file=pin))
    return lines


def _platform_lines(run: Any, phase: dict[str, Any]) -> list[str]:
    from ..run_texts import run_text

    rules = dict(phase.get("path_rules") or {})
    lines = []
    if rules.get("write_tests") and phase.get("output"):
        lines.append(run_text("brief.platform_confirms"))
    if phase.get("pipeline_after"):
        lines.append(run_text("brief.platform_pipeline"))
    if phase.get("capability_class") != "read_only":
        lines.append(run_text("brief.platform_push"))
    return lines


def _short_output(run: Any, contract: dict[str, Any]) -> str:
    from ...engineering_knowledge.stacks import test_runners
    from ..run_memory import for_brief

    for entry in (for_brief(run) if run is not None else {}).get("large_output") or []:
        if entry.get("shorter"):
            return str(entry["shorter"])
    declared = str(_environment(contract).get("test") or "").strip()
    words = declared.split()
    for runner in test_runners():
        if runner.get("short_output") and any(words[index:index + len(command)] == list(command)
                                              for command in runner.get("commands") or []
                                              for index in range(len(words))):
            return str(runner["short_output"])
    return f"{declared} 2>&1 | tail -30" if declared else ""


def _output_lines(run: Any, contract: dict[str, Any], phase: dict[str, Any]) -> list[str]:
    from ..run_texts import run_text

    if not phase.get("pipeline_after"):
        return []  # without a pipeline after it the gates judge the agent's own test output: never ask it shorter
    short = _short_output(run, contract)
    return [run_text("brief.short_output", command=short) if short else run_text("brief.short_output_general")]


def _memory_lines(run: Any) -> list[str]:
    from ..run_memory import for_brief
    from ..run_memory.store import data
    from ..run_texts import run_text

    memory = for_brief(run) if run is not None else {}
    lines = [run_text("brief.memory_test_command", command=entry["command"])
             for entry in memory.get("test_command") or [] if entry.get("command")]
    lines += [run_text("brief.memory_environment_fix", error=entry["error"], ran=entry.get("ran") or "")
              for entry in memory.get("environment_fix") or [] if entry.get("error")]
    lines += [run_text("brief.memory_denial", reason=entry.get("reason") or "", refused=entry["refused"],
                       worked=entry.get("worked") or "")
              for entry in memory.get("denial_alternative") or [] if entry.get("refused")]
    lines += [run_text("brief.memory_large_output_shorter" if entry.get("shorter") else "brief.memory_large_output",
                       command=entry["command"], kb=entry.get("kb") or "", shorter=entry.get("shorter") or "")
              for entry in memory.get("large_output") or [] if entry.get("command")]
    lines = lines[: int(data()["brief_max_lines"])]
    return [run_text("brief.memory_head"), *lines] if lines else []


def phase_brief(run: Any, contract: dict[str, Any]) -> str:
    from ..run_texts import run_text

    phase = contract.get("phase")
    if not isinstance(phase, dict):
        return ""
    lines = [run_text("brief.head", phase=str(phase.get("title") or phase.get("node_id") or ""))]
    lines += _test_lines(_environment(contract), phase)
    lines += _shell_lines(phase)
    lines += _file_lines(contract, phase)
    lines += _platform_lines(run, phase)
    lines += _output_lines(run, contract, phase)
    lines += _memory_lines(run)
    checks = [str(item) for item in phase.get("checks") or [] if str(item).strip()]
    if checks:
        lines.append(run_text("brief.checks", checks="; ".join(checks)))
    lines.append(run_text("brief.tail"))
    return "\n".join(line for line in lines if line)


__all__ = ["phase_brief"]
