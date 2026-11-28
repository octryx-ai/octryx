"""Who holds the hands-on test's serve port, so a refusal can name the process."""

from __future__ import annotations

import subprocess
from urllib.parse import urlparse

LSOF_TIMEOUT = 5


def holder(url: str) -> str:
    parsed = urlparse(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        done = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fpc"], capture_output=True,
                              text=True, timeout=LSOF_TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    pid = command = ""
    for line in done.stdout.splitlines():
        if line.startswith("p") and not pid:
            pid = line[1:]
        elif line.startswith("c") and not command:
            command = line[1:]
    return f"port {port} is used by {command} (pid {pid})" if pid and command else ""


__all__ = ["holder"]
