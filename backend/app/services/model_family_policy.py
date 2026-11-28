from __future__ import annotations

PREMIUM_REASONING_MODEL_FAMILIES: tuple[str, ...] = (
    "sonnet",
    "opus",
)
FAST_REASONING_MODEL_FAMILIES: tuple[str, ...] = (
    "haiku",
    "flash",
)
HAIKU_MODEL_FAMILIES: tuple[str, ...] = ("haiku",)
# The lite/micro Nova tiers answer coding turns with text instead of tool calls. This is the seed; the live list
# is admin data (``policy_lists.weak_model_families``).
WEAK_CODING_MODEL_FAMILIES: tuple[str, ...] = (
    "haiku",
    "flash",
    "gpt-3.5",
    "gemma",
    "nova-lite",
    "nova-2-lite",
    "nova-micro",
)


def normalize_model_family_name(model_id: str) -> str:
    return str(model_id or "").strip().lower()


def model_matches_any_family(model_id: str, *families: str) -> bool:
    normalized_model = normalize_model_family_name(model_id)
    if not normalized_model:
        return False
    return any(str(family).strip().lower() in normalized_model for family in families if str(family).strip())


def is_weak_coding_model_family(model_id: str) -> bool:
    from .policy_lists.live import live_policy_lists

    return model_matches_any_family(model_id, *live_policy_lists().weak_coding_model_families)
