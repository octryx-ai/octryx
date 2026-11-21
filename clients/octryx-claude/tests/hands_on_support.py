"""Shared helpers for the test_hands_on_* modules."""

from __future__ import annotations

import json
import shutil
import socket
from pathlib import Path

import pytest

APP = """<!doctype html><html><head><meta charset="utf-8"><title>Beans</title></head><body><div id="app"></div>
<script>
const memory = {};
const flags = %s;
function render() {
  const app = document.getElementById('app');
  if (!flags.getItem('onboarded')) {
    app.innerHTML = '<h1>Welcome to Beans</h1><button id="skip">Skip</button>';
    document.getElementById('skip').onclick = () => { flags.setItem('onboarded', '1'); render(); };
    return;
  }
  const beans = JSON.parse(localStorage.getItem('beans') || '[]');
  app.innerHTML = '<h1>My beans</h1>' + (beans.length ? beans.map(b => '<p>' + b + '</p>').join('')
      : '<p>No beans yet</p>') + '<label>Bean name <input id="name"></label><button id="add">Add bean</button>'
      + '<p id="error"></p>';
  document.getElementById('add').onclick = () => {
    const name = document.getElementById('name').value.trim();
    if (!name) { document.getElementById('error').textContent = 'Name is required'; return; }
    localStorage.setItem('beans', JSON.stringify([...beans, name])); render();
  };
}
render();
</script></body></html>"""


PERSISTED = "localStorage"


IN_MEMORY = "{getItem: k => memory[k], setItem: (k, v) => { memory[k] = v; }}"


SCENARIOS = [
    {"id": "S1", "part": "feature", "title": "Onboarding on the first start, not again after a reload",
     "fresh_profile": True, "seed": [], "viewport": {"width": 390, "height": 844}, "covers": [],
     "steps": [{"do": "goto", "path": "/"}, {"do": "expect_text", "text": "Welcome to Beans"},
               {"do": "click", "text": "Skip"}, {"do": "expect_text", "text": "No beans yet"}, {"do": "reload"},
               {"do": "expect_no_text", "text": "Welcome to Beans"}]},
    {"id": "S2", "part": "regression", "title": "A bean stays after a restart", "fresh_profile": False,
     "seed": [{"do": "goto", "path": "/"}, {"do": "click", "text": "Skip"},
              {"do": "fill", "label": "Bean name", "value": "Bohne 1"}, {"do": "click", "text": "Add bean"}],
     "viewport": {"width": 1280, "height": 800}, "covers": ["persistence_reload"],
     "steps": [{"do": "goto", "path": "/"}, {"do": "expect_text", "text": "Bohne 1"},
               {"do": "screenshot", "name": "beans"}]},
]


def _port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _repo(tmp_path: Path, flags: str, *, serve: bool = True, ui: bool = True) -> Path:
    root = tmp_path / "repo"
    app = root / "web"
    app.mkdir(parents=True)
    (app / "index.html").write_text(APP % flags)
    port = _port()
    environment = {"test": "true", **({"browser": "chrome"} if ui else {}),
                   **({"serve": {"command": f"python3 -m http.server {port} --bind 127.0.0.1",
                                 "url": f"http://127.0.0.1:{port}/", "ready_seconds": 30}} if serve else {})}
    (app / ".octryx").mkdir()
    (app / ".octryx/environment.json").write_text(json.dumps(environment))
    return root


def _view() -> dict:
    return {"node_id": "hands_on", "entry": 1, "scenarios": SCENARIOS,
            "environment_file": {"file": "web/.octryx/environment.json", "app_folder": "web"}}


def _why(body: dict, shots: Path) -> str:
    """Each failed scenario in full (the gate cut the body; a red run shows its cause)."""
    failed = [{key: item.get(key) for key in ("id", "failed_step", "error", "invalid", "screenshots", "seconds")}
              for item in body.get("scenarios") or [] if not item.get("passed")]
    files = sorted(path.name for path in Path(shots).iterdir()) if shots and Path(shots).is_dir() else []
    return json.dumps({"failed": failed, "serve_end": body.get("serve_end"), "shots": str(shots), "files": files},
                      indent=1, default=str)


needs_chrome = pytest.mark.skipif(
    not Path("/Applications/Google Chrome.app").exists() and not shutil.which("google-chrome"),
    reason="needs the installed Google Chrome")
