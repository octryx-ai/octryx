from __future__ import annotations

from typing import Any

DEFAULT_FRAGMENT_CHAR_CAP = 2_400
FRAGMENT_CHAR_CAPS: dict[str, int] = {
    "description": 2_800,
    "understood_request": 2_400,
    "rollback_plan": 1_200,
    "operator_request": 1_200,
    "state_machine": 1_200,
}
ESTIMATED_CHARS_PER_TOKEN = 4


def build_coding_context_budget_snapshot(
    fragments: dict[str, Any],
    *,
    default_char_cap: int = DEFAULT_FRAGMENT_CHAR_CAP,
    fragment_char_caps: dict[str, int] | None = None,
) -> dict[str, Any]:
    caps = {**FRAGMENT_CHAR_CAPS, **(fragment_char_caps or {})}
    fragment_records: dict[str, dict[str, Any]] = {}
    total_original_chars = 0
    total_prompt_chars = 0
    for key, value in fragments.items():
        cap = _positive_int(caps.get(key), default_char_cap)
        original = str(value or "")
        prompt, truncated = _cap_text(original, cap)
        original_chars = len(original)
        prompt_chars = len(prompt)
        total_original_chars += original_chars
        total_prompt_chars += prompt_chars
        fragment_records[key] = {
            "content": prompt,
            "char_cap": cap,
            "original_chars": original_chars,
            "prompt_chars": prompt_chars,
            "estimated_prompt_tokens": _estimate_tokens(prompt_chars),
            "truncated": truncated,
        }
    return {
        "version": "coding_context_budget.v1",
        "default_char_cap": default_char_cap,
        "total_original_chars": total_original_chars,
        "total_prompt_chars": total_prompt_chars,
        "estimated_prompt_tokens": _estimate_tokens(total_prompt_chars),
        "fragments": fragment_records,
    }


def budget_fragment_content(snapshot: dict[str, Any], key: str) -> str:
    fragments = snapshot.get("fragments") if isinstance(snapshot, dict) else {}
    record = fragments.get(key) if isinstance(fragments, dict) else None
    if not isinstance(record, dict):
        return ""
    return str(record.get("content") or "")


def coding_context_budget_metadata(snapshot: dict[str, Any]) -> dict[str, Any]:
    fragments = snapshot.get("fragments") if isinstance(snapshot, dict) else {}
    return {
        key: {field: value for field, value in record.items() if field != "content"}
        for key, record in (fragments or {}).items()
        if isinstance(record, dict)
    }


def _cap_text(value: str, cap: int) -> tuple[str, bool]:
    clean = value.strip()
    if len(clean) <= cap:
        return clean, False
    marker = "\n[... truncated by coding context budget ...]"
    usable = max(0, cap - len(marker))
    return clean[:usable].rstrip() + marker, True


def _estimate_tokens(chars: int) -> int:
    if chars <= 0:
        return 0
    return max(1, (chars + ESTIMATED_CHARS_PER_TOKEN - 1) // ESTIMATED_CHARS_PER_TOKEN)


def _positive_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default
