"""Provider-owned GitLab merge request tools."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ...services.ai_marking import marking_facts, with_marker
from ...services.outbound_egress import CONNECTION_GITLAB
from ...services.source_control import SourceControlOperation
from ..context import ToolContext
from ..scm_requester_rule import apply_requester_rule, connection_author
from .common import _string, connection_http_json
from .gitlab import _gitlab_base_url, _gitlab_headers, _resolve_gitlab_project
from .gitlab_source_control import _gitlab_default_branch
from .gitlab_source_control_common import gitlab_source_control_metadata, require_gitlab_repository_operation
from .source_control_evidence import gitlab_web_base, with_web_url_source

_http_json = connection_http_json(CONNECTION_GITLAB)


def _mr_summary(mr: dict[str, Any]) -> dict[str, Any]:
    return {
        "iid": mr.get("iid"),
        "title": mr.get("title"),
        "state": mr.get("state"),
        "author": (mr.get("author") or {}).get("username"),
        "from_branch": mr.get("source_branch"),
        "to_branch": mr.get("target_branch"),
        "created_at": mr.get("created_at"),
        "updated_at": mr.get("updated_at"),
        "web_url": mr.get("web_url"),
    }


def _change_request_output(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "change_request_id": str(summary.get("iid") or ""),
        "title": summary.get("title") or "",
        "state": summary.get("state") or "",
        "source_branch": summary.get("from_branch") or "",
        "target_branch": summary.get("to_branch") or "",
        "url": summary.get("web_url") or "",
    }


def _change_request_source_control(
    operation: SourceControlOperation,
    *,
    project: str,
    status: str,
    summary: dict[str, Any],
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return gitlab_source_control_metadata(
        operation,
        project=project,
        status=status,
        output=_change_request_output(summary),
        evidence=evidence or {},
    )


class GetGitLabMergeRequestTool:
    name = "get_gitlab_merge_request"
    description = "Get details of a configured GitLab merge request."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        project = _resolve_gitlab_project(context, params)
        mr_iid = _string(params.get("mr_iid") or params.get("iid"))
        if not project or not mr_iid:
            return {"error": "project and mr_iid are required and project must be allowed"}
        denied = await require_gitlab_repository_operation(context, project=project, operation="read")
        if denied:
            return denied
        mr = await _http_json(
            "GET",
            f"{_gitlab_base_url(context)}/projects/{quote(project, safe='')}/merge_requests/{quote(mr_iid, safe='')}",
            headers=await _gitlab_headers(context),
        )
        # The merge request's own web URL, only on the configured GitLab host (evidence fields).
        result = with_web_url_source(
            _mr_summary(mr),
            gitlab_web_base(context),
            url_field="web_url",
            title=f"{project} !{mr.get('iid')}: {mr.get('title') or ''}",
        )
        result["project"] = project
        result["source_control"] = _change_request_source_control(
            SourceControlOperation.GET_CHANGE_REQUEST,
            project=project,
            status="read",
            summary=result,
        )
        return result


async def _reviewer_ids(context: ToolContext, raw: Any) -> tuple[list[int], list[str]]:
    """GitLab takes reviewer ids: each requested username is looked up; one GitLab does not know is reported."""
    names = [_string(item) for item in raw or [] if _string(item)] if isinstance(raw, list) else []
    ids: list[int] = []
    unresolved: list[str] = []
    for name in names:
        users = await _http_json(
            "GET", f"{_gitlab_base_url(context)}/users", headers=await _gitlab_headers(context),
            params={"username": name},
        )
        match = next((user for user in users or [] if isinstance(user, dict) and user.get("id") is not None), None)
        if match is None:
            unresolved.append(name)
        else:
            ids.append(int(match["id"]))
    return ids, unresolved


class CreateGitLabMergeRequestTool:
    name = "create_gitlab_merge_request"
    description = "Create a merge request in a configured GitLab project."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        project = _resolve_gitlab_project(context, params)
        title = _string(params.get("title"))
        from_branch = _string(params.get("from_branch") or params.get("source_branch"))
        if not project or not title or not from_branch:
            return {"error": "project, title and from_branch are required and project must be allowed"}
        denied = await require_gitlab_repository_operation(context, project=project, operation="pr")
        if denied:
            return denied
        to_branch = _string(params.get("to_branch") or params.get("target_branch")) or await _gitlab_default_branch(
            context, project
        )
        reviewers = [_string(item) for item in params.get("reviewers") or [] if _string(item)] if isinstance(
            params.get("reviewers"), list) else []
        description, requester, skipped = _string(params.get("description")), _string(params.get("requester")), ""
        if requester and reviewers:
            async def username() -> str:
                me = await _http_json("GET", f"{_gitlab_base_url(context)}/user", headers=await _gitlab_headers(context))
                return _string((me or {}).get("username"))

            reviewers, description, skipped = apply_requester_rule(
                reviewers, requester=requester, author=await connection_author("gitlab", username),
                description=description, mention=f"@{requester}")
        description = with_marker(description, await marking_facts(context))
        reviewer_ids, unresolved = await _reviewer_ids(context, reviewers)
        body: dict[str, Any] = {
            "title": title,
            "source_branch": from_branch,
            "target_branch": to_branch,
            "description": description,
        }
        if reviewer_ids:
            body["reviewer_ids"] = reviewer_ids
        mr = await _http_json(
            "POST",
            f"{_gitlab_base_url(context)}/projects/{quote(project, safe='')}/merge_requests",
            headers=await _gitlab_headers(context),
            json_body=body,
        )
        summary = _mr_summary(mr)
        return {
            **summary,
            "project": project,
            "status": "created",
            "reviewers": [item.get("username") for item in mr.get("reviewers") or [] if isinstance(item, dict)],
            "reviewers_unresolved": unresolved,
            **({"reviewer_skipped": skipped} if skipped else {}),
            "source_control": _change_request_source_control(
                SourceControlOperation.CREATE_CHANGE_REQUEST,
                project=project,
                status="created",
                summary=summary,
                evidence={"source_branch": from_branch, "target_branch": to_branch},
            ),
        }


class UpdateGitLabMergeRequestTool:
    name = "update_gitlab_merge_request"
    description = "Update title, description, target branch, or state of a configured GitLab merge request."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        project = _resolve_gitlab_project(context, params)
        mr_iid = _string(params.get("mr_iid") or params.get("iid"))
        if not project or not mr_iid:
            return {"error": "project and mr_iid are required and project must be allowed"}
        if not any(key in params for key in ("title", "description", "to_branch", "target_branch", "state")):
            return {"error": "At least one of title, description, to_branch/target_branch, or state is required"}
        denied = await require_gitlab_repository_operation(context, project=project, operation="pr")
        if denied:
            return denied
        payload: dict[str, Any] = {}
        if "title" in params:
            payload["title"] = _string(params.get("title"))
        if "description" in params:
            payload["description"] = _string(params.get("description"))
        if "to_branch" in params or "target_branch" in params:
            payload["target_branch"] = _string(params.get("to_branch") or params.get("target_branch"))
        if "state" in params:
            payload["state_event"] = _string(params.get("state"))
        mr = await _http_json(
            "PUT",
            f"{_gitlab_base_url(context)}/projects/{quote(project, safe='')}/merge_requests/{quote(mr_iid, safe='')}",
            headers=await _gitlab_headers(context),
            json_body=payload,
        )
        summary = _mr_summary(mr)
        return {
            **summary,
            "project": project,
            "status": "updated",
            "source_control": _change_request_source_control(
                SourceControlOperation.UPDATE_CHANGE_REQUEST,
                project=project,
                status="updated",
                summary=summary,
                evidence={"updated_fields": sorted(payload)},
            ),
        }
