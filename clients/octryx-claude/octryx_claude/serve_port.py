"""A free loopback port per hands-on pass, so parallel runs on one device never fight over the declared port.

With the environment file's fixed port, two runs at the same time would wait for each other's lock, and a server
another run (or a person) left on that port makes the hands-on test refuse "something else already answers". When
the serve command names its URL's port literally, the pass serves on a free port instead (the command and the URL
rewritten, ``PORT`` set as well); a
command that does not name the port keeps the declared URL, since the app picks its port itself then.
"""

from __future__ import annotations

import re
import socket
import urllib.parse
from typing import Any


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def on_free_port(serve: dict[str, Any], env: dict[str, str], *,
                 pick: Any = free_port) -> tuple[dict[str, Any], dict[str, str]]:
    """``(serve, env)`` for this pass: moved to a free port when the command names the declared one."""
    parsed = urllib.parse.urlsplit(str(serve.get("url") or ""))
    declared = parsed.port
    named = re.compile(rf"(?<!\d){declared}(?!\d)") if declared else None
    if named is None or not named.search(str(serve.get("command") or "")):
        return serve, env
    port = pick()
    url = urllib.parse.urlunsplit(parsed._replace(netloc=f"{parsed.hostname}:{port}"))
    command = named.sub(str(port), str(serve["command"]))
    return {**serve, "command": command, "url": url, "declared_url": serve["url"]}, {**env, "PORT": str(port)}


__all__ = ["free_port", "on_free_port"]
