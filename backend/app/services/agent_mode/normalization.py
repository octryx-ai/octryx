from __future__ import annotations

import re

from ...agent.runtime_defaults import DEFAULT_AGENT_MODE_KEY, VALID_CAPABILITY_TYPES


def normalize_agent_mode_key(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    return normalized or DEFAULT_AGENT_MODE_KEY


def normalize_capability_type(value: str | None) -> str:
    capability = str(value or "").strip().lower()
    return capability if capability in VALID_CAPABILITY_TYPES else DEFAULT_AGENT_MODE_KEY
