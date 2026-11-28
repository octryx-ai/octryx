"""A fresh ``python -c`` probe that fails on a hang, not on a slow machine."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path

HEARTBEAT_ENV = "OCTRYX_TEST_PROBE_HEARTBEAT"
STALL_SECONDS = 120.0
POLL_SECONDS = 2.0

_HEARTBEAT = '''
def _octryx_probe_heartbeat():
    import os, sys, threading, time
    path = os.environ.get("OCTRYX_TEST_PROBE_HEARTBEAT")
    if not path:
        return
    main = threading.main_thread().ident

    def beat():
        last = None
        while True:
            frame = sys._current_frames().get(main)
            where = f"{frame.f_code.co_filename}:{frame.f_lineno} modules={len(sys.modules)}" if frame else ""
            if where != last:
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(where)
                last = where
            time.sleep(1)

    threading.Thread(target=beat, daemon=True, name="octryx-probe-heartbeat").start()


_octryx_probe_heartbeat()
del _octryx_probe_heartbeat
'''


def _position(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def run_python_probe(code: str, *args: str, cwd: str | Path | None = None, env: Mapping[str, str] | None = None,
                     stall_seconds: float = STALL_SECONDS) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as directory:
        heartbeat = Path(directory) / "heartbeat"
        environment = dict(os.environ if env is None else env)
        environment[HEARTBEAT_ENV] = str(heartbeat)
        process = subprocess.Popen([sys.executable, "-c", _HEARTBEAT + code, *args], cwd=cwd, env=environment,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        last, moved_at = "", time.monotonic()
        while True:
            try:
                stdout, stderr = process.communicate(timeout=POLL_SECONDS)
                return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                position = _position(heartbeat)
                if position != last:
                    last, moved_at = position, time.monotonic()
                # Before the first heartbeat the interpreter is still starting (site, the venv): three times the
                # allowance, since that start reads the most files from a busy disk.
                elif time.monotonic() - moved_at > stall_seconds * (1 if last else 3):
                    process.kill()
                    _stdout, stderr = process.communicate()
                    raise AssertionError(f"the probe made no progress for {stall_seconds:.0f} s, "
                                         f"stuck at {last or 'its start'}\n{stderr[-3000:]}") from None


_PYTEST_MAIN = "import runpy, sys\nsys.argv[0] = 'pytest'\nrunpy.run_module('pytest', run_name='__main__', alter_sys=True)\n"


def run_pytest_probe(cwd: str | Path, *targets: str) -> subprocess.CompletedProcess[str]:
    environment = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    return run_python_probe(_PYTEST_MAIN, "-rA", "-p", "no:cacheprovider", "-o", "addopts=", *targets, cwd=cwd,
                            env=environment)


__all__ = ["HEARTBEAT_ENV", "STALL_SECONDS", "run_pytest_probe", "run_python_probe"]
