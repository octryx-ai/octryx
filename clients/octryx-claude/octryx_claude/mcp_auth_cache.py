"""Clears Claude Code's "needs authentication" mark for the platform's MCP server before each session.
Claude Code skips a server that answered 401 for about 15 minutes, but the launcher supplies that auth itself."""

from __future__ import annotations

import json
from pathlib import Path

from .state import write_private_json

CACHE_FILE = "mcp-needs-auth-cache.json"


def _ours(key: str, server: str) -> bool:
    # The reproduced key is the server's name; a scoped form ("<scope>:<name>") is covered as well.
    return key == server or key.endswith(f":{server}")


def clear(config_dir: Path, server: str) -> bool:
    path = Path(config_dir) / CACHE_FILE
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(cache, dict):
        return False
    kept = {key: value for key, value in cache.items() if not _ours(str(key), server)}
    if len(kept) == len(cache):
        return False
    try:
        write_private_json(path, kept)
    except OSError:
        return False
    return True


__all__ = ["CACHE_FILE", "clear"]
