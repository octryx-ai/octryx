"""The platform's MCP server never waits out Claude Code's "needs authentication" mark.

Claude Code remembers a server that answered 401 in ``<CLAUDE_CONFIG_DIR>/mcp-needs-auth-cache.json``
(``{"<server>": {"timestamp": <ms>}}``, reproduced with Claude Code 2.1.318) and skips it for about 15 minutes. The
launcher supplies the platform server's authentication itself (``mcp-headers``), so a mark left by one broken turn
(a device turn with a broken hook) cost every following turn its platform tools (acceptance 2,
09:27-09:45). Before each session the launcher removes the mark for its own server from its own config folder; other
servers' marks stay, and a file it cannot read stays as it is.
"""

from __future__ import annotations

import json
from pathlib import Path

from .state import write_private_json

CACHE_FILE = "mcp-needs-auth-cache.json"


def _ours(key: str, server: str) -> bool:
    # The reproduced key is the server's name; a scoped form ("<scope>:<name>") is covered as well.
    return key == server or key.endswith(f":{server}")


def clear(config_dir: Path, server: str) -> bool:
    """Remove ``server``'s mark from ``config_dir``'s cache; True when there was one."""
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
