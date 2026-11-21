"""Entry script for bin/octryx-claude.

Running this file puts its directory on ``sys.path``, so the package imports without
touching ``PYTHONPATH`` (which Claude Code and its tools would otherwise inherit).

A tool hook of a session that decides on the device (``local_decisions``, epic-delivery) is answered before the CLI
and its dependencies are imported: the full import would cost a noticeable fraction of a second per tool call.
"""

import io
import sys

from octryx_claude import hook_timings  # first: its clock starts with the process


def _fast_hook(argv):
    if len(argv) != 2 or argv[0] != "hook" or argv[1] not in ("pre-tool-use", "post-tool-use"):
        return None
    raw = sys.stdin.buffer.read()
    try:
        from octryx_claude.local_decisions import fast_hook

        if fast_hook(argv[1], raw):
            hook_timings.mark("fast_hook")
            return 0
    except Exception:  # noqa: BLE001 - anything unexpected: the full hook decides
        pass
    sys.stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8")
    return None


if __name__ == "__main__":
    hook_timings.start_for(sys.argv[1:])
    handled = _fast_hook(sys.argv[1:])
    if handled is not None:
        sys.exit(handled)
    from octryx_claude.cli import main

    sys.exit(main())
