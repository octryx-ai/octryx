"""Matching helpers for design delivery sync."""

from __future__ import annotations

from typing import Any


def artifact_match_tokens(normalize_text, artifact: dict[str, Any], task_titles: list[str]) -> list[str]:
    tokens: list[str] = []
    for raw in [artifact.get("title"), artifact.get("summary"), *task_titles]:
        normalized = normalize_text(raw)
        if len(normalized) >= 8:
            tokens.append(normalized)
    deduped: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        deduped.append(token)
    return deduped


def artifact_title_matches(normalize_text, haystack: str, artifact: dict[str, Any]) -> bool:
    title = normalize_text(artifact.get("title"))
    return bool(title and title in haystack)


def artifact_summary_matches(normalize_text, haystack: str, artifact: dict[str, Any]) -> bool:
    summary = normalize_text(artifact.get("summary"))
    return bool(summary and len(summary) >= 8 and summary in haystack)


def task_title_matches(normalize_text, haystack: str, task_titles: list[str]) -> bool:
    return any(title and title in haystack for title in (normalize_text(value) for value in task_titles))


def linked_pull_request_matches(normalize_text, haystack: str, linked_prs: list[dict[str, Any]]) -> bool:
    for pr in linked_prs:
        pr_title = normalize_text(pr.get("title"))
        pr_number = str(pr.get("number") or "").strip()
        if pr_title and pr_title in haystack:
            return True
        if pr_number and any(
            marker in haystack for marker in [f"#{pr_number}", f"pr {pr_number}", f"pull request {pr_number}"]
        ):
            return True
    return False


def linked_release_matches(normalize_text, haystack: str, linked_releases: list[dict[str, Any]]) -> bool:
    for release in linked_releases:
        tag_name = normalize_text(release.get("tag_name"))
        release_title = normalize_text(release.get("title"))
        if tag_name and tag_name in haystack:
            return True
        if release_title and release_title in haystack:
            return True
    return False


def match_haystack_against_rules(
    normalize_match_rules,
    normalize_text,
    haystack: str,
    *,
    artifact: dict[str, Any],
    task_titles: list[str],
    tokens: list[str],
    linked_prs: list[dict[str, Any]],
    linked_releases: list[dict[str, Any]],
    rules: list[str],
) -> bool:
    if not haystack:
        return False
    for rule in normalize_match_rules(rules, ["artifact_tokens"]):
        if rule == "artifact_tokens" and any(token in haystack for token in tokens):
            return True
        if rule == "artifact_titles" and artifact_title_matches(normalize_text, haystack, artifact):
            return True
        if rule == "artifact_summaries" and artifact_summary_matches(normalize_text, haystack, artifact):
            return True
        if rule == "task_titles" and task_title_matches(normalize_text, haystack, task_titles):
            return True
        if rule == "linked_pull_requests" and linked_pull_request_matches(normalize_text, haystack, linked_prs):
            return True
        if rule == "linked_releases" and linked_release_matches(normalize_text, haystack, linked_releases):
            return True
    return False


def release_matches_artifact(
    normalize_match_rules,
    normalize_text,
    release: dict[str, Any],
    *,
    artifact: dict[str, Any],
    task_titles: list[str],
    tokens: list[str],
    linked_prs: list[dict[str, Any]],
    rules: list[str],
) -> bool:
    haystack = normalize_text(
        f"{release.get('title') or ''} {release.get('body') or ''} {release.get('tag_name') or ''}"
    )
    return match_haystack_against_rules(
        normalize_match_rules,
        normalize_text,
        haystack,
        artifact=artifact,
        task_titles=task_titles,
        tokens=tokens,
        linked_prs=linked_prs,
        linked_releases=[],
        rules=rules,
    )


def checkpoint_matches_artifact(
    normalize_match_rules,
    normalize_text,
    checkpoint: dict[str, Any],
    *,
    artifact: dict[str, Any],
    task_titles: list[str],
    tokens: list[str],
    linked_prs: list[dict[str, Any]],
    linked_releases: list[dict[str, Any]],
    rules: list[str],
) -> bool:
    haystack = normalize_text(
        f"{checkpoint.get('title') or ''} {checkpoint.get('body') or ''} "
        f"{checkpoint.get('branch') or ''} {checkpoint.get('event') or ''} "
        f"{checkpoint.get('conclusion') or ''}"
    )
    return match_haystack_against_rules(
        normalize_match_rules,
        normalize_text,
        haystack,
        artifact=artifact,
        task_titles=task_titles,
        tokens=tokens,
        linked_prs=linked_prs,
        linked_releases=linked_releases,
        rules=rules,
    )
