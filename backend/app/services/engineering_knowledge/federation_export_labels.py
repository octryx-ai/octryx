"""Export labels, policy normalisation and label detection for knowledge federation."""

from __future__ import annotations

import re
from typing import Any

EXPORT_LABEL_PUBLIC = "public"
EXPORT_LABEL_INTERNAL = "internal"
EXPORT_LABEL_CONFIDENTIAL = "confidential"
EXPORT_LABEL_CUSTOMER_SPECIFIC = "customer_specific"
EXPORT_LABEL_PERSONAL_DATA = "personal_data"
EXPORT_LABEL_SECRET = "secret"
EXPORT_LABEL_NON_EXPORTABLE = "non_exportable"

FEDERATION_EXPORT_LABELS = {
    EXPORT_LABEL_PUBLIC,
    EXPORT_LABEL_INTERNAL,
    EXPORT_LABEL_CONFIDENTIAL,
    EXPORT_LABEL_CUSTOMER_SPECIFIC,
    EXPORT_LABEL_PERSONAL_DATA,
    EXPORT_LABEL_SECRET,
    EXPORT_LABEL_NON_EXPORTABLE,
}

PACKAGE_EXPORT_CLASSIFICATIONS = {EXPORT_LABEL_PUBLIC, EXPORT_LABEL_INTERNAL}
REVIEW_REQUIRED_LABELS = {EXPORT_LABEL_CONFIDENTIAL, EXPORT_LABEL_CUSTOMER_SPECIFIC}
ALWAYS_BLOCKED_LABELS = {EXPORT_LABEL_SECRET, EXPORT_LABEL_NON_EXPORTABLE}
DEFAULT_REVIEW_ROLES = {"admin", "security", "data_protection", "knowledge_steward"}

JIRA_KEY_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]{1,15}-\d+\b")
URL_PATTERN = re.compile(r"https?://[^\s)>\"]+")
REPOSITORY_PATH_PATTERN = re.compile(
    r"(?<![\w.-])(?:[\w.-]+/){1,8}[\w.-]+\."
    r"(?:java|kt|py|ts|tsx|js|jsx|go|rb|rs|yaml|yml|xml|json|md|sql|sh|properties)\b"
)
SECRET_VALUE_PATTERNS: dict[str, re.Pattern[str]] = {
    "bearer_token": re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private_key": re.compile(r"-----BEGIN\s+(?:RSA\s+|EC\s+|OPENSSH\s+)?PRIVATE KEY-----"),
    "api_token": re.compile(r"\b(?:sk|pk|ghp|glpat)-[A-Za-z0-9_=-]{16,}\b"),
}
UNSAFE_KEY_PARTS = {
    "access_token",
    "api_key",
    "authorization",
    "bearer",
    "client_secret",
    "cookie",
    "credential",
    "password",
    "private_key",
    "raw_log",
    "raw_payload",
    "secret",
    "session_token",
}


def normalize_federation_export_label(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "restricted": EXPORT_LABEL_CONFIDENTIAL,
        "customer": EXPORT_LABEL_CUSTOMER_SPECIFIC,
        "customer_derived": EXPORT_LABEL_CUSTOMER_SPECIFIC,
        "customer_specific": EXPORT_LABEL_CUSTOMER_SPECIFIC,
        "pii": EXPORT_LABEL_PERSONAL_DATA,
        "personal": EXPORT_LABEL_PERSONAL_DATA,
        "personal_data": EXPORT_LABEL_PERSONAL_DATA,
        "no_export": EXPORT_LABEL_NON_EXPORTABLE,
        "non_exportable": EXPORT_LABEL_NON_EXPORTABLE,
    }
    normalized = aliases.get(text, text)
    return normalized if normalized in FEDERATION_EXPORT_LABELS else EXPORT_LABEL_INTERNAL


def build_federation_export_policy(policy: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = dict(policy or {})
    review = dict(raw.get("review") or {})
    allowed_labels = {
        normalize_federation_export_label(item)
        for item in raw.get("allowed_labels", raw.get("allowed_classifications", PACKAGE_EXPORT_CLASSIFICATIONS))
    }
    allowed_labels.add(EXPORT_LABEL_PERSONAL_DATA)
    allow_with_review = {
        normalize_federation_export_label(item)
        for item in raw.get("allow_with_review", [EXPORT_LABEL_CONFIDENTIAL])
    }
    reviewer_role = str(raw.get("reviewer_role") or review.get("reviewer_role") or "").strip().lower()
    approved = bool(raw.get("review_approved") or review.get("approved"))
    reviewer_roles = {str(item).strip().lower() for item in raw.get("reviewer_roles", DEFAULT_REVIEW_ROLES)}
    return {
        "allowed_labels": allowed_labels or set(PACKAGE_EXPORT_CLASSIFICATIONS),
        "allow_with_review": allow_with_review,
        "review_approved": approved,
        "reviewer_role": reviewer_role,
        "reviewer_roles": reviewer_roles,
        "customer_terms": _term_list(raw.get("customer_terms")),
        "username_terms": _term_list(raw.get("username_terms")),
        "redact_urls": bool(raw.get("redact_urls", True)),
        "redact_jira_keys": bool(raw.get("redact_jira_keys", True)),
        "redact_repository_paths": bool(raw.get("redact_repository_paths", True)),
    }



def _fact_labels(fact: dict[str, Any], *, policy: dict[str, Any]) -> set[str]:
    labels = {normalize_federation_export_label(fact.get("classification"))}
    for label in _metadata_labels(fact):
        labels.add(label)
    serialized = _string_values(fact)
    if any(term and term in serialized for term in policy["customer_terms"]):
        labels.add(EXPORT_LABEL_CUSTOMER_SPECIFIC)
    fact_export_control = normalize_federation_export_label(fact.get("export_control"))
    if fact_export_control == EXPORT_LABEL_NON_EXPORTABLE:
        labels.add(EXPORT_LABEL_NON_EXPORTABLE)
    return labels


def _metadata_labels(value: Any) -> set[str]:
    labels: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key).strip().lower()
            if key_text in {"classification", "export_classification", "federation_label", "sensitivity"}:
                labels.add(normalize_federation_export_label(item))
            if key_text in {"customer", "customer_name", "customer_id", "tenant_id"} and item:
                labels.add(EXPORT_LABEL_CUSTOMER_SPECIFIC)
            if key_text in {"shareable", "exportable"} and item is False:
                labels.add(EXPORT_LABEL_NON_EXPORTABLE)
            labels.update(_metadata_labels(item))
    elif isinstance(value, list):
        for item in value:
            labels.update(_metadata_labels(item))
    elif isinstance(value, str):
        normalized = normalize_federation_export_label(value)
        if normalized in FEDERATION_EXPORT_LABELS and normalized != EXPORT_LABEL_INTERNAL:
            labels.add(normalized)
    return labels



def _string_values(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_string_values(item) for item in value.values()).lower()
    if isinstance(value, list):
        return " ".join(_string_values(item) for item in value).lower()
    return str(value or "").lower()


def _term_list(value: Any) -> list[str]:
    if isinstance(value, str):
        items = [item.strip().lower() for item in value.split(",")]
    elif isinstance(value, list):
        items = [str(item).strip().lower() for item in value]
    else:
        items = []
    return [item for item in items if item]

