"""The platform's own secret pass over transcript lines, run when a batch is stored and again when a page is served."""

from __future__ import annotations

import importlib.util
import re
import sys
from functools import cache
from pathlib import Path
from types import ModuleType
from typing import Any

from ..knowledge.memory.session_lessons import redact as redact_secret_shapes
from ..redaction_policy import redact_secret_text

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "transcript_secrets.py"
_EDGE = re.compile(r"^(\s*)(.*?)(\s*)$", re.S)


@cache
def rules() -> ModuleType:
    spec = importlib.util.spec_from_file_location("transcript_secrets", _SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("transcript_secrets_missing")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("transcript_secrets", module)
    spec.loader.exec_module(module)
    return module


def redact_text(text: str) -> str:
    if not text:
        return text
    text = rules().redact_text(text)
    lead, body, trail = _EDGE.match(text).groups()
    return f"{lead}{redact_secret_text(redact_secret_shapes(body))}{trail}"


def _strings(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {key: _strings(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_strings(item) for item in value]
    return value


def redact_entry(value: Any, secret_ids: set[str] | None = None) -> Any:
    return _strings(rules().redact_line(value, secret_ids if secret_ids is not None else set()))


def note_secret_calls(entries: list[Any], secret_ids: set[str]) -> set[str]:
    for entry in entries:
        rules().note_secret_calls(entry, secret_ids)
    return secret_ids


__all__ = ["note_secret_calls", "redact_entry", "redact_text", "rules"]
