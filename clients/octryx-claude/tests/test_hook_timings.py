import json
import os
import subprocess
import sys
from pathlib import Path

from octryx_claude.hook_timings import FILE_NAME, MAX_BYTES, HookTimer

ENTRY = Path(__file__).resolve().parents[1] / "octryx_claude_entry.py"


def test_a_hook_process_through_the_shim_entry_logs_its_steps_and_exit(tmp_path):
    env = {**os.environ, "OCTRYX_CLAUDE_HOME": str(tmp_path)}
    for name in ("OCTRYX_SESSION_KEY", "OCTRYX_BASE_URL"):
        env.pop(name, None)
    done = subprocess.run([sys.executable, str(ENTRY), "hook", "stop"], input='{"hook_event_name": "Stop"}',
                          capture_output=True, text=True, timeout=60, env=env, check=False)
    assert done.returncode == 0
    line = json.loads((tmp_path / "logs" / FILE_NAME).read_text().splitlines()[-1])
    assert line["event"] == "stop"
    assert line["steps"]["exit"] >= 0


def test_the_log_moves_aside_when_it_is_full(tmp_path):
    (tmp_path / FILE_NAME).write_text("x" * (MAX_BYTES + 1))
    timer = HookTimer("pre-tool-use", started=0.0, clock=lambda: 1.5)
    timer.mark("decided")
    timer.write(tmp_path)
    assert (tmp_path / f"{FILE_NAME}.1").stat().st_size > MAX_BYTES
    assert json.loads((tmp_path / FILE_NAME).read_text())["steps"] == {"decided": 1.5}
