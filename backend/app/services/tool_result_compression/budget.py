from __future__ import annotations

from typing import Any

from .diagram_budget import enforce_diagram_compact_result_budget, has_diagram_brief
from .support import _estimate_tokens

DEFAULT_COMPACT_RESULT_TOKEN_BUDGET = 3000
DEFAULT_COMPACT_RESULT_STRING_CHARS = 4000
DEFAULT_COMPACT_RESULT_LIST_ITEMS = 25
DEFAULT_COMPACT_RESULT_DICT_KEYS = 40
COMPACT_RESULT_TOKEN_BUDGET_KEY = "_compact_result_token_budget"
MAX_COMPACT_RESULT_TOKEN_BUDGET_OVERRIDE = 50000

_AGGRESSIVE_STRING_CHARS = 1200
_AGGRESSIVE_LIST_ITEMS = 10
_AGGRESSIVE_DICT_KEYS = 20


def _truncate_text(value: str, *, max_chars: int) -> str:
    text = str(value or "")
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return text[: max_chars - 3].rstrip() + "..."


def _preview_value(value: Any, *, max_chars: int = 180, depth: int = 0) -> Any:
    if depth >= 2:
        return _truncate_text(str(value), max_chars=max_chars)
    if isinstance(value, str):
        return _truncate_text(value, max_chars=max_chars)
    if isinstance(value, list):
        return [_preview_value(item, max_chars=max_chars, depth=depth + 1) for item in value[:3]]
    if isinstance(value, dict):
        preview: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 5:
                preview["_truncated_keys"] = len(value) - 5
                break
            preview[str(key)] = _preview_value(item, max_chars=max_chars, depth=depth + 1)
        return preview
    return value


def _cap_value(
    value: Any,
    *,
    token_budget: int,
    max_chars: int,
    max_list_items: int,
    max_dict_keys: int,
) -> Any:
    if _estimate_tokens(value) <= token_budget:
        return value
    if isinstance(value, str):
        return _truncate_text(value, max_chars=max_chars)
    if isinstance(value, list):
        items = [
            _cap_value(
                item,
                token_budget=token_budget,
                max_chars=max_chars,
                max_list_items=max_list_items,
                max_dict_keys=max_dict_keys,
            )
            for item in value[:max_list_items]
        ]
        if len(value) > max_list_items:
            return {
                "_hard_capped": True,
                "_original_type": "list",
                "item_count": len(value),
                "items": items,
                "omitted_count": len(value) - len(items),
            }
        return items
    if isinstance(value, dict):
        items = list(value.items())
        capped: dict[str, Any] = {}
        for key, item in items[:max_dict_keys]:
            capped[str(key)] = _cap_value(
                item,
                token_budget=token_budget,
                max_chars=max_chars,
                max_list_items=max_list_items,
                max_dict_keys=max_dict_keys,
            )
        if len(items) > max_dict_keys:
            capped["_truncated_keys"] = len(items) - max_dict_keys
        capped["_hard_capped"] = True
        return capped
    return value


def _summarize_over_budget(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            "_hard_capped": True,
            "_original_type": "dict",
            "estimated_tokens": _estimate_tokens(value),
            "keys": [str(key) for key in list(value.keys())[:12]],
            "preview": _preview_value(value),
        }
    if isinstance(value, list):
        return {
            "_hard_capped": True,
            "_original_type": "list",
            "estimated_tokens": _estimate_tokens(value),
            "item_count": len(value),
            "items": _preview_value(value),
        }
    return {
        "_hard_capped": True,
        "_original_type": type(value).__name__,
        "estimated_tokens": _estimate_tokens(value),
        "value": _preview_value(value),
    }


def enforce_compact_result_budget(
    value: Any,
    *,
    token_budget: int = DEFAULT_COMPACT_RESULT_TOKEN_BUDGET,
) -> Any:
    if _estimate_tokens(value) <= token_budget:
        return value

    if has_diagram_brief(value):
        # Diagram-path results must never degrade to a brief-less stub: the
        # evidence-backed diagram pipeline requires ``diagram_brief`` in the
        # turn history. Shrink the selection deterministically instead.
        return enforce_diagram_compact_result_budget(value, token_budget=token_budget)

    candidate = _cap_value(
        value,
        token_budget=token_budget,
        max_chars=DEFAULT_COMPACT_RESULT_STRING_CHARS,
        max_list_items=DEFAULT_COMPACT_RESULT_LIST_ITEMS,
        max_dict_keys=DEFAULT_COMPACT_RESULT_DICT_KEYS,
    )
    if _estimate_tokens(candidate) <= token_budget:
        return candidate

    candidate = _cap_value(
        candidate,
        token_budget=token_budget,
        max_chars=_AGGRESSIVE_STRING_CHARS,
        max_list_items=_AGGRESSIVE_LIST_ITEMS,
        max_dict_keys=_AGGRESSIVE_DICT_KEYS,
    )
    if _estimate_tokens(candidate) <= token_budget:
        return candidate

    summary = _summarize_over_budget(value)
    if _estimate_tokens(summary) <= token_budget:
        return summary

    summary["preview"] = _preview_value(value, max_chars=96)
    if _estimate_tokens(summary) <= token_budget:
        return summary

    return {
        "_hard_capped": True,
        "_original_type": type(value).__name__,
        "estimated_tokens": _estimate_tokens(value),
    }


def compact_result_token_budget(value: Any, *, default: int) -> int:
    if not isinstance(value, dict):
        return default
    raw_value = value.get(COMPACT_RESULT_TOKEN_BUDGET_KEY)
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return default
    return max(default, min(parsed, MAX_COMPACT_RESULT_TOKEN_BUDGET_OVERRIDE))


def strip_compact_result_budget_hint(value: Any) -> Any:
    if not isinstance(value, dict) or COMPACT_RESULT_TOKEN_BUDGET_KEY not in value:
        return value
    stripped = dict(value)
    stripped.pop(COMPACT_RESULT_TOKEN_BUDGET_KEY, None)
    return stripped
