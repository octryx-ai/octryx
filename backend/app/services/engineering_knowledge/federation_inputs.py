"""Validation of free-form federation feed input."""

from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException


def _required_text(value: Any, label: str, *, max_len: int = 500) -> str:
    text = str(value or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail=f"{label} is required")
    if len(text) > max_len:
        raise HTTPException(status_code=400, detail=f"{label} is too long")
    return text


def _optional_text(value: Any, *, max_len: int) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) > max_len:
        raise HTTPException(status_code=400, detail="Value is too long")
    return text


def _safe_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=True)
    for blocked in ("password", "secret", "token", "private_key", "raw_log", "raw_payload"):
        if blocked in encoded.lower():
            raise HTTPException(status_code=400, detail="Feed policy contains unsafe secret or raw payload fields")
    return dict(value)


def _enum(value: Any, allowed: set[str], label: str) -> str:
    text = str(value or "").strip().lower()
    if text not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported {label}: {text}")
    return text
