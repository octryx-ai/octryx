from __future__ import annotations

from typing import Any

from ...models import WorkItem
from .jira_values import object_value, string_list

DEFAULT_AUTOMATION_LABEL = "octryx"


def work_item_automation_eligibility(item: WorkItem) -> dict[str, Any]:
    source_fields = object_value(item.source_fields_json)
    policy = object_value(source_fields.get("automation_policy"))
    labels = [str(label).strip() for label in item.labels_json or [] if str(label).strip()]
    trigger_labels = _configured_labels(policy, "trigger_labels", [DEFAULT_AUTOMATION_LABEL])
    exclude_labels = _configured_labels(policy, "exclude_labels", ["human-only", "no-octryx"])
    matched = [label for label in labels if _matches(label, trigger_labels)]
    excluded = [label for label in labels if _matches(label, exclude_labels)]
    blocking_reasons: list[str] = []
    review_reasons: list[str] = []
    reason_codes: list[str] = []

    if matched:
        reason_codes.extend([f"label:{label}" for label in matched])
    if excluded:
        blocking_reasons.extend([f"excluded_label:{label}" for label in excluded])
    if not matched:
        reason_codes.append("missing_label:octryx")
    if item.sync_state in {"removed_from_source_filter", "failed"}:
        blocking_reasons.append(f"sync_state:{item.sync_state}")
    if item.work_state == "done":
        blocking_reasons.append("work_state:done")
    if not _has_text(item.description):
        review_reasons.append("missing_description")
    if not _has_acceptance_evidence(item):
        review_reasons.append("missing_acceptance_criteria")
    if not _has_repository_evidence(item):
        review_reasons.append("missing_repository_evidence")

    requested = bool(matched)
    blocked = bool(blocking_reasons)
    can_start = requested and not blocked
    if not requested:
        mode = "human_only"
    elif blocked:
        mode = "blocked"
    else:
        mode = str(policy.get("mode") or policy.get("automation_mode") or "needs_review").strip() or "needs_review"

    return {
        "requested": requested,
        "can_start": can_start,
        "mode": mode,
        "trigger_label": DEFAULT_AUTOMATION_LABEL,
        "trigger_labels": trigger_labels,
        "matched_labels": matched,
        "blocking_reasons": blocking_reasons,
        "review_reasons": review_reasons,
        "reason_codes": reason_codes,
        "policy_source": "sync_config" if policy else "default",
    }


def automation_policy_for_sync_config(sync_options: dict[str, Any]) -> dict[str, Any]:
    policy = object_value(sync_options.get("automation_policy"))
    trigger_labels = _configured_labels(policy, "trigger_labels", [])
    if not trigger_labels:
        trigger_labels = _configured_labels(sync_options, "automation_labels", [DEFAULT_AUTOMATION_LABEL])
    exclude_labels = _configured_labels(policy, "exclude_labels", [])
    if not exclude_labels:
        exclude_labels = _configured_labels(sync_options, "automation_exclude_labels", [])
    normalized = {
        "trigger_labels": trigger_labels,
        "exclude_labels": exclude_labels or ["human-only", "no-octryx"],
    }
    mode = str(policy.get("mode") or policy.get("automation_mode") or sync_options.get("automation_mode") or "").strip()
    if mode:
        normalized["mode"] = mode
    return normalized


def _configured_labels(config: dict[str, Any], key: str, default: list[str]) -> list[str]:
    labels = string_list(config.get(key))
    return labels or default


def _matches(label: str, candidates: list[str]) -> bool:
    normalized = label.strip().casefold()
    return any(normalized == candidate.strip().casefold() for candidate in candidates)


def _has_text(value: Any) -> bool:
    return bool(str(value or "").strip())


def _has_acceptance_evidence(item: WorkItem) -> bool:
    source_fields = object_value(item.source_fields_json)
    raw = object_value(source_fields.get("raw"))
    fields = object_value(raw.get("fields"))
    return any(
        _has_text(value)
        for value in [
            source_fields.get("acceptance_criteria"),
            fields.get("acceptanceCriteria"),
            fields.get("customfield_acceptance_criteria"),
        ]
    )


def _has_repository_evidence(item: WorkItem) -> bool:
    source_fields = object_value(item.source_fields_json)
    return any(
        bool(source_fields.get(key))
        for key in [
            "affected_repositories",
            "repositories",
            "planned_branches",
            "change_units",
            "pull_requests",
        ]
    )
