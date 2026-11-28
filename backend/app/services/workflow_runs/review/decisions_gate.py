"""The decisions check in the review (``spec_decisions``): the table for the reviewer, the platform's own findings
and the gate that applies them to the settled verdict, whatever the model answered."""

from __future__ import annotations

from typing import Any

from .spec_decisions import MISSING, DecisionCheck

DECISIONS_TABLE_RULE = (
    "The platform checked the specification's decisions against the working copy (the 'spec decisions' section: "
    "✓ implemented with its evidence, ✗ missing, ? unclear, · an existing decision that is context only). A ✗ "
    "decision is already a finding of the platform (high when hard, low for a differing value); "
    "do not repeat it. For every ? decision check the change and say in a finding (severity by its impact: \"high\" "
    "when the change contradicts it or leaves it out where the story needs it) or in the summary that it holds.")


def missing_findings(check: DecisionCheck | None) -> list[dict[str, Any]]:
    if check is None:
        return []
    found = [{"severity": "high", "file": check.spec, "line": 1,
              "fix": (f"Spec decision {item.number} not implemented: \"{item.text[:200]}\". {item.reason}. Implement "
                      f"it as decided (dependency and its use in the code) or have the product owner change the "
                      f"decision.")} for item in check.missing]
    for item in check.decisions:
        if not item.hard and item.state == MISSING:
            where = item.evidence[0].split(" ", 1)[0] if item.evidence else f"{check.spec}:1"
            file, _sep, line = where.rpartition(":")
            found.append({"severity": "low", "file": file or check.spec, "line": int(line) if line.isdigit() else 1,
                          "fix": f"Spec decision {item.number}: {item.reason} ({'; '.join(item.evidence[:2])})."})
    return found


def decisions_gate(settled: Any, check: DecisionCheck | None) -> Any:
    import dataclasses

    from .verdict import VERDICT_CHANGES, Finding

    added = missing_findings(check)
    if settled is None:
        return settled
    settled = _drop_settled_decisions(settled, check, added)
    if not added:
        return settled
    verdict = settled.verdict
    said = " ".join(finding.fix for finding in verdict.findings)
    new = [Finding(item["severity"], item["file"], item["line"], item["fix"], f"D{number}")
           for number, item in enumerate(added, 1) if item["fix"][:40] not in said]
    if not new:
        return settled
    findings = (*verdict.findings, *new)
    blocking = any(item.severity == "high" for item in new)
    # ``replace`` keeps every other field of the verdict (the PR review bot adds optional ones).
    return dataclasses.replace(settled, verdict=dataclasses.replace(
        verdict, verdict=VERDICT_CHANGES if blocking else verdict.verdict, findings=findings))


def _drop_settled_decisions(settled: Any, check: DecisionCheck | None, added: list[dict[str, Any]]) -> Any:
    import dataclasses

    from .verdict import BLOCKING_SEVERITIES, VERDICT_CHANGES, VERDICT_PASS

    if check is None:
        return settled
    current = {item["fix"][:40] for item in added}
    verdict = settled.verdict
    kept = tuple(finding for finding in verdict.findings
                 if not (_is_decision(finding) and finding.fix[:40] not in current))
    if len(kept) == len(verdict.findings):
        return settled
    blocking = any(finding.severity in BLOCKING_SEVERITIES for finding in kept)
    state = verdict.verdict if blocking or verdict.verdict != VERDICT_CHANGES else VERDICT_PASS
    return dataclasses.replace(settled, verdict=dataclasses.replace(verdict, findings=kept, verdict=state))


def _is_decision(finding: Any) -> bool:
    return str(getattr(finding, "id", "") or "").startswith("D") and str(finding.fix).startswith("Spec decision ")


__all__ = ["DECISIONS_TABLE_RULE", "decisions_gate", "missing_findings"]
