from __future__ import annotations

from typing import Any


def clamp_config_int(
    config: dict[str, Any],
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw_value = config.get(key) if isinstance(config, dict) else None
    return max(minimum, min(int(raw_value or default), maximum))


def build_truncated_excerpt(text: str, *, max_chars: int) -> str:
    excerpt = str(text or "")[:max_chars].strip()
    if len(str(text or "")) > max_chars:
        excerpt = excerpt.rstrip() + "..."
    return excerpt
