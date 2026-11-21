"""Git Worktree Isolation tools."""

from __future__ import annotations

from typing import Any

from .context import ToolContext


class WorktreeCreateTool:
    name = "worktree_create"
    description = (
        "Create an isolated git worktree for the current agent session. "
        "All subsequent file edits happen in the worktree and do not affect the main branch. "
        "Returns the worktree path – pass this as workspace_root for isolated work. "
        "Requires the workspace to be a git repository."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        from pathlib import Path

        from ..services.worktree import worktree_service

        workspace = str(context.workspace_root or Path.cwd())
        session_id = str(context.session_id or "default")
        branch_prefix = str(params.get("branch_prefix") or "agent")

        try:
            wt = await worktree_service.create(
                session_id=session_id,
                workspace_root=workspace,
                branch_prefix=branch_prefix,
            )
        except Exception as e:
            return {"error": str(e)}

        return {
            "id": wt.id,
            "session_id": wt.session_id,
            "branch": wt.branch,
            "path": str(wt.path),
            "git_root": str(wt.git_root),
            "status": "created",
        }


class WorktreeListTool:
    name = "worktree_list"
    description = "List all active git worktrees managed by this server."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        from ..services.worktree import worktree_service

        worktrees = await worktree_service.list()
        return {
            "worktrees": [
                {
                    "id": wt.id,
                    "session_id": wt.session_id,
                    "branch": wt.branch,
                    "path": str(wt.path),
                }
                for wt in worktrees
            ],
            "count": len(worktrees),
        }


class WorktreeDiffTool:
    name = "worktree_diff"
    description = (
        "Show unified diff of all changes in the current session's worktree vs the base commit. "
        "Useful for reviewing all changes before merging."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        from ..services.worktree import worktree_service

        session_id = str(context.session_id or "default")
        try:
            diff = await worktree_service.diff(session_id)
        except Exception as e:
            return {"error": str(e)}

        return {"session_id": session_id, "diff": diff[:8000]}


class WorktreeCommitTool:
    name = "worktree_commit"
    description = "Stage all changes in the current session's worktree and create a git commit. Returns the commit SHA."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        from ..services.ai_marking import commit_message_with_trailers, marking_facts
        from ..services.worktree import worktree_service

        session_id = str(context.session_id or "default")
        message = str(params.get("message") or f"Agent session {session_id[:8]} changes")
        message = commit_message_with_trailers(message, await marking_facts(context))
        try:
            sha = await worktree_service.commit(session_id, message)
        except Exception as e:
            return {"error": str(e)}

        return {"session_id": session_id, "sha": sha, "message": message}


class WorktreeCleanupTool:
    name = "worktree_cleanup"
    description = (
        "Remove the git worktree for the current session and delete the associated branch. "
        "Call this after the agent has finished its work (or after merging)."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        from ..services.worktree import worktree_service

        session_id = str(context.session_id or "default")
        try:
            removed = await worktree_service.cleanup(session_id)
        except Exception as e:
            return {"error": str(e)}

        return {"session_id": session_id, "removed": removed}


class WorktreeMergeTool:
    name = "worktree_merge"
    description = (
        "Merge the current session's worktree branch into a target branch (default: main). "
        "Commits any pending changes first. Returns the merge commit SHA."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        from ..services.ai_marking import commit_message_with_trailers, marking_facts
        from ..services.worktree import worktree_service

        session_id = str(context.session_id or "default")
        target_branch = str(params.get("target_branch") or "main")
        facts = await marking_facts(context)
        try:
            sha = await worktree_service.merge_into_main(
                session_id, target_branch, mark_message=lambda message: commit_message_with_trailers(message, facts)
            )
        except Exception as e:
            return {"error": str(e)}

        return {"session_id": session_id, "merged_into": target_branch, "sha": sha}
