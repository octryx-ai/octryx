"""A free loopback port per hands-on pass, so parallel runs on one device never fight over the declared port."""

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
