"""What an image plugin brings and may do, in a few plain lines for the Workspace's plugin list (no review, a short
readable list)."""

from __future__ import annotations

from typing import Any

MAX_LINES = 5


def _line(key: str, text: str, **params: Any) -> dict[str, Any]:
    return {"key": f"plugins.summary.{key}", "text": text, "params": params}


def _count(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def summary(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    contributes = manifest.get("contributes") or {}
    permissions = manifest.get("permissions") or {}
    lines = []
    brought = [(len(contributes.get("skills") or []), "skill"), (len(contributes.get("workflows") or []), "workflow"),
               (len(contributes.get("roles") or []), "role")]
    parts = [_count(n, word) for n, word in brought if n]
    if parts:
        lines.append(_line("brings", "Brings " + ", ".join(parts), skills=brought[0][0], workflows=brought[1][0],
                           roles=brought[2][0]))
    pages = [str(page.get("title") or page.get("id")) for page in (contributes.get("ui") or {}).get("pages") or []]
    if pages:
        lines.append(_line("pages", "Adds pages: " + ", ".join(pages), pages=pages))
    used = [str(kind) for kind in permissions.get("connections") or []]
    if used:
        lines.append(_line("uses", "Uses " + ", ".join(used) + " of this Workspace", connections=used))
    writes = [str(kind) for kind in permissions.get("writes") or []]
    if writes:
        lines.append(_line("writes", "Writes to " + ", ".join(writes) + ", asks every time", writes=writes))
    hosts = [str(host) for host in permissions.get("egress") or []]
    if hosts:
        lines.append(_line("connects", "Connects to " + ", ".join(hosts), hosts=hosts))
    return lines[:MAX_LINES]


def needs_settings(schema: dict[str, Any] | None, row) -> bool:
    if not (schema or {}).get("required"):
        return False
    return row is None or getattr(row, "settings_json", None) is None


__all__ = ["needs_settings", "summary"]
