"""Scanner results as review findings (tool runner).

The device runs the stack's scanners (``stacks.json`` ``scanners``: linters, SAST, secret scanners, pinned in the
launcher) on the pull request's changed files only, never on repository code it would execute. Every scanner reports
**SARIF 2.1** (gitleaks, opengrep, ruff, osv-scanner and eslint's formatter all write it), so one parser serves all;
which kind a scanner is (``lint``, ``sast``, ``secrets``, ``dependencies``) is data of its entry. Pure:

- **secrets** are always ``high`` and never quoted: the finding names the rule and the place, never the matched text
  or a snippet (SARIF carries the secret in its region snippet and often in the message);
- **sast** and **dependencies** map the SARIF level by the entry's ``severity_map`` (default error→high,
  warning→medium, note→low);
- **lint** counts only on lines the pull request changed and never above ``medium``: an old warning next to the
  change is not this pull request's finding.

A result outside the changed files is dropped (the scan only got those). Each finding gets the id ``S<n>`` and the
source ``scan``; at most :data:`MAX_FINDINGS` per review, the rest counted in the footer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .ci_results import short
from .diff_lines import ADDED, FileChange

KINDS = ("lint", "sast", "secrets", "dependencies")
DEFAULT_SEVERITY = {"error": "high", "warning": "medium", "note": "low", "none": "low"}
_RANK = {"low": 0, "medium": 1, "high": 2}
MAX_FINDINGS = 30


@dataclass(slots=True)
class ScanResult:
    findings: list[dict[str, Any]] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)  # the scanners whose report was read
    dropped: int = 0  # over :data:`MAX_FINDINGS`
    notes: list[str] = field(default_factory=list)  # a scanner not available, failed or timed out


def _relative(uri: str, root: str) -> str:
    """The repository path of a reported file: below ``root``, an absolute folder or the name of the unpacked
    archive's folder (a device job reports ``files/pay/x.py`` or ``/<temp>/files/pay/x.py``)."""
    path = str(uri or "").removeprefix("file://").removeprefix("./")
    root = str(root or "").rstrip("/")
    if root and path.startswith(root + "/"):
        return path[len(root) + 1:]
    if root and not root.startswith("/") and f"/{root}/" in path:
        return path.split(f"/{root}/", 1)[1]
    return path


def _location(result: dict[str, Any], root: str) -> tuple[str, int]:
    for location in result.get("locations") or []:
        physical = dict(dict(location or {}).get("physicalLocation") or {})
        uri = str(dict(physical.get("artifactLocation") or {}).get("uri") or "")
        if uri:
            line = dict(physical.get("region") or {}).get("startLine")
            return _relative(uri, root), int(line) if isinstance(line, int) and line > 0 else 1
    return "", 0


def _rule_texts(run: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """Per rule id: its short description and default level."""
    driver = dict(dict(run.get("tool") or {}).get("driver") or {})
    texts = {}
    for rule in driver.get("rules") or []:
        rule = dict(rule or {})
        text = str(dict(rule.get("shortDescription") or {}).get("text") or "")
        level = str(dict(rule.get("defaultConfiguration") or {}).get("level") or "")
        texts[str(rule.get("id") or "")] = (text, level)
    return texts


def _severity(kind: str, level: str, severity_map: dict[str, str]) -> str:
    if kind == "secrets":
        return "high"
    mapped = {**DEFAULT_SEVERITY, **{str(key).lower(): str(value) for key, value in severity_map.items()}}
    severity = mapped.get(level or "warning", "medium")
    severity = severity if severity in _RANK else "medium"
    if kind == "lint" and _RANK[severity] > _RANK["medium"]:
        return "medium"
    return severity


def _fix(kind: str, tool: str, rule: str, message: str) -> str:
    if kind == "secrets":
        return (f"{tool} found a secret ({rule}) committed here. Remove it from the change and rotate it: a pushed "
                "credential counts as leaked even after a later commit removes it.")
    return f"{tool} {rule}: {short(message, 300)}".strip()


def findings_from_sarif(scanner: dict[str, Any], sarif: dict[str, Any], *, root: str,
                        changed: dict[str, set[int]]) -> list[dict[str, Any]]:
    """One scanner's SARIF report as findings (``changed``: per changed file, the lines it added or changed)."""
    kind = str(scanner.get("kind") or "lint")
    kind = kind if kind in KINDS else "lint"
    tool = str(scanner.get("id") or "scanner")
    severity_map = dict(scanner.get("severity_map") or {})
    found: list[dict[str, Any]] = []
    for run in [dict(item or {}) for item in sarif.get("runs") or [] if isinstance(item, dict)]:
        rules = _rule_texts(run)
        for result in [dict(item or {}) for item in run.get("results") or [] if isinstance(item, dict)]:
            path, line = _location(result, root)
            if path not in changed:
                continue  # only the pull request's files were scanned; anything else is not its finding
            if kind == "lint" and line not in changed[path]:
                continue
            rule = str(result.get("ruleId") or "") or "rule"
            description, default_level = rules.get(rule, ("", ""))
            level = str(result.get("level") or default_level or "warning").lower()
            # A secret's message and snippet carry the secret itself: only the rule's own description is kept.
            message = description if kind == "secrets" else (
                str(dict(result.get("message") or {}).get("text") or "") or description)
            found.append({"severity": _severity(kind, level, severity_map), "file": path, "line": line,
                          "fix": _fix(kind, tool, rule, message), "source": "scan", "tool": tool, "rule": rule,
                          "kind": kind})
    return found


def scan_findings(reports: list[tuple[dict[str, Any], dict[str, Any]]], *, root: str,
                  changed: dict[str, set[int]]) -> ScanResult:
    """Every scanner's findings, the same place and rule once, highest severity first, numbered ``S<n>``."""
    result, seen = ScanResult(), set()
    every: list[dict[str, Any]] = []
    for scanner, sarif in reports:
        result.tools.append(str(scanner.get("id") or "scanner"))
        for finding in findings_from_sarif(scanner, sarif, root=root, changed=changed):
            key = (finding["file"], finding["line"], finding["rule"])
            if key not in seen:
                seen.add(key)
                every.append(finding)
    every.sort(key=lambda item: (-_RANK[item["severity"]], item["file"], item["line"]))
    result.dropped = max(0, len(every) - MAX_FINDINGS)
    for index, finding in enumerate(every[:MAX_FINDINGS], 1):
        result.findings.append({**finding, "id": f"S{index}"})
    return result


def changed_lines(files: dict[str, FileChange]) -> dict[str, set[int]]:
    """Per file the pull request keeps, the new-side lines it added (a deleted file is not scanned)."""
    return {path: {line for line, kind in change.lines.items() if kind == ADDED}
            for path, change in files.items() if change.status not in ("deleted", "binary")}


def to_facts(result: ScanResult) -> dict[str, Any]:
    """What ``pr_review.scan`` keeps on the run (``context.pr_review.scan``) for the reviewer and the post."""
    return {"findings": result.findings, "tools": result.tools, "dropped": result.dropped, "notes": result.notes}


__all__ = ["DEFAULT_SEVERITY", "KINDS", "MAX_FINDINGS", "ScanResult", "changed_lines", "findings_from_sarif",
           "scan_findings", "to_facts"]
