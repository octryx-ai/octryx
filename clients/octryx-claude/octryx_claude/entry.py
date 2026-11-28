"""Console entry point of the installed package (``octryx-claude`` in the venv).
Native Windows is refused: Claude Code's Bash sandbox does not exist there, so no governed session could start."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence

from . import hook_timings  # first: its clock starts with the process

# Commands Claude Code runs itself: their output is machine-read, they must stay fast and silent.
MACHINE_COMMANDS = ("api-key-helper", "mcp-headers", "hook")
NATIVE_WINDOWS_REFUSAL = (
    "octryx-claude: needs_configuration: native_windows_unsupported (Claude Code's sandbox, required for "
    "governed sessions, runs only in WSL2 on Windows; install with install.ps1, which sets up WSL2)\n"
)


def native_windows(os_name: str | None = None) -> bool:
    return (os_name or os.name) == "nt"


def wants_update_notice(argv: Sequence[str]) -> bool:
    return not (argv and argv[0] in MACHINE_COMMANDS)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["test-run"]:
        # A run phase's test run outside Claude Code's sandbox (``local_tests``): no state, no update check.
        from .local_tests import run_wrapped  # noqa: PLC0415

        return run_wrapped(args[1:])
    hook_timings.start_for(args)
    if args[:1] == ["hook"] and args[1:2] in (["pre-tool-use"], ["post-tool-use"]) and len(args) == 2:
        # A session that decides on the device (``local_decisions``): answered before the CLI is imported.
        import io  # noqa: PLC0415

        raw = sys.stdin.buffer.read()
        try:
            from .local_decisions import fast_hook  # noqa: PLC0415

            if fast_hook(args[1], raw):
                hook_timings.mark("fast_hook")
                return 0
        except Exception:  # noqa: BLE001 - the full hook decides
            pass
        sys.stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8")
    if native_windows():
        sys.stderr.write(NATIVE_WINDOWS_REFUSAL)
        return 2
    # Imported here: ``state`` needs fcntl, which native Windows lacks.
    from . import cli, self_update  # noqa: PLC0415

    if wants_update_notice(args):
        self_update.on_start(args, sys.stderr)
    return cli.main(args)
