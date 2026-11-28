"""macOS notifications under octryx's own name, via a tiny applet (``osascript`` notifications show as
"Script Editor")."""

from __future__ import annotations

import contextlib
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

from .state import default_root

APP_NAME = "Octryx.app"
BUNDLE_ID = "ai.octryx.notify"
QUEUE = "notify-queue"
VERSION = "2"  # bump when the applet's script changes: an older applet is rebuilt
MAX_TITLE = 80
MAX_MESSAGE = 240

APPLET_SCRIPT = """on run
  set q to "{queue}"
  set names to paragraphs of (do shell script "ls -1 " & quoted form of q & " 2>/dev/null || true")
  repeat with n in names
    set n to n as text
    if n ends with ".msg" then
      set p to q & "/" & n
      set body to do shell script "cat " & quoted form of p without altering line endings
      do shell script "rm -f " & quoted form of p
      set AppleScript's text item delimiters to (ASCII character 10)
      set parts to text items of body
      set AppleScript's text item delimiters to ""
      if (count of parts) > 1 then
        display notification (item 2 of parts) with title (item 1 of parts)
      else
        display notification body with title "Octryx"
      end if
    end if
  end repeat
end run
"""


def _clean(text: str, limit: int) -> str:
    flat = " ".join("".join(ch if ch.isprintable() else " " for ch in str(text)).split())
    return flat[:limit]


def applet_path(root: Path | None = None) -> Path:
    return (root or default_root()) / APP_NAME


def queue_dir(root: Path | None = None) -> Path:
    return (root or default_root()) / QUEUE


def ensure_applet(root: Path | None = None, *, run: object = subprocess.run) -> Path | None:
    if sys.platform != "darwin":
        return None
    app = applet_path(root)
    marker = app / "Contents" / "Resources" / "octryx-notify-version"
    if marker.is_file() and marker.read_text(encoding="utf-8").strip() == VERSION:
        return app
    queue = queue_dir(root)
    try:
        queue.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(queue, 0o700)
        source = APPLET_SCRIPT.replace("{queue}", str(queue).replace("\\", "\\\\").replace('"', '\\"'))
        script = app.parent / "octryx-notify.applescript"
        script.write_text(source, encoding="utf-8")
        built = run(["osacompile", "-o", str(app), str(script)], check=False, timeout=30, capture_output=True)
        if getattr(built, "returncode", 1) != 0:
            return None
        plist = str(app / "Contents" / "Info.plist")
        for key, kind, value in (("CFBundleIdentifier", "-string", BUNDLE_ID), ("CFBundleName", "-string", "Octryx"),
                                 ("LSUIElement", "-bool", "true")):
            run(["plutil", "-replace", key, kind, value, plist], check=False, timeout=10, capture_output=True)
        # The plist edits void osacompile's ad-hoc signature: sign it again so macOS starts it without asking.
        run(["codesign", "--force", "--sign", "-", str(app)], check=False, timeout=30, capture_output=True)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(VERSION, encoding="utf-8")
        return app
    except (OSError, subprocess.SubprocessError):
        return None


def notify(title: str, message: str, *, root: Path | None = None, run: object = subprocess.run) -> None:
    if sys.platform != "darwin":
        return
    title, message = _clean(title, MAX_TITLE) or "Octryx", _clean(message, MAX_MESSAGE)
    if not message:
        return
    with contextlib.suppress(Exception):
        app = ensure_applet(root, run=run)
        if app is not None:
            name = f"{time.time_ns()}-{secrets.token_hex(4)}.msg"
            path = queue_dir(root) / name
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(f"{title}\n{message}")
            run(["open", "-g", "-j", str(app)], check=False, timeout=10, capture_output=True)
            return
        quoted = lambda text: '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'  # noqa: E731
        run(["osascript", "-e", f"display notification {quoted(message)} with title {quoted(title)}"],
            check=False, timeout=5, capture_output=True)


__all__ = ["APP_NAME", "BUNDLE_ID", "ensure_applet", "notify"]
