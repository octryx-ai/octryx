"""Typed validation issues of an Agent Definition revision snapshot. A fixed code plus the offending identifier, never
authored prose or configuration content."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    # ``subject`` carries identifiers only, never authored prose or configuration content.

    code: str
    field: str
    subject: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "field": self.field, "subject": self.subject}


@dataclass(frozen=True, slots=True)
class ValidationResult:
    ok: bool
    issues: tuple[ValidationIssue, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "issues": [issue.as_dict() for issue in self.issues]}


def _result(issues: list[ValidationIssue]) -> ValidationResult:
    return ValidationResult(ok=not issues, issues=tuple(issues))
