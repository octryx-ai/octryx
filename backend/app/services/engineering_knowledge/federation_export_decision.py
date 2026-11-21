"""Redaction and export decisions for federated knowledge facts."""

from __future__ import annotations

import re
from typing import Any

from app.services.data_classification.pii import detect_and_redact_pii

from .federation_export_labels import (
    ALWAYS_BLOCKED_LABELS,
    EXPORT_LABEL_INTERNAL,
    EXPORT_LABEL_PERSONAL_DATA,
    EXPORT_LABEL_PUBLIC,
    JIRA_KEY_PATTERN,
    REPOSITORY_PATH_PATTERN,
    REVIEW_REQUIRED_LABELS,
    SECRET_VALUE_PATTERNS,
    UNSAFE_KEY_PARTS,
    URL_PATTERN,
)


def _redact_fact(fact: dict[str, Any], *, policy: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    redacted, pii_types, pii_paths = detect_and_redact_pii(fact)
    labels = {EXPORT_LABEL_PERSONAL_DATA} if pii_types else set()
    paths = list(pii_paths)
    types = [f"pii:{item}" for item in pii_types]
    redacted, extra_paths, extra_types = _redact_text_patterns(redacted, policy=policy)
    paths.extend(extra_paths)
    types.extend(extra_types)
    return redacted, {"labels": labels, "paths": sorted(set(paths)), "types": sorted(set(types))}


def _redact_text_patterns(value: Any, *, policy: dict[str, Any], path: str = "") -> tuple[Any, list[str], list[str]]:
    paths: list[str] = []
    types: list[str] = []
    if isinstance(value, str):
        result = value
        replacements: list[tuple[bool, re.Pattern[str] | None, str, str]] = [
            (policy["redact_jira_keys"], JIRA_KEY_PATTERN, "[JIRA_KEY]", "jira_key"),
            (policy["redact_urls"], URL_PATTERN, "[URL]", "url"),
            (policy["redact_repository_paths"], REPOSITORY_PATH_PATTERN, "[REPOSITORY_PATH]", "repository_path"),
        ]
        for enabled, pattern, replacement, redaction_type in replacements:
            if enabled and pattern and pattern.search(result):
                result = pattern.sub(replacement, result)
                paths.append(path)
                types.append(redaction_type)
        for term in [*policy["customer_terms"], *policy["username_terms"]]:
            if term and term in result.lower():
                result = re.sub(re.escape(term), "[TERM]", result, flags=re.IGNORECASE)
                paths.append(path)
                types.append("term")
        return result, paths, types
    if isinstance(value, dict):
        processed = {}
        for key, item in value.items():
            next_path = f"{path}.{key}" if path else str(key)
            processed_item, item_paths, item_types = _redact_text_patterns(item, policy=policy, path=next_path)
            processed[key] = processed_item
            paths.extend(item_paths)
            types.extend(item_types)
        return processed, paths, types
    if isinstance(value, list):
        processed_list = []
        for index, item in enumerate(value):
            processed_item, item_paths, item_types = _redact_text_patterns(item, policy=policy, path=f"{path}[{index}]")
            processed_list.append(processed_item)
            paths.extend(item_paths)
            types.extend(item_types)
        return processed_list, paths, types
    return value, paths, types


def _decision_action(
    *,
    labels: set[str],
    unsafe_paths: list[str],
    secret_paths: list[str],
    policy: dict[str, Any],
) -> str:
    if unsafe_paths or secret_paths or labels.intersection(ALWAYS_BLOCKED_LABELS):
        return "blocked"
    needs_review = labels.intersection(REVIEW_REQUIRED_LABELS) - policy["allowed_labels"]
    if needs_review:
        if not labels.issubset(policy["allowed_labels"] | policy["allow_with_review"]):
            return "blocked"
        if not _review_is_approved(policy):
            return "requires_review"
    if EXPORT_LABEL_PERSONAL_DATA in labels or labels.intersection(REVIEW_REQUIRED_LABELS):
        return "redacted"
    if not labels.issubset(policy["allowed_labels"] | policy["allow_with_review"]):
        return "blocked"
    return "exportable"


def _decision_reasons(
    *,
    labels: set[str],
    unsafe_paths: list[str],
    secret_paths: list[str],
    policy: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if unsafe_paths:
        reasons.append(f"Blocked unsafe raw fields: {', '.join(unsafe_paths[:5])}")
    if secret_paths:
        reasons.append(f"Blocked secret-looking values: {', '.join(secret_paths[:5])}")
    if labels.intersection(ALWAYS_BLOCKED_LABELS):
        reasons.append("Blocked by secret or non-exportable classification")
    needs_review = labels.intersection(REVIEW_REQUIRED_LABELS) - policy["allowed_labels"]
    if needs_review and not _review_is_approved(policy):
        reasons.append(f"Human review required for {', '.join(sorted(needs_review))}")
    if needs_review and _review_is_approved(policy):
        reasons.append(f"Reviewer approval accepted for {', '.join(sorted(needs_review))}")
    if EXPORT_LABEL_PERSONAL_DATA in labels:
        reasons.append("Personal data detected and redacted")
    if not reasons:
        reasons.append("Allowed by federation export policy")
    return reasons


def _review_is_approved(policy: dict[str, Any]) -> bool:
    return bool(policy["review_approved"] and policy["reviewer_role"] in policy["reviewer_roles"])


def _export_classification(labels: set[str]) -> str:
    return EXPORT_LABEL_PUBLIC if labels == {EXPORT_LABEL_PUBLIC} else EXPORT_LABEL_INTERNAL


def _unsafe_paths(value: Any, *, path: str = "fact") -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key).strip().lower()
            if any(part in key_text for part in UNSAFE_KEY_PARTS):
                paths.append(f"{path}.{key}")
            paths.extend(_unsafe_paths(item, path=f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            paths.extend(_unsafe_paths(item, path=f"{path}[{index}]"))
    return paths


def _secret_value_paths(value: Any, *, path: str = "fact") -> list[str]:
    paths: list[str] = []
    if isinstance(value, str):
        if any(pattern.search(value) for pattern in SECRET_VALUE_PATTERNS.values()):
            paths.append(path)
    elif isinstance(value, dict):
        for key, item in value.items():
            paths.extend(_secret_value_paths(item, path=f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            paths.extend(_secret_value_paths(item, path=f"{path}[{index}]"))
    return paths

