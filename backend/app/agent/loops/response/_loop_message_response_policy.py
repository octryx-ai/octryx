"""User-visible loop message text policies (fixed answer texts are catalog keys ``answer.*``)."""

from __future__ import annotations

from collections.abc import Iterable

from app.services.prompt_catalog import render_prompt


def build_runtime_salvage_presentation_message(*, topic: str, relative_path: str) -> str:
    artifact_line = (
        render_prompt("answer.salvage.presentation_file", relative_path=relative_path)
        if relative_path
        else render_prompt("answer.salvage.presentation_file_unknown")
    )
    return render_prompt(
        "answer.salvage.presentation",
        topic=topic,
        artifact_line=artifact_line,
        provider_limit_suffix=render_prompt("answer.provider_limit_suffix"),
    )


def build_runtime_salvage_outline_from_evidence_message() -> str:
    return render_prompt("answer.salvage.outline", provider_limit_suffix=render_prompt("answer.provider_limit_suffix"))


def build_runtime_salvage_weekly_summary_message(
    *,
    jira_count: int,
    bitbucket_count: int,
    confluence_count: int,
) -> str:
    return render_prompt(
        "answer.salvage.weekly_summary",
        jira_line=render_prompt("answer.salvage.weekly_jira", jira_count=jira_count),
        bitbucket_line=render_prompt("answer.salvage.weekly_bitbucket", bitbucket_count=bitbucket_count),
        confluence_line=render_prompt("answer.salvage.weekly_confluence", confluence_count=confluence_count),
        provider_limit_suffix=render_prompt("answer.provider_limit_suffix"),
    )


def build_runtime_salvage_office_artifact_message(*, relative_path: str) -> str:
    return render_prompt(
        "answer.salvage.office_artifact",
        relative_path=relative_path,
        provider_limit_suffix=render_prompt("answer.provider_limit_suffix"),
    )


def build_tool_execution_status_message(*, tool_names: Iterable[str]) -> str:
    names = [str(name).strip() for name in tool_names if str(name).strip()]
    if not names:
        return render_prompt("answer.tool_status.empty")
    if len(names) == 1:
        return render_prompt("answer.tool_status.single", tool_name=names[0])
    preview = ", ".join(f"`{name}`" for name in names[:3])
    if len(names) > 3:
        preview += ", ..."
    return render_prompt("answer.tool_status.multi", tool_names=preview)
