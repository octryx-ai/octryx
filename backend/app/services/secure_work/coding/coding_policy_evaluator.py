from __future__ import annotations

import fnmatch
import re
from typing import Any

from ....models import WorkChangePlan, WorkCodingPolicy, WorkItem
from ..jira_values import string_list

POLICY_TYPES = {
    "file_line_threshold",
    "pr_size_threshold",
    "protected_path",
    "sensitive_change",
    "dependency_change",
    "test_requirement",
    "documentation_requirement",
    "branch_commit_naming",
    "custom",
}
SEVERITIES = {"info", "low", "medium", "high", "critical"}
ENFORCEMENT_MODES = {"warn", "review_required", "block", "disabled"}
BLOCKING_EFFECTS = {"block", "review_required"}


def collect_change_evidence(
    *,
    work_item: WorkItem | None,
    change_plan: WorkChangePlan | None,
    change_units: list[dict[str, Any]],
    payload: dict[str, Any],
) -> dict[str, Any]:
    changed_files = [entry for entry in payload.get("changed_files") or [] if isinstance(entry, dict)]
    unit_paths = [path for unit in change_units for path in string_list(unit.get("expected_paths"))]
    plan_paths = list(change_plan.planned_files_json or []) if change_plan else []
    paths = _unique([*(str(entry.get("path") or "") for entry in changed_files), *unit_paths, *string_list(plan_paths)])
    plan_repositories, plan_validation_commands = _plan_evidence(change_plan)
    branches = _unique(
        [
            *string_list(payload.get("branches")),
            *(str(unit.get("branch_name") or "") for unit in change_units),
            *string_list(change_plan.proposed_branches_json if change_plan else []),
        ]
    )
    repositories = _unique(
        [
            *string_list(payload.get("repositories")),
            *(str(unit.get("repository_name") or "") for unit in change_units),
            *plan_repositories,
        ]
    )
    validation_commands = _unique(
        [
            *string_list(payload.get("validation_commands")),
            *(command for unit in change_units for command in string_list(unit.get("validation_commands"))),
            *plan_validation_commands,
        ]
    )
    changed_lines = _int_value(payload.get("changed_lines"))
    if changed_lines is None:
        changed_lines = sum(
            _int_value(entry.get("changed_lines") or entry.get("lines") or entry.get("code_lines")) or 0
            for entry in changed_files
        )
    return {
        "source_key": work_item.source_key if work_item else "",
        "repositories": repositories,
        "branches": branches,
        "paths": paths,
        "changed_files": changed_files,
        "changed_file_count": _int_value(payload.get("changed_file_count")) or len(paths),
        "changed_lines": changed_lines,
        "validation_commands": validation_commands,
        "dependencies": string_list(payload.get("dependencies") or payload.get("added_dependencies")),
        "has_change_evidence": bool(changed_files or paths or change_units or change_plan),
    }


def evaluate_policy(policy: WorkCodingPolicy, evidence: dict[str, Any]) -> dict[str, Any]:
    if policy.enforcement_mode == "disabled":
        return _outcome(policy, "skipped", "Policy is disabled.", evidence={})
    exception = _matching_exception(policy, evidence)
    if exception:
        return _outcome(policy, "skipped", "Policy exception matched.", evidence={"exception": exception})
    if not _scope_matches(policy, evidence):
        return _outcome(policy, "skipped", "Change evidence is outside policy scope.", evidence={})
    evaluator = {
        "file_line_threshold": _evaluate_file_line_threshold,
        "pr_size_threshold": _evaluate_pr_size_threshold,
        "protected_path": _evaluate_protected_path,
        "sensitive_change": _evaluate_protected_path,
        "dependency_change": _evaluate_dependency_change,
        "test_requirement": _evaluate_test_requirement,
        "documentation_requirement": _evaluate_documentation_requirement,
        "branch_commit_naming": _evaluate_branch_commit_naming,
    }.get(policy.policy_type, _evaluate_custom)
    return evaluator(policy, evidence)


def summarize_outcomes(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"pass": 0, "warn": 0, "review_required": 0, "block": 0, "skipped": 0}
    for outcome in outcomes:
        effect = str(outcome.get("effect") or "skipped")
        counts[effect] = counts.get(effect, 0) + 1
    return {
        "status": "blocked"
        if counts["block"]
        else "review_required"
        if counts["review_required"]
        else "warn"
        if counts["warn"]
        else "passed",
        "counts": counts,
        "total": len(outcomes),
        "blocking": counts["block"] + counts["review_required"],
    }


def _plan_evidence(change_plan: WorkChangePlan | None) -> tuple[list[str], list[str]]:
    if not change_plan:
        return [], []
    repositories = [
        str(entry.get("repository_name") or entry.get("name") or "")
        for entry in (change_plan.affected_repositories_json or [])
        if isinstance(entry, dict)
    ]
    validation_commands = [
        str(entry.get("command") or entry)
        for entry in (change_plan.validation_plan_json or [])
        if isinstance(entry, (dict, str))
    ]
    return repositories, validation_commands


def _evaluate_file_line_threshold(policy: WorkCodingPolicy, evidence: dict[str, Any]) -> dict[str, Any]:
    if not evidence["changed_files"]:
        return _missing_evidence(policy, "Changed file line counts are required for file threshold evaluation.")
    rule = dict(policy.rule_json or {})
    warn_above = _int_value(rule.get("warn_above_lines"))
    block_above = _int_value(rule.get("block_above_lines") or rule.get("max_lines"))
    largest = max(
        _int_value(entry.get("code_lines") or entry.get("lines") or entry.get("changed_lines")) or 0
        for entry in evidence["changed_files"]
    )
    if block_above is not None and largest > block_above:
        return _outcome(
            policy,
            "block",
            f"Largest file has {largest} lines, above block threshold {block_above}.",
            evidence={"largest_file_lines": largest},
        )
    if warn_above is not None and largest > warn_above:
        return _outcome(
            policy,
            _effect(policy),
            f"Largest file has {largest} lines, above warning threshold {warn_above}.",
            evidence={"largest_file_lines": largest},
        )
    return _outcome(policy, "pass", "File line thresholds passed.", evidence={"largest_file_lines": largest})


def _evaluate_pr_size_threshold(policy: WorkCodingPolicy, evidence: dict[str, Any]) -> dict[str, Any]:
    changed_lines = evidence["changed_lines"]
    changed_files = evidence["changed_file_count"]
    if changed_lines is None and changed_files == 0:
        return _missing_evidence(policy, "Changed line or file counts are required for PR size evaluation.")
    rule = dict(policy.rule_json or {})
    thresholds = {
        "block_lines": _int_value(rule.get("block_changed_lines")),
        "review_lines": _int_value(rule.get("review_changed_lines")),
        "warn_lines": _int_value(rule.get("warn_changed_lines")),
        "block_files": _int_value(rule.get("block_files")),
        "review_files": _int_value(rule.get("review_files")),
        "warn_files": _int_value(rule.get("warn_files")),
    }
    evidence_payload = {"changed_lines": changed_lines, "changed_files": changed_files}
    if _above(changed_lines, thresholds["block_lines"]) or _above(changed_files, thresholds["block_files"]):
        return _outcome(policy, "block", "Change size is above the blocking threshold.", evidence=evidence_payload)
    if _above(changed_lines, thresholds["review_lines"]) or _above(changed_files, thresholds["review_files"]):
        return _outcome(policy, "review_required", "Change size requires senior review.", evidence=evidence_payload)
    if _above(changed_lines, thresholds["warn_lines"]) or _above(changed_files, thresholds["warn_files"]):
        return _outcome(
            policy,
            _effect(policy),
            "Change size is above the warning threshold.",
            evidence=evidence_payload,
        )
    return _outcome(policy, "pass", "PR size thresholds passed.", evidence=evidence_payload)


def _evaluate_protected_path(policy: WorkCodingPolicy, evidence: dict[str, Any]) -> dict[str, Any]:
    patterns = string_list(
        (policy.rule_json or {}).get("protected_paths") or (policy.scope_json or {}).get("file_patterns")
    )
    matches = _matching_paths(evidence["paths"], patterns)
    if matches:
        return _outcome(policy, _effect(policy), "Protected or sensitive path matched.", evidence={"paths": matches})
    if not evidence["paths"]:
        return _missing_evidence(policy, "Changed paths are required for protected-path evaluation.")
    return _outcome(policy, "pass", "No protected paths matched.", evidence={})


def _evaluate_dependency_change(policy: WorkCodingPolicy, evidence: dict[str, Any]) -> dict[str, Any]:
    dependency_files = _matching_paths(
        evidence["paths"], ["pom.xml", "build.gradle*", "package.json", "requirements*.txt", "pyproject.toml"]
    )
    dependencies = evidence["dependencies"]
    if dependency_files or dependencies:
        return _outcome(
            policy,
            _effect(policy),
            "Dependency change requires governance.",
            evidence={"paths": dependency_files, "dependencies": dependencies},
        )
    return _outcome(policy, "pass", "No dependency changes detected.", evidence={})


def _evaluate_test_requirement(policy: WorkCodingPolicy, evidence: dict[str, Any]) -> dict[str, Any]:
    required = string_list(
        (policy.rule_json or {}).get("required_commands") or (policy.rule_json or {}).get("required_patterns")
    )
    commands = evidence["validation_commands"]
    if not required:
        if commands:
            return _outcome(policy, "pass", "Validation evidence is present.", evidence={"commands": commands})
        return _outcome(policy, _effect(policy), "Validation evidence is missing.", evidence={"commands": []})
    missing = [
        pattern
        for pattern in required
        if not any(fnmatch.fnmatch(command, pattern) or pattern in command for command in commands)
    ]
    if missing:
        return _outcome(
            policy,
            _effect(policy),
            "Required validation commands are missing.",
            evidence={"missing": missing, "commands": commands},
        )
    return _outcome(policy, "pass", "Required validation commands are present.", evidence={"commands": commands})


def _evaluate_documentation_requirement(policy: WorkCodingPolicy, evidence: dict[str, Any]) -> dict[str, Any]:
    docs = _matching_paths(evidence["paths"], ["*.md", "docs/**", "README*", "CHANGELOG*"])
    code = [path for path in evidence["paths"] if path and path not in docs]
    if code and not docs:
        return _outcome(
            policy,
            _effect(policy),
            "Code changes do not include documentation evidence.",
            evidence={"code_paths": code},
        )
    return _outcome(policy, "pass", "Documentation requirement passed.", evidence={"documentation_paths": docs})


def _evaluate_branch_commit_naming(policy: WorkCodingPolicy, evidence: dict[str, Any]) -> dict[str, Any]:
    patterns = string_list(
        (policy.rule_json or {}).get("branch_patterns") or (policy.scope_json or {}).get("branch_patterns")
    )
    if not evidence["branches"]:
        return _missing_evidence(policy, "Branch names are required for branch naming evaluation.")
    if not patterns:
        return _outcome(
            policy, "pass", "No branch naming pattern configured.", evidence={"branches": evidence["branches"]}
        )
    invalid = [
        branch for branch in evidence["branches"] if not any(_pattern_matches(branch, pattern) for pattern in patterns)
    ]
    if invalid:
        return _outcome(
            policy,
            _effect(policy),
            "Branch name does not match the required pattern.",
            evidence={"invalid_branches": invalid, "patterns": patterns},
        )
    return _outcome(policy, "pass", "Branch naming policy passed.", evidence={"branches": evidence["branches"]})


def _evaluate_custom(policy: WorkCodingPolicy, evidence: dict[str, Any]) -> dict[str, Any]:
    if not evidence["has_change_evidence"]:
        return _missing_evidence(policy, "Change evidence is required for custom policy preview.")
    return _outcome(policy, "review_required", "Custom policy requires human review.", evidence={})


def _missing_evidence(policy: WorkCodingPolicy, reason: str) -> dict[str, Any]:
    if policy.enforcement_mode == "warn":
        return _outcome(policy, "warn", reason, evidence={"missing_evidence": True})
    return _outcome(policy, "review_required", reason, evidence={"missing_evidence": True})


def _scope_matches(policy: WorkCodingPolicy, evidence: dict[str, Any]) -> bool:
    scope = dict(policy.scope_json or {})
    repository_names = string_list(scope.get("repository_names"))
    branch_patterns = string_list(scope.get("branch_patterns"))
    file_patterns = string_list(scope.get("file_patterns"))
    if repository_names and not set(repository_names).intersection(evidence["repositories"]):
        return False
    if branch_patterns and not any(
        _pattern_matches(branch, pattern) for branch in evidence["branches"] for pattern in branch_patterns
    ):
        return False
    if file_patterns and not _matching_paths(evidence["paths"], file_patterns):
        return False
    return True


def _matching_exception(policy: WorkCodingPolicy, evidence: dict[str, Any]) -> dict[str, Any] | None:
    for entry in policy.exceptions_json or []:
        if isinstance(entry, str):
            if _matching_paths(evidence["paths"], [entry]) or evidence["source_key"] == entry:
                return {"pattern": entry}
        elif isinstance(entry, dict):
            patterns = string_list(entry.get("file_patterns") or entry.get("patterns") or entry.get("pattern"))
            issue_keys = set(string_list(entry.get("issue_keys") or entry.get("source_keys")))
            if (patterns and _matching_paths(evidence["paths"], patterns)) or evidence["source_key"] in issue_keys:
                return entry
    return None


def _outcome(policy: WorkCodingPolicy, effect: str, reason: str, *, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "policy_id": policy.id,
        "name": policy.name,
        "policy_type": policy.policy_type,
        "severity": policy.severity,
        "enforcement_mode": policy.enforcement_mode,
        "effect": effect,
        "passed": effect in {"pass", "skipped"},
        "blocking": effect in BLOCKING_EFFECTS,
        "reason": reason,
        "remediation": policy.remediation or "",
        "evidence": evidence,
    }


def _effect(policy: WorkCodingPolicy) -> str:
    return "warn" if policy.enforcement_mode == "warn" else policy.enforcement_mode


def _matching_paths(paths: list[str], patterns: list[str]) -> list[str]:
    return [path for path in paths if path and any(_pattern_matches(path, pattern) for pattern in patterns)]


def _pattern_matches(value: str, pattern: str) -> bool:
    if not pattern:
        return False
    if pattern.startswith("regex:"):
        return re.search(pattern.removeprefix("regex:"), value) is not None
    return fnmatch.fnmatch(value, pattern) or fnmatch.fnmatch(value.lower(), pattern.lower())


def _above(value: int | None, threshold: int | None) -> bool:
    return value is not None and threshold is not None and value > threshold


def _int_value(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in seen:
            result.append(normalized)
            seen.add(normalized)
    return result
