"""Validation of hand-written (custom) Cedar policies."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.services.content_detection.custom_definitions import DetectorDefinitions

from .engine import cedar_module, text_digest, validate_policy_text
from .obligation_checks import obligation_issues
from .schema import RESERVED_ID_PREFIXES, SCHEMA_VERSION

MAX_POLICY_TEXT_CHARS = 200_000
MAX_POLICIES = 500
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,119}$")

ERROR_TOO_LARGE = "policy_set_too_large"
ERROR_INVALID = "policy_set_invalid"
ERROR_TEMPLATES = "policy_set_templates_not_allowed"
ERROR_TOO_MANY = "policy_set_too_many_policies"
ISSUE_ID_REQUIRED = "policy_id_required"
ISSUE_ID_INVALID = "policy_id_invalid"
ISSUE_ID_RESERVED = "policy_id_reserved"
ISSUE_ID_DUPLICATE = "policy_id_duplicate"
ISSUE_PERMIT = "permit_not_allowed"


class CustomPolicyError(ValueError):
    def __init__(self, code: str, issues: list[dict[str, str]] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.issues = list(issues or [])[:50]


@dataclass(frozen=True, slots=True)
class CustomPolicySet:
    text: str
    ids: tuple[str, ...] = field(default_factory=tuple)
    digest: str = ""


def custom_digest(text: str) -> str:
    return text_digest(f"{SCHEMA_VERSION}\n{text}")


def set_digest(text: str, detectors: DetectorDefinitions | None = None) -> str:
    if detectors is None or detectors.empty:
        return custom_digest(text)
    return text_digest(f"{SCHEMA_VERSION}\n{text}\n#content-detectors {detectors.digest()}")


def _positional(item: tuple[str, Any]) -> int:
    digits = "".join(char for char in item[0] if char.isdigit())
    return int(digits) if digits else 0


def check_custom_policies(text: Any) -> CustomPolicySet:
    source = text if isinstance(text, str) else ""
    if len(source) > MAX_POLICY_TEXT_CHARS:
        raise CustomPolicyError(ERROR_TOO_LARGE)
    issues = [{"policy_id": item.policy_id, "code": "schema", "message": item.message}
              for item in validate_policy_text(source)]
    if issues:
        raise CustomPolicyError(ERROR_INVALID, issues)
    est = json.loads(cedar_module().policies_to_json_str(source))
    if est.get("templates"):
        raise CustomPolicyError(ERROR_TEMPLATES)
    static = sorted((est.get("staticPolicies") or {}).items(), key=_positional)
    if len(static) > MAX_POLICIES:
        raise CustomPolicyError(ERROR_TOO_MANY)
    ids: list[str] = []
    for position, (_, body) in enumerate(static):
        policy_id = str((body.get("annotations") or {}).get("id") or "")
        label = policy_id or f"#{position + 1}"
        if not policy_id:
            issues.append({"policy_id": label, "code": ISSUE_ID_REQUIRED, "message": "Add an @id annotation."})
        elif not ID_PATTERN.match(policy_id):
            issues.append({"policy_id": label, "code": ISSUE_ID_INVALID, "message": "Use letters, digits, ._:/@-."})
        elif policy_id.startswith(RESERVED_ID_PREFIXES):
            issues.append({"policy_id": label, "code": ISSUE_ID_RESERVED,
                           "message": "platform:, classification: and workspace: are generated ids."})
        elif policy_id in ids:
            issues.append({"policy_id": label, "code": ISSUE_ID_DUPLICATE, "message": "Each @id must be unique."})
        issues.extend(obligation_issues(label, body))
        if body.get("effect") != "forbid":
            issues.append({"policy_id": label, "code": ISSUE_PERMIT,
                           "message": "Custom policies may only forbid; the baseline grants."})
        ids.append(policy_id)
    if issues:
        raise CustomPolicyError(ERROR_INVALID, issues)
    return CustomPolicySet(source, tuple(ids), custom_digest(source))


__all__ = [
    "ERROR_INVALID",
    "ERROR_TEMPLATES",
    "ERROR_TOO_LARGE",
    "ERROR_TOO_MANY",
    "ID_PATTERN",
    "ISSUE_ID_DUPLICATE",
    "ISSUE_ID_INVALID",
    "ISSUE_ID_REQUIRED",
    "ISSUE_ID_RESERVED",
    "ISSUE_PERMIT",
    "MAX_POLICY_TEXT_CHARS",
    "CustomPolicyError",
    "CustomPolicySet",
    "check_custom_policies",
    "custom_digest",
    "set_digest",
]
