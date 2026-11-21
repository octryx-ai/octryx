"""Shared helpers for the test_codex_driver_* modules."""

from __future__ import annotations

import json
import stat
from pathlib import Path
from types import SimpleNamespace


def _prepared(tmp_path: Path, **env: str) -> SimpleNamespace:
    session = tmp_path / "sessions" / "k1"
    session.mkdir(parents=True)
    return SimpleNamespace(
        session_key="k1", model="team-coder", profile="governed", settings_path=session / "settings.json",
        env={"PATH": "/usr/bin:/bin", "OCTRYX_SESSION_KEY": "k1", "OCTRYX_WORKSPACE_ID": "w1",
             "ANTHROPIC_BASE_URL": "https://platform.test/api/v1/model-gateway/anthropic", **env},
        extra={"gateway": {"base_url": "https://platform.test", "session_key": "k1", "workspace_id": "w1",
                           "workflow_run": "run-1"},
               "hook_shim": "/opt/octryx/bin/octryx-claude", "permission_mode": "bypassPermissions"})


def _fake_codex(folder: Path, lines: list[dict], *, version: str = "codex-cli 0.169.0") -> Path:
    """A ``codex`` that prints ``lines`` as ``exec --json`` would and records how it was called."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "lines.json").write_text(json.dumps(lines))
    script = folder / "codex"
    script.write_text(
        "#!/usr/bin/env python3\nimport json, os, sys\n"
        f"HERE = {str(folder)!r}\n"
        f"if sys.argv[1:] == ['--version']:\n    print({version!r})\n    sys.exit(0)\n"
        "with open(os.path.join(HERE, 'argv.json'), 'w') as fh:\n"
        "    json.dump({'argv': sys.argv[1:], 'home': os.environ.get('CODEX_HOME'),\n"
        "               'key': os.environ.get('OPENAI_API_KEY')}, fh)\n"
        "for line in json.load(open(os.path.join(HERE, 'lines.json'))):\n"
        "    print(json.dumps(line), flush=True)\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script
