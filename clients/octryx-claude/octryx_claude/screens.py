"""Screenshots of the last declared system test run, uploaded at Stop of a changing phase for the review.
The server's reviewer cannot read the device; best effort and bounded."""

from __future__ import annotations

import base64
import time
from datetime import UTC
from pathlib import Path
from typing import Any

FOLDER = ("test-reports", "screenshots")
SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
MAX_SCREENS = 200  # a guard against a runaway folder, not a cut
MAX_BYTES = 8_000_000
RECENT_SECONDS = 6 * 3600
CHANGING = ("change", "deliver")
TIMEOUT = 20.0


RUN_FILE = "system_test_run.json"


def _declared(contract: dict[str, Any] | None) -> str:
    phase = (contract or {}).get("phase") if isinstance((contract or {}).get("phase"), dict) else {}
    system = phase.get("system_tests") if isinstance(phase.get("system_tests"), dict) else {}
    return str(system.get("command") or "").strip()


def note_run(session_dir: Path, contract: dict[str, Any] | None, hook_input: dict[str, Any]) -> bool:
    tool_input = hook_input.get("tool_input") if isinstance(hook_input.get("tool_input"), dict) else {}
    command = _declared(contract)
    if hook_input.get("tool_name") != "Bash" or not command or str(tool_input.get("command") or "").strip() != command:
        return False
    import json

    (session_dir / RUN_FILE).write_text(json.dumps({"started": time.time()}))
    return True


def last_run(session_dir: Path) -> float | None:
    import json

    try:
        return float(json.loads((session_dir / RUN_FILE).read_text())["started"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def pending(contract: dict[str, Any] | None, root: Path, *, now: float | None = None,
            since: float | None = None) -> list[Path]:
    phase = (contract or {}).get("phase")
    if not isinstance(phase, dict) or str(phase.get("capability_class") or "") not in CHANGING:
        return []
    folder = root.joinpath(*FOLDER)
    if not folder.is_dir():
        return []
    cutoff = since or _pass_start(contract) or (now or time.time()) - RECENT_SECONDS
    files = [path for path in folder.iterdir()
             if path.is_file() and path.suffix.lower() in SUFFIXES and 0 < path.stat().st_size <= MAX_BYTES
             and path.stat().st_mtime >= cutoff]
    return sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)[:MAX_SCREENS]


CLOCK_SLACK_SECONDS = 120


def _pass_start(contract: dict[str, Any] | None) -> float | None:
    from datetime import datetime

    run = (contract or {}).get("run") if isinstance((contract or {}).get("run"), dict) else {}
    raw = str(run.get("entered_at") or "")
    try:
        entered = datetime.fromisoformat(raw) if raw else None
    except ValueError:
        return None
    if entered is None:
        return None
    entered = entered if entered.tzinfo is not None else entered.replace(tzinfo=UTC)
    return entered.timestamp() - CLOCK_SLACK_SECONDS


def upload(post: Any, contract: dict[str, Any] | None, root: Path, *, since: float | None = None) -> int:
    run = (contract or {}).get("run") if isinstance((contract or {}).get("run"), dict) else {}
    node = run.get("current_node") if isinstance(run.get("current_node"), dict) else {}
    kept = 0
    for path in pending(contract, root, since=since):
        body = {"node_id": node.get("id"), "entry": run.get("entry"), "name": path.name,
                "data": base64.b64encode(path.read_bytes()).decode()}
        result = post(body)
        kept += 1 if getattr(result, "body", None) and result.body.get("state") == "stored" else 0
    return kept


__all__ = ["last_run", "note_run", "pending", "upload"]
