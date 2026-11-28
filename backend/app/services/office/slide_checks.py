"""The corporate-identity slide gate applied to any built deck (``office_identity.slide_gate``)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

#: Findings that shorter text fixes; they trigger the build tool's one aggressive re-normalization.
TEXT_FIT_CODES = frozenset({"text_overflow", "capacity_exceeded"})


def slide_gate_check(template_path: str | Path, deck_path: str | Path) -> dict[str, Any]:
    from ..office_identity import check_deck_quality
    from ..office_identity.template_snapshot import build_template_snapshot

    try:
        findings = check_deck_quality(build_template_snapshot(template_path), [], deck_path)
    except (OSError, ValueError, KeyError) as exc:
        return {"issue_count": None, "issues": [], "error_code": "slide_gate_failed", "error_type": type(exc).__name__}
    return {
        "source": "slide_gate",
        "issue_count": len(findings),
        "issues": findings[:50],
        "text_fit_findings": sum(1 for item in findings if item.get("code") in TEXT_FIT_CODES),
    }


__all__ = ["TEXT_FIT_CODES", "slide_gate_check"]
