"""Bitbucket diff tool."""

from typing import Any

from app.tools.context import ToolContext

from . import _bitbucket_internal_network
from ._bitbucket_evidence import with_commit_source
from ._bitbucket_internal_core import _bitbucket_base_url, _is_repo_allowed


class GetBitbucketDiff:
    name = "get_bitbucket_diff"
    description = (
        "Get the actual diff content of a commit or between two refs in an allowed Bitbucket repository. "
        "Use commit_id for a single commit diff, or from_ref+to_ref for a range."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if not _bitbucket_base_url(context):
            return {"error": "No Bitbucket URL configured for this project"}

        project_key = str(params.get("project_key") or "").strip()
        repo_slug = str(params.get("repo_slug") or "").strip()
        if not project_key or not repo_slug:
            return {"error": "project_key and repo_slug are required"}
        if not _is_repo_allowed(context, project_key, repo_slug):
            return {"error": f"Repository {project_key}/{repo_slug} is not allowed for this project"}

        commit_id = str(params.get("commit_id") or "").strip()
        from_ref = str(params.get("from_ref") or "").strip()
        to_ref = str(params.get("to_ref") or "").strip()
        path_filter = str(params.get("path") or "").strip()

        if not commit_id and not (from_ref and to_ref):
            return {"error": "commit_id or both from_ref and to_ref are required"}

        req_params: dict[str, Any] = {"withComments": "false"}
        if from_ref:
            req_params["since"] = from_ref
        if to_ref:
            req_params["until"] = to_ref
        if path_filter:
            req_params["path"] = path_filter

        base_path = (
            f"/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/commits/{commit_id}/diff"
            if commit_id
            else f"/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/diff"
        )
        payload = await _bitbucket_internal_network._bitbucket_json_get(context, base_path, params=req_params)

        diffs = []
        for d in (payload.get("diffs") or [])[:20]:
            dst = (d.get("destination") or {}).get("toString", "")
            src = (d.get("source") or {}).get("toString", "")
            hunks_text = []
            for hunk in (d.get("hunks") or [])[:10]:
                lines = []
                for seg in hunk.get("segments") or []:
                    prefix = {"ADDED": "+", "REMOVED": "-", "CONTEXT": " "}.get(seg.get("type", "CONTEXT"), " ")
                    for line in seg.get("lines") or []:
                        lines.append(f"{prefix}{line.get('line', '')}")
                if lines:
                    hunks_text.append(
                        f"@@ -{hunk.get('sourceLine', 0)},{hunk.get('sourceSpan', 0)} "
                        f"+{hunk.get('destinationLine', 0)},{hunk.get('destinationSpan', 0)} @@\n" + "\n".join(lines)
                    )
            diffs.append(
                {
                    "path": dst or src,
                    "type": "MODIFY" if dst and src else "ADD" if dst else "DELETE",
                    "hunks": hunks_text,
                }
            )

        result = {
            "project_key": project_key,
            "repo_slug": repo_slug,
            "commit_id": commit_id or None,
            "from_ref": from_ref or None,
            "to_ref": to_ref or None,
            "files_changed": len(diffs),
            "diffs": diffs,
        }
        # A single commit's diff names the commit page on the configured Bitbucket (evidence fields);
        # a range between two refs has no item page.
        return with_commit_source(result, _bitbucket_base_url(context), project_key, repo_slug) if commit_id else result
