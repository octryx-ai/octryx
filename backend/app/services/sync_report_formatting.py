"""Formatting helpers for repository sync reporting.

Service-owned module: renders user-facing Bitbucket and repository sync
report templates.
"""

from datetime import UTC, datetime
from typing import Any


def _format_recent_bitbucket_commits_report(result: dict) -> str:
    commits = result.get("commits") or []
    days = int(result.get("days") or 0)
    if not commits:
        return f"I did not find any commits in the approved Bitbucket repositories within the last {days} days."

    def fmt_timestamp(timestamp_ms: int | None) -> str:
        if not isinstance(timestamp_ms, int):
            return "-"
        return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")

    def escape_cell(value: object) -> str:
        text = str(value or "").replace("\n", " ").replace("|", "\\|")
        return text.strip() or "-"

    lines = [
        f"Here is the table of all commits from the last {days} days in the approved Bitbucket repositories.",
        "",
        f"Total found: **{len(commits)} commits**",
        "",
        "| Repository | Date | Commit | Author | Message |",
        "| --- | --- | --- | --- | --- |",
    ]
    for commit in commits:
        lines.append(
            "| "
            + " | ".join(
                [
                    escape_cell(
                        commit.get("repository_label") or f"{commit.get('project_key')}/{commit.get('repo_slug')}"
                    ),
                    escape_cell(fmt_timestamp(commit.get("author_timestamp"))),
                    escape_cell(commit.get("display_id") or commit.get("id")),
                    escape_cell(commit.get("author_name")),
                    escape_cell(commit.get("message")),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _format_repository_knowledge_sync_report(tool_results: list[dict[str, Any]]) -> str | None:
    by_name = {item.get("tool_name"): (item.get("result") or {}) for item in tool_results}
    batch_result = by_name.get("upsert_project_knowledge_batch")
    sync_result = by_name.get("update_repository_sync_states")
    if not isinstance(batch_result, dict) or batch_result.get("error"):
        return None
    if not isinstance(sync_result, dict) or sync_result.get("error"):
        return None

    entries = batch_result.get("entries") or []
    repositories = sync_result.get("repositories") or []
    lines = [
        "Incremental repository knowledge sync completed.",
        "",
        f"- Knowledge entries written: **{batch_result.get('count', 0)}**",
        f"- Created: **{batch_result.get('created', 0)}**",
        f"- Updated: **{batch_result.get('updated', 0)}**",
        f"- Repository sync states updated: **{sync_result.get('count', 0)}**",
    ]
    if entries:
        lines.extend(["", "Updated knowledge keys:"])
        for entry in entries[:12]:
            lines.append(f"- `{entry.get('category')}/{entry.get('key')}` (v{entry.get('version')})")
        if len(entries) > 12:
            lines.append(f"- ... and {len(entries) - 12} more")
    if repositories:
        lines.extend(["", "Updated repository sync states:"])
        for item in repositories[:8]:
            lines.append(
                f"- `{item.get('project_key')}/{item.get('repo_slug')}` -> `{item.get('last_synced_commit')}`"
            )
        if len(repositories) > 8:
            lines.append(f"- ... and {len(repositories) - 8} more")
    return "\n".join(lines)


def _format_repository_noop_sync_report(tool_results: list[dict[str, Any]]) -> str | None:
    by_name = {item.get("tool_name"): (item.get("result") or {}) for item in tool_results}
    plan_result = by_name.get("plan_bitbucket_knowledge_sync")
    if isinstance(plan_result, dict) and not plan_result.get("error"):
        if int(plan_result.get("changed_repository_count") or 0) == 0:
            return "\n".join(
                [
                    "Incremental repository knowledge sync found no changes.",
                    "",
                    f"- Project: **{plan_result.get('project_name') or plan_result.get('project_id') or 'unknown'}**",
                    "- Tracked repositories: "
                    f"**{plan_result.get('tracked_repository_count', plan_result.get('repository_count', 0))}**",
                    "- Changed repositories: **0**",
                    "",
                    "All tracked repositories are already in sync with the stored repository sync state. "
                    "No Knowledge Map update was required.",
                ]
            )

    source_result = by_name.get("collect_repository_knowledge_sources")
    if isinstance(source_result, dict) and not source_result.get("error"):
        if int(source_result.get("count") or 0) == 0:
            return "\n".join(
                [
                    "Incremental repository knowledge sync found no repositories that require source collection.",
                    "",
                    f"- Repository source batches: **{source_result.get('count', 0)}**",
                    "- Summary: "
                    f"{source_result.get('summary') or 'No repositories require knowledge source collection.'}",
                    "",
                    "No README or code-analysis update was needed, so the Knowledge Map was left unchanged.",
                ]
            )

    return None
