"""Quality gate for a composed Word document — the docx mirror of the slide gate."""

from __future__ import annotations

from typing import Any

MAX_FINDINGS = 40

FINDING_CODES = (
    "heading_hierarchy_skip",
    "empty_section",
    "missing_evidence_source",
    "no_open_points",
    "off_brand_font",
)

#: Block kinds that carry a claim and therefore must state a source.
_SOURCED_KINDS = {"title", "heading", "diagram"}
#: Block kinds that count as a section's own content.
_CONTENT_KINDS = {"paragraph", "bullets", "diagram", "marker"}


def _finding(rule: str, index: int, message: str, *, severity: str = "warning") -> dict[str, Any]:
    return {"rule": rule, "severity": severity, "block_index": index, "message": message}


def _is_marker(block: dict[str, Any]) -> bool:
    text = str(block.get("text") or "")
    return block.get("kind") == "marker" or text.startswith("[")


class _SectionTracker:
    def __init__(self, findings: list[dict[str, Any]]) -> None:
        self.findings = findings
        self.prev_heading_level = 0
        self.open_section_index: int | None = None
        self.open_section_has_content = False

    def close(self) -> None:
        if self.open_section_index is not None and not self.open_section_has_content:
            self.findings.append(
                _finding(
                    "empty_section",
                    self.open_section_index,
                    "a heading has no content under it before the next heading",
                    severity="info",
                )
            )
        self.open_section_index = None
        self.open_section_has_content = False

    def heading(self, index: int, level: int) -> None:
        if self.prev_heading_level and level > self.prev_heading_level + 1:
            self.findings.append(
                _finding(
                    "heading_hierarchy_skip",
                    index,
                    f"heading jumps from level {self.prev_heading_level} to {level}, skipping a level",
                )
            )
        self.close()
        self.open_section_index = index
        self.open_section_has_content = False
        self.prev_heading_level = level


def check_document_quality(
    plan: list[dict[str, Any]],
    document_snapshot: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return findings for a document plan; empty when the plan is clean."""
    del document_snapshot  # reserved for a future font/colour brand check
    findings: list[dict[str, Any]] = []
    blocks = [block for block in (plan or []) if isinstance(block, dict)]
    sections = _SectionTracker(findings)
    has_open_points = False

    for index, block in enumerate(blocks):
        kind = str(block.get("kind") or "").strip()

        if kind in _SOURCED_KINDS and not str(block.get("source") or "").strip():
            findings.append(
                _finding(
                    "missing_evidence_source",
                    index,
                    f"{kind} block states a claim without a source",
                )
            )

        if kind == "heading":
            sections.heading(index, int(block.get("level") or 1))
            continue

        if kind in _CONTENT_KINDS and sections.open_section_index is not None:
            sections.open_section_has_content = True
        if _is_marker(block):
            has_open_points = True

    sections.close()

    if not has_open_points:
        findings.append(
            _finding(
                "no_open_points",
                len(blocks),
                "the document carries no open-points markers; the missing 20% must stay visible",
                severity="info",
            )
        )

    return findings[:MAX_FINDINGS]


__all__ = ["check_document_quality", "FINDING_CODES", "MAX_FINDINGS"]
