"""The platform's launcher texts (``run.launcher.*``) with their fallbacks, and the summaries of a red pipeline the
session's next turn reads (``pipeline``)."""

from __future__ import annotations

import re
from typing import Any

RED_TAIL_LINES = 40


# The platform's texts (prompt catalog ``run.launcher.*``, the run contract's ``prompt_texts``; data, overridable per
# workflow and Workspace); these copies answer a hook that has no run contract to read (no run, or the platform is
# unreachable when a call is denied fail-closed).
FALLBACK_TEXTS = {
    "run.launcher.compound_test": "The system test starts the app and a browser, and the browser starts only "
                                  "outside the sandbox: only a command that is the test run alone runs there. Next: "
                                  "run `{command} 2>&1 | tail -15` as its own call, and the other steps before or "
                                  "after it.",
    "run.launcher.compound_tool": "`{tool}` cannot run inside the sandbox (it writes its SDK's cache), so among other "
                                  "commands it fails and its silence says nothing about your code. Next: run `{tool} "
                                  "<files>` as its own call; it then runs outside the sandbox, as the platform's own "
                                  "style check does.",
    "run.launcher.style_tools": "The platform checks the code style with these commands in `{folder}`; run them "
                                "the same way, each as its own call (they then run where the platform's do):",
    "run.launcher.code_map": "Where this app's files are (tracked files; read what you need, no need to list the "
                             "tree again):",
    "run.launcher.pipeline_red": "The CI pipeline's red result on this change:\n\n{summary}",
    "run.launcher.env_missing": "{file} does not exist: declare this story's test commands there (the format of "
                                "coding_setup.environment: test, system_test, setup, check, lint, path, browser); "
                                "the pipeline runs exactly those in {folder}/.",
    "run.launcher.env_setup_failed": "the setup of {file} failed in {folder}/:",
    "run.launcher.env_invalid": "{file} is not a valid environment file; nothing ran:",
    "run.launcher.wrapper_denied": "`octryx-claude test-run` is the launcher's own form of a test run. Next: run the "
    "test command itself (pytest, python -m pytest, the declared command), piped into tail or grep as you like.",
    "run.launcher.plain_form": 'A test run whose output goes to a file (`>`, `tee`) runs inside the sandbox, where '
                               'the browser cannot start. Next: run `{plain}` instead, without redirecting to a '
                               'file; pipe into tail or grep if you need less output.',
    "run.launcher.fail_closed": 'Octryx could not confirm this tool call{codes}; it is denied (fail closed). Next: '
                                'ask the user to check `octryx-claude status`.',
    "run.launcher.proof_unavailable": 'Octryx could not prove this confirmation (hook_signer_unavailable). Next: ask '
                                      'the user to restart octryx-claude, then confirm again.',
    "run.launcher.takeover_denied": 'A takeover is confirmed or declined by a person in the Octryx UI (Agents → '
                                    'Claims and handoffs), never by an agent. Next: tell the person and go on with '
                                    'your own work.',
    "run.launcher.patch_format": "Write files with apply_patch in the shell, exactly this form (one call per change, "
    "paths relative to the repository):\napply_patch <<'PATCH'\n*** Begin Patch\n*** Add File: docs/NEW.md\n+first "
    "line\n+second line\n*** Update File: src/app.py\n@@\n-old line\n+new line\n*** End Patch\nPATCH\nEvery line of "
    "an added file starts with '+'. No JSON, no other markers (only Add File, Update File, Delete File).",
    "run.launcher.sandbox_browser": 'This cannot run here: Chromium cannot start inside this sandbox, and waiting or '
                                    'retrying does not change that, so do not schedule a wakeup for it. Next: take a '
                                    'screenshot with `python -m playwright screenshot --viewport-size 1280,800 '
                                    'http://127.0.0.1:<port>/ <file inside the repository>` (it runs outside the '
                                    'sandbox, loopback URLs only; start the app first), or skip the visual check and '
                                    'note it in your summary.',
}
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def text(texts: dict[str, Any] | None, key: str, **values: object) -> str:
    """``key`` from the contract's ``prompt_texts`` (else the fallback) with its placeholders filled."""
    body = str(dict(texts or {}).get(key) or FALLBACK_TEXTS[key])
    return _PLACEHOLDER.sub(lambda match: str(values.get(match.group(1), match.group(0))), body)


def file_summary(account: dict[str, Any] | None, texts: dict[str, Any] | None = None) -> str:
    """Why the repository's environment file ran nothing (missing, invalid, its setup failed); ``""`` when it ran."""
    if not account or account.get("state") == "ok":
        return ""
    file, folder = account.get("file"), account.get("app_folder")
    key = {"missing": "run.launcher.env_missing", "setup_failed": "run.launcher.env_setup_failed"}.get(
        str(account.get("state")), "run.launcher.env_invalid")
    lines = text(texts, key, file=file, folder=folder)
    details = [f"- {error}" for error in account.get("errors") or []]
    failed = [item for item in account.get("setup") or [] if item.get("exit_code") != 0]
    details += [f"$ {item['command']}  (exit {item.get('exit_code')})\n{str(item.get('output_tail') or '').rstrip()}"
                for item in failed[-1:]]
    return "\n".join([lines, *details])


def red_summary(results: list[dict[str, Any]]) -> str:
    """What the session needs to fix a red pipeline, for its resume prompt: per red command the failed test ids and the
    last lines of its output; ``""`` when every command is green."""
    parts = []
    for item in results:
        if item.get("exit_code") == 0:
            continue
        if item.get("skipped"):
            parts.append(f"$ {item.get('command')}  ({item['skipped']}; it runs once the checks above are green)")
            continue
        rerun = item.get("rerun") if isinstance(item.get("rerun"), dict) else {}
        tests = item.get("failed_tests") or rerun.get("tests") or []
        lines = str(rerun.get("output_tail") or item.get("output_tail") or "").rstrip().splitlines()[-RED_TAIL_LINES:]
        parts.append(f"$ {item.get('command')}  (exit {item.get('exit_code')})\n"
                     + (f"failed: {', '.join(tests)}\n" if tests else "") + "\n".join(lines))
    return "\n\n".join(parts)


def style_summary(body: Any) -> str:
    """The platform's code style findings on this change from its answer to the report (``""`` without any).

    A pipeline that is red only on the code style has no failed command to name, so the findings themselves go into
    the agent's prompt."""
    phase = dict(dict(dict(body or {}).get("workflow_run") or {}).get("phase") or {})
    errors = [str(error) for error in dict(phase.get("pipeline_failure") or {}).get("code_style_errors") or []]
    return "\n".join(f"- {error}" for error in errors)
