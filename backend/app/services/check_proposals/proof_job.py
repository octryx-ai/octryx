"""The proof of a proposed ast-grep check as one device tool job, and its verdict (From Correction to Check, step 2)."""

from __future__ import annotations

import json
from typing import Any

RULE_ARCHIVE, RULE_FILE, TOOL = "rule", "rule.yml", "ast-grep"
RULE_ID = "proposed-check"
LOCATIONS = 5


def rule_file(rule: dict[str, Any]) -> bytes:
    body = rule.get("rule") if isinstance(rule, dict) else None
    language = str(rule.get("language") or "") if isinstance(rule, dict) else ""
    if rule.get("tool") != TOOL or not isinstance(body, dict) or not body or not language:
        raise ValueError("a pattern draft names ast-grep, a language and a rule object")
    return json.dumps({"id": RULE_ID, "language": language, "severity": "error", "message": RULE_ID,
                       "rule": body}, sort_keys=True).encode()


def steps(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"id": f"scan-{case['archive']}", "tool": TOOL,
             "args": ["scan", "--rule", f"{{archive:{RULE_ARCHIVE}}}/{RULE_FILE}", "--json=stream",
                      f"{{archive:{case['archive']}}}"]} for case in cases]


def _matches(step: dict[str, Any], archive: str) -> list[str]:
    found = []
    for line in str(step.get("stdout") or "").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue  # the first line of a cut output
        if isinstance(item, dict) and item.get("file"):
            path = str(item["file"]).removeprefix(f"{archive}/")
            found.append(f"{path}:{int(dict(dict(item.get('range') or {}).get('start') or {}).get('line') or 0) + 1}")
    return found


def _outcome(step: dict[str, Any] | None, archive: str) -> tuple[str, list[str]]:
    if step is None or step.get("status") not in ("ok",) or step.get("exit") not in (0, 1):
        return "error", []
    found = _matches(step, archive)
    if step["exit"] == 0:
        return "clean", []
    # exit 1 without a match is ast-grep refusing the rule (it prints no match then)
    return ("match", found) if found or "error(s) found" in str(step.get("stderr") or "") else ("error", [])


def verdict(cases: list[dict[str, Any]], reported: list[dict[str, Any]], *, at: str) -> dict[str, Any]:
    by_id = {str(step.get("id")): step for step in reported}
    red_on, missed, flagged, errors, files = [], [], [], [], 0
    green_commit = ""
    for case in cases:
        outcome, found = _outcome(by_id.get(f"scan-{case['archive']}"), case["archive"])
        label = ", ".join(case["paths"])
        if outcome == "error":
            errors.append(case["archive"])
        elif case["side"] == "red":
            (red_on if outcome == "match" else missed).append({"commit": case["commit"], "path": label})
        else:
            files += len(case["paths"])
            green_commit = green_commit or case["commit"]
            flagged += found or ([label] if outcome == "match" else [])
    proof: dict[str, Any] = {"red_on": red_on, "green_on": {"commit": green_commit, "files_checked": files},
                             "at": at}
    if errors:
        return {**proof, "state": "failed", "reason": f"the check could not run on {len(errors)} case(s); the rule "
                "may be invalid for ast-grep"}
    if missed:
        return {**proof, "state": "failed", "reason": f"misses {len(missed)} of {len(missed) + len(red_on)} past "
                f"mistakes: {', '.join(item['path'] for item in missed[:LOCATIONS])}"}
    if flagged:
        return {**proof, "state": "failed", "reason": f"flags corrected code: {', '.join(flagged[:LOCATIONS])}"}
    return {**proof, "state": "proven"}


__all__ = ["RULE_ARCHIVE", "RULE_FILE", "TOOL", "rule_file", "steps", "verdict"]
