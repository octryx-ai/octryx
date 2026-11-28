"""Runs the launcher's PreToolUse hook for Codex: a call runs only on the hook's explicit allow, anything else blocks.
Standard library only; it runs with ``python -I``."""

from __future__ import annotations

import json
import os
import subprocess
import sys

BLOCK = 2
MAX_REASON_CHARS = 2000
GUARDED_ENV = "OCTRYX_CODEX_GUARDED"
PROBE = "--probe"
REFUSED = "Octryx policy denied this tool call (the policy hook gave no valid decision)."


def block(reason: str) -> None:
    sys.stderr.write(reason[:MAX_REASON_CHARS].strip() + "\n")
    sys.stderr.flush()
    sys.exit(BLOCK)


def answer(returncode: int, stdout: bytes) -> tuple[int, str, str]:
    # Codex 0.169 lets the call run when a hook times out, fails, exits otherwise or prints output it cannot parse;
    # it always blocks on exit 2 with a reason on stderr. The hook's own stderr is never passed on.
    refused = (BLOCK, "", REFUSED)
    if returncode != 0:
        return refused
    try:
        output = json.loads(stdout or b"null")
    except ValueError:
        return refused
    specific = output.get("hookSpecificOutput") if isinstance(output, dict) else None
    decision = specific.get("permissionDecision") if isinstance(specific, dict) else None
    if decision == "deny":
        reason = specific.get("permissionDecisionReason")
        reason = reason.strip() if isinstance(reason, str) else ""
        return BLOCK, "", reason[:MAX_REASON_CHARS] if reason else REFUSED
    if decision != "allow" or specific.get("hookEventName") not in (None, "PreToolUse"):
        return refused
    updated, context = specific.get("updatedInput"), specific.get("additionalContext")
    if updated is not None and not isinstance(updated, dict):
        return refused
    # Codex takes allow only together with updatedInput; a plain allow is answered by no decision at all.
    shown: dict = {"hookEventName": "PreToolUse"}
    if updated is not None:
        shown.update(permissionDecision="allow", updatedInput=updated)
    if isinstance(context, str) and context.strip():
        shown["additionalContext"] = context
    return 0, (json.dumps({"hookSpecificOutput": shown}) if len(shown) > 1 else ""), ""


def main(argv: list[str]) -> None:
    if argv[:1] == [PROBE]:
        command = argv[1:]
        sys.exit(0 if command and os.access(command[0], os.X_OK) else 1)
    deadline, command = float(argv[0]), argv[1:]
    hook_input = sys.stdin.buffer.read()
    try:
        done = subprocess.run(command, input=hook_input, capture_output=True, timeout=deadline, check=False,
                              env={**os.environ, GUARDED_ENV: "1"})
    except subprocess.TimeoutExpired:
        block("Octryx policy denied this tool call (the policy hook did not answer in time).")
    except Exception:  # noqa: BLE001 - a hook that cannot run decides nothing: block
        block("Octryx policy denied this tool call (the policy hook could not run).")
    code, stdout, stderr = answer(done.returncode, done.stdout)
    if code == BLOCK:
        block(stderr)
    sys.stdout.write(stdout)
    sys.stdout.flush()


if __name__ == "__main__":
    main(sys.argv[1:])
