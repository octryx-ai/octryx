"""Sub-agent spawning tool – fan out delegated child runs from within a parent agent."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.agent_reply_contract_schema import REPLY_CONTRACT_PAYLOAD_KEY

from .. import db as db_runtime
from ..models import Message, Session, SubAgentGroup, ToolCall
from ..services.answer_evidence.child_evidence import child_evidence_sources
from ..services.prompt_catalog import render_prompt
from ..services.run_capability.sub_agent_capability import sub_agent_session_capability_metadata
from ..services.session.run_state import RUN_STATUS_AWAITING_SUBAGENTS, set_session_run_state
from ..services.session.turn_runtime_selection import RUNTIME_SELECTION_SOURCE_METADATA_KEY, RuntimeSelectionSource
from ..services.sub_agent_group import (
    DEFAULT_SUB_AGENT_GROUP_TIMEOUT_SECONDS,
    MAX_SUB_AGENT_GROUP_TIMEOUT_SECONDS,
    create_sub_agent_group,
    launch_sub_agent_group,
)
from ..services.sub_agent_group.evidence import (
    build_sub_agent_evidence_record,
    determine_sub_agent_evidence_profile,
)
from ..services.subtask_merge_contract import build_subtask_merge_contract, persist_subtask_merge_contract
from ..services.workspace_composition import (
    build_sub_agent_workspace_execution_view,
    get_workspace_default_runtime_target_id,
)
from .context import ToolContext

_DEFAULT_SUB_AGENT_RUNTIME_TIMEOUT_SECONDS = 30
_DEFAULT_CODING_MIGRATION_SUB_AGENT_RUNTIME_TIMEOUT_SECONDS = 180


class SpawnSubAgentTool:
    name = "spawn_sub_agent"
    description = "Spawn multiple sub-agents in parallel to work on independent sub-tasks concurrently. Use this when a task can be split into independent workloads (e.g. one sub-agent per folder, per service, per ticket). Results are aggregated and returned together."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        sub_tasks: list[str] = params.get("sub_tasks") or []
        if not sub_tasks:
            return {"error": "sub_tasks list is required and must not be empty"}

        if len(sub_tasks) > 10:
            return {"error": "Maximum 10 sub-tasks per spawn call to prevent runaway parallelism"}

        if context.sub_agent_depth >= 1:
            return {"error": "Sub-agent depth limit reached (max 1 level). Sub-agents cannot spawn further sub-agents."}

        if await _should_keep_java_spring_migration_local(context):
            return {
                "status": "blocked",
                "error": render_prompt("research.spawn.blocked_error"),
                "recommended_next_step": render_prompt("research.spawn.blocked_next_step"),
            }

        inherit_agent_definition = bool(params.get("inherit_agent_definition", True))
        child_agent_type = str(params.get("child_agent_type") or "").strip()
        inherited_agent_type = str((context.agent_definition or {}).get("agentType") or "").strip()
        effective_child_agent_type = child_agent_type or inherited_agent_type or _parent_agent_type(context)
        requested_max_concurrent = params.get("max_concurrent")
        min_sources_per_child = _coerce_positive_int(params.get("min_sources_per_child"), default=1)
        child_runtime_timeout_seconds = _coerce_positive_int(
            params.get("child_runtime_timeout_seconds"),
            default=_default_child_runtime_timeout_seconds(
                child_agent_type=effective_child_agent_type,
                context=context,
            ),
            maximum=300,
        )
        requested_group_timeout_seconds = (
            params.get("child_group_timeout_seconds")
            or params.get("group_timeout_seconds")
            or params.get("timeout_seconds")
        )
        child_allowed_tools = [
            str(item).strip() for item in (params.get("child_allowed_tools") or []) if str(item).strip()
        ]
        resume_prompt = str(params.get("resume_prompt") or "").strip() or None
        child_agent_definition = context.agent_definition if inherit_agent_definition else None
        if isinstance(child_agent_definition, dict) and REPLY_CONTRACT_PAYLOAD_KEY in child_agent_definition:
            # A child answers its parent as a tool result; only the parent's own final reply is checked.
            child_agent_definition = {
                key: value for key, value in child_agent_definition.items() if key != REPLY_CONTRACT_PAYLOAD_KEY
            }
        if child_agent_definition is None and child_allowed_tools:
            child_agent_definition = _build_bounded_child_agent_definition(
                child_agent_type=effective_child_agent_type,
                allowed_tools=child_allowed_tools,
                min_sources_per_child=min_sources_per_child,
            )
        parent_workspace_execution_view = None
        if isinstance(context.project_config, dict):
            raw_view = context.project_config.get("workspace_execution_view")
            if isinstance(raw_view, dict):
                parent_workspace_execution_view = raw_view
        child_workspace_execution_view = build_sub_agent_workspace_execution_view(
            parent_workspace_execution_view,
            child_agent_type=effective_child_agent_type,
            inherited_agent_definition=child_agent_definition,
        )
        child_runtime_target_id = await _resolve_child_runtime_target_id(
            db=context.db,
            child_agent_type=effective_child_agent_type,
            turn_context_snapshot=context.turn_context_snapshot,
            workspace_execution_view=child_workspace_execution_view,
        )
        max_concurrent_children = _resolve_max_concurrent_children(
            requested_max_concurrent=requested_max_concurrent,
            child_count=len(sub_tasks),
        )
        child_group_timeout_seconds = _resolve_child_group_timeout_seconds(
            requested_timeout_seconds=requested_group_timeout_seconds,
            child_runtime_timeout_seconds=child_runtime_timeout_seconds,
            child_count=len(sub_tasks),
            max_concurrent_children=max_concurrent_children,
            min_sources_per_child=min_sources_per_child,
        )

        parent_engineering_resolution = _parent_engineering_knowledge_resolution(context)
        child_metadata_context = _build_child_engineering_metadata(parent_engineering_resolution)
        sub_session_ids: list[str] = []
        child_runs: list[dict[str, str]] = []

        for task in sub_tasks:
            child_task = _build_child_task(
                task,
                parent_request=context.current_user_message,
                engineering_resolution=parent_engineering_resolution,
            )
            sub_session = Session(
                id=str(uuid.uuid4()),
                user_id=context.user_id,
                project_id=(context.project_config or {}).get("project_id"),
                agent_type=effective_child_agent_type,
                status="active",
                origin="sub_agent",
                metadata_={
                    "title": f"Sub-agent: {task[:80]}",
                    "trigger": "sub_agent",
                    "allow_workflow_contracts": False,
                    "runtime_target_id": child_runtime_target_id or None,
                    # The child keeps the runtime it was started on for its later turns.
                    **({RUNTIME_SELECTION_SOURCE_METADATA_KEY: RuntimeSelectionSource.SESSION.value}
                       if child_runtime_target_id else {}),
                    "runtime_request_timeout_seconds": child_runtime_timeout_seconds,
                    "workspace_execution_view": child_workspace_execution_view,
                    **child_metadata_context,
                    # The child's profile derives from this turn's enforced class, tightening only.
                    **sub_agent_session_capability_metadata(context),
                },
                parent_session_id=context.session_id,
                sub_agent_depth=context.sub_agent_depth + 1,
            )
            context.db.add(sub_session)
            sub_session_ids.append(sub_session.id)
            child_runs.append({"session_id": sub_session.id, "task": child_task})

        group = await create_sub_agent_group(
            context.db,
            parent_session_id=context.session_id,
            child_session_ids=sub_session_ids,
            timeout_seconds=child_group_timeout_seconds,
            resume_prompt=resume_prompt,
        )
        parent_session = await context.db.get(Session, context.session_id)
        if parent_session is not None:
            parent_session.status = "awaiting_subagents"
            metadata = dict(parent_session.metadata_ or {})
            metadata["current_sub_agent_group_id"] = group.id
            metadata["sub_agent_group_child_session_ids"] = list(sub_session_ids)
            parent_session.metadata_ = metadata
            set_session_run_state(parent_session, RUN_STATUS_AWAITING_SUBAGENTS, "waiting_for_sub_agents")
            context.db.add(parent_session)
        await context.db.commit()

        session_factory = async_sessionmaker(bind=context.db.bind, class_=AsyncSession, expire_on_commit=False)
        await launch_sub_agent_group(
            session_factory=session_factory,
            group_id=group.id,
            parent_session_id=context.session_id,
            user_id=context.user_id,
            project_id=(context.project_config or {}).get("project_id"),
            agent_type=effective_child_agent_type,
            runtime_target_id=child_runtime_target_id or None,
            thinking_level=str((context.turn_context_snapshot or {}).get("thinking_level") or "").strip() or None,
            agent_definition=child_agent_definition,
            sub_agent_depth=context.sub_agent_depth + 1,
            child_runs=child_runs,
            max_concurrent_children=max_concurrent_children,
        )

        return {
            "status": "awaiting_subagents",
            "sub_agent_group_id": group.id,
            "sub_session_ids": sub_session_ids,
            "count": len(sub_session_ids),
            "completed": 0,
            "failed": 0,
            "timeout_seconds": child_group_timeout_seconds,
            "message": render_prompt("research.spawn.spawned_message", count=len(sub_session_ids)),
        }


def _resolve_max_concurrent_children(*, requested_max_concurrent: Any, child_count: int) -> int | None:
    if child_count <= 0:
        return None
    # SQLite is the default local/runtime database for this repository. Its write
    # concurrency is materially weaker than Postgres, and parallel delegated child
    # runs have already proven able to deadlock on session/message/tool persistence.
    # Keep the delegated flow correct on SQLite by serializing child execution there.
    if db_runtime._is_sqlite:
        return 1
    try:
        parsed = int(requested_max_concurrent)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return max(1, min(parsed, child_count, 5))


def _resolve_child_group_timeout_seconds(
    *,
    requested_timeout_seconds: Any,
    child_runtime_timeout_seconds: int,
    child_count: int,
    max_concurrent_children: int | None,
    min_sources_per_child: int,
) -> int:
    if requested_timeout_seconds not in (None, "", 0, "0"):
        return _coerce_positive_int(
            requested_timeout_seconds,
            default=DEFAULT_SUB_AGENT_GROUP_TIMEOUT_SECONDS,
            maximum=MAX_SUB_AGENT_GROUP_TIMEOUT_SECONDS,
        )
    child_limit = max(1, int(max_concurrent_children or child_count or 1))
    waves = max(1, (max(child_count, 1) + child_limit - 1) // child_limit)
    iteration_budget = max(3, min_sources_per_child + 2)
    derived = max(
        DEFAULT_SUB_AGENT_GROUP_TIMEOUT_SECONDS,
        int(child_runtime_timeout_seconds) * iteration_budget * waves + 60,
    )
    return _coerce_positive_int(
        derived,
        default=DEFAULT_SUB_AGENT_GROUP_TIMEOUT_SECONDS,
        maximum=MAX_SUB_AGENT_GROUP_TIMEOUT_SECONDS,
    )


def _coerce_positive_int(value: Any, *, default: int, maximum: int | None = None) -> int:
    try:
        resolved = int(value)
    except (TypeError, ValueError):
        resolved = default
    resolved = max(1, resolved)
    if maximum is not None:
        resolved = min(resolved, maximum)
    return resolved


def _parent_agent_type(context: ToolContext) -> str:
    for candidate in (
        context.agent_mode_key,
        context.capability_type,
        (context.project_config or {}).get("selected_agent_type"),
    ):
        normalized = str(candidate or "").strip()
        if normalized:
            return normalized
    return "diagnosis"


def _default_child_runtime_timeout_seconds(*, child_agent_type: str, context: ToolContext) -> int:
    if str(child_agent_type or "").strip().lower() == "coding" and _parent_has_coding_migration_context(context):
        return _DEFAULT_CODING_MIGRATION_SUB_AGENT_RUNTIME_TIMEOUT_SECONDS
    return _DEFAULT_SUB_AGENT_RUNTIME_TIMEOUT_SECONDS


def _parent_has_coding_migration_context(context: ToolContext) -> bool:
    resolution = _parent_engineering_knowledge_resolution(context)
    prompt_contract = resolution.get("prompt_contract")
    if isinstance(prompt_contract, dict) and str(prompt_contract.get("intent") or "").strip() == "coding_migration":
        return True
    prompt = str(context.current_user_message or "").lower()
    return any(marker in prompt for marker in ("migrate", "migration", "upgrade")) and any(
        marker in prompt for marker in ("java", "spring boot", "springboot")
    )


async def _should_keep_java_spring_migration_local(context: ToolContext) -> bool:
    if not context.db or not context.session_id or not _parent_has_coding_migration_context(context):
        return False

    group_ids = list(
        (
            await context.db.execute(
                select(SubAgentGroup.id).where(SubAgentGroup.parent_session_id == context.session_id)
            )
        ).scalars()
    )
    if not group_ids:
        return False

    tool_names = {
        str(tool_name or "").strip()
        for tool_name in (
            await context.db.execute(select(ToolCall.tool_name).where(ToolCall.session_id == context.session_id))
        ).scalars()
    }
    return bool(
        "get_context_from_subthreads" in tool_names
        or tool_names
        & {
            "run_openrewrite_recipe",
            "edit_workspace_file",
            "run_test_suite",
            "get_git_diff",
        }
    )


def _parent_engineering_knowledge_resolution(context: ToolContext) -> dict[str, Any]:
    resolution = (context.project_config or {}).get("engineering_knowledge_runtime_resolution")
    return dict(resolution) if isinstance(resolution, dict) else {}


def _build_child_engineering_metadata(resolution: dict[str, Any]) -> dict[str, Any]:
    if not resolution:
        return {}
    metadata: dict[str, Any] = {
        "parent_engineering_knowledge_runtime_resolution": resolution,
    }
    repository = resolution.get("repository")
    if isinstance(repository, dict):
        repository_id = str(repository.get("id") or "").strip()
        repository_root = str(repository.get("repo_root") or "").strip()
        if repository_id:
            metadata["code_repository_id"] = repository_id
        if repository_root:
            metadata["engineering_knowledge_repo_search_roots"] = [repository_root]
    return metadata


def _build_child_task(
    task: Any,
    *,
    parent_request: str | None,
    engineering_resolution: dict[str, Any],
) -> str:
    task_text = str(task or "").strip()
    if not engineering_resolution:
        return task_text
    context_lines = _engineering_resolution_context_lines(engineering_resolution)
    if not context_lines:
        return task_text
    lines = [render_prompt("research.child.preamble")]
    if parent_request:
        lines.append(render_prompt("research.child.parent_request_line", parent_request=str(parent_request).strip()))
    lines.extend(context_lines)
    lines.extend(["", render_prompt("research.child.task_header"), task_text])
    return "\n".join(lines).strip()


def _engineering_resolution_context_lines(resolution: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    prompt_contract = resolution.get("prompt_contract")
    if isinstance(prompt_contract, dict):
        intent = str(prompt_contract.get("intent") or "").strip()
        stack_key = str(prompt_contract.get("stack_key") or "").strip()
        source_versions = prompt_contract.get("source_versions")
        target_versions = prompt_contract.get("target_versions")
        if intent:
            lines.append(f"Intent: {intent}")
        if stack_key:
            lines.append(f"Stack: {stack_key}")
        if isinstance(source_versions, dict) and source_versions:
            lines.append(f"Source versions: {source_versions}")
        if isinstance(target_versions, dict) and target_versions:
            lines.append(f"Target versions: {target_versions}")
    repository = resolution.get("repository")
    if isinstance(repository, dict):
        repo_name = str(repository.get("name") or "").strip()
        repo_root = str(repository.get("repo_root") or "").strip()
        if repo_name or repo_root:
            lines.append(f"Repository: {repo_name or 'unknown'} ({repo_root or 'unknown root'})")
    pack = resolution.get("engineering_knowledge_pack")
    if isinstance(pack, dict):
        pack_key = str(pack.get("pack_key") or "").strip()
        version = str(pack.get("version") or pack.get("version_id") or "").strip()
        quality_status = str(pack.get("quality_status") or "").strip()
        if pack_key:
            lines.append(
                f"Resolved migration knowledge baseline: {pack_key} "
                f"v{version or 'unknown'} ({quality_status or 'unknown'})"
            )
    return lines


def _build_bounded_child_agent_definition(
    *,
    child_agent_type: str,
    allowed_tools: list[str],
    min_sources_per_child: int = 1,
) -> dict[str, Any]:
    normalized_tools = {str(tool_name or "").strip() for tool_name in allowed_tools if str(tool_name or "").strip()}
    normalized_agent_type = str(child_agent_type or "").strip().lower()
    # A delegated worker with tools must use them before it reports back; one without tools answers in text.
    tool_use = "required" if normalized_tools else "optional"
    if normalized_agent_type in {"coding", "change"}:
        return {
            "name": "Delegated Coding Worker",
            "agentType": child_agent_type,
            "prompt": render_prompt("research.child.coding.prompt"),
            "steps": [
                {
                    "name": "Inspect Delegated Coding Scope",
                    "stepType": "analysis",
                    "instructions": render_prompt("research.child.coding.instructions"),
                    "successCriteria": render_prompt("research.child.coding.success"),
                    "allowedTools": allowed_tools,
                    "stepConfig": {"tool_use": tool_use, "max_iterations": 4, "max_transitional_responses": 1},
                    "isEnabled": True,
                }
            ],
        }

    min_sources_per_child = _coerce_positive_int(min_sources_per_child, default=1)
    if min_sources_per_child > 1:
        source_goal = render_prompt(
            "research.child.source_goal.multiple", min_sources_per_child=min_sources_per_child
        )
        success_goal = render_prompt(
            "research.child.success_goal.multiple", min_sources_per_child=min_sources_per_child
        )
    else:
        source_goal = render_prompt("research.child.source_goal.single")
        success_goal = render_prompt("research.child.success_goal.single")
    search_first_guidance = ""
    if "web_search" in normalized_tools or "codesearch" in normalized_tools:
        search_first_guidance = render_prompt("research.child.search_first_guidance", source_goal=source_goal)
    return {
        "name": "Delegated Sub-task Worker",
        "agentType": child_agent_type,
        "prompt": render_prompt("research.child.research.prompt", search_first_guidance=search_first_guidance),
        "steps": [
            {
                "name": "Gather Delegated Evidence",
                "stepType": "analysis",
                "instructions": render_prompt("research.child.research.instructions", source_goal=source_goal),
                "successCriteria": render_prompt("research.child.research.success", success_goal=success_goal),
                "allowedTools": allowed_tools,
                "stepConfig": {
                    "tool_use": tool_use,
                    "max_iterations": max(3, min_sources_per_child + 2),
                    "max_transitional_responses": 2,
                },
                "isEnabled": True,
            }
        ],
    }


async def _resolve_child_runtime_target_id(
    *,
    db: AsyncSession | None,
    child_agent_type: str,
    turn_context_snapshot: dict[str, Any] | None,
    workspace_execution_view: dict[str, Any] | None,
) -> str:
    explicit_runtime_target_id = str((turn_context_snapshot or {}).get("runtime_target_id") or "").strip()
    if explicit_runtime_target_id:
        return explicit_runtime_target_id

    workspace_runtime_target_id = get_workspace_default_runtime_target_id(workspace_execution_view)
    if workspace_runtime_target_id:
        return workspace_runtime_target_id

    # Otherwise automatic: the platform order, bounded by the Workspace's allowed, cleared models when the child
    # run is prepared (model_selection.chain_admission). Use-case tags do not pick a model.
    return ""


def _truncate_subthread_text(value: Any, limit: int = 600) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


class GetContextFromSubthreadsTool:
    name = "get_context_from_subthreads"
    description = (
        "Collect a compact context summary from child sessions spawned from the current session. "
        "Use this after `spawn_sub_agent` to consolidate what each sub-agent found before you write the final answer."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if not context.db or not context.session_id:
            return {"error": "No active database session"}

        parent_session_id = str(params.get("parent_session_id") or context.session_id or "").strip()
        if not parent_session_id:
            return {"error": "parent_session_id is required"}

        session_ids = [str(item).strip() for item in (params.get("session_ids") or []) if str(item).strip()]
        include_tool_names = bool(params.get("include_tool_names", True))

        if parent_session_id != context.session_id:
            return {"error": "get_context_from_subthreads may only inspect child sessions of the current session"}

        parent_session = await context.db.get(Session, parent_session_id)
        evidence_profile = determine_sub_agent_evidence_profile(parent_session)

        stmt = select(Session).where(Session.parent_session_id == parent_session_id).order_by(Session.started_at.asc())
        child_sessions = (await context.db.execute(stmt)).scalars().all()
        if session_ids:
            allowed_ids = set(session_ids)
            child_sessions = [row for row in child_sessions if row.id in allowed_ids]

        if not child_sessions:
            return {
                "parent_session_id": parent_session_id,
                "evidence_profile": evidence_profile,
                "count": 0,
                "subthreads": [],
                "accepted_subthreads": [],
                "rejected_subthreads": [],
                "accepted_count": 0,
                "rejected_count": 0,
                "summary": {
                    "completed": 0,
                    "failed": 0,
                    "active": 0,
                    "accepted": 0,
                    "rejected": 0,
                },
            }

        child_ids = [row.id for row in child_sessions]
        messages = (
            (
                await context.db.execute(
                    select(Message).where(Message.session_id.in_(child_ids)).order_by(Message.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        tool_calls = (
            (
                await context.db.execute(
                    select(ToolCall).where(ToolCall.session_id.in_(child_ids)).order_by(ToolCall.created_at.asc())
                )
            )
            .scalars()
            .all()
        )

        messages_by_session: dict[str, list[Message]] = {}
        for message in messages:
            messages_by_session.setdefault(message.session_id, []).append(message)
        tool_calls_by_session: dict[str, list[ToolCall]] = {}
        for call in tool_calls:
            tool_calls_by_session.setdefault(call.session_id, []).append(call)

        accepted_subthreads: list[dict[str, Any]] = []
        rejected_subthreads: list[dict[str, Any]] = []
        workflow_contract = (
            parent_session.metadata_.get("workflow_contract")
            if parent_session is not None and isinstance(parent_session.metadata_, dict)
            else {}
        )
        delegated_topic = str((workflow_contract or {}).get("topic") or "").strip()
        for row in child_sessions:
            session_messages = messages_by_session.get(row.id, [])
            session_tool_calls = tool_calls_by_session.get(row.id, [])
            first_user = next(
                (msg for msg in session_messages if msg.role == "user" and str(msg.content or "").strip()), None
            )
            last_assistant = next(
                (
                    msg
                    for msg in reversed(session_messages)
                    if msg.role == "assistant" and str(msg.content or "").strip()
                ),
                None,
            )
            tool_names = []
            if include_tool_names:
                seen_tools: set[str] = set()
                for call in session_tool_calls:
                    tool_name = str(call.tool_name or "").strip()
                    if not tool_name or tool_name in seen_tools:
                        continue
                    seen_tools.add(tool_name)
                    tool_names.append(tool_name)

            metadata = dict(row.metadata_ or {})
            evidence_record = build_sub_agent_evidence_record(
                profile=evidence_profile,
                topic=delegated_topic,
                session=row,
                title=metadata.get("title"),
                task=_truncate_subthread_text((first_user.content if first_user else metadata.get("title") or ""), 220),
                final_response=_truncate_subthread_text(last_assistant.content if last_assistant else "", 900),
                tool_calls=session_tool_calls,
                include_tool_names=include_tool_names,
                message_count=len(session_messages),
            )
            if evidence_record["quality"]["accepted"]:
                # The child's sources join the parent's turn evidence (the answer guard checks the union).
                evidence_record["evidence_sources"] = child_evidence_sources(session_tool_calls)
                accepted_subthreads.append(evidence_record)
            else:
                rejected_subthreads.append(evidence_record)

        if parent_session is not None:
            merge_contract = build_subtask_merge_contract(
                parent_session=parent_session,
                child_sessions=child_sessions,
                accepted_subthreads=accepted_subthreads,
                rejected_subthreads=rejected_subthreads,
                tool_calls_by_session=tool_calls_by_session,
            )
            persist_subtask_merge_contract(parent_session, merge_contract)
            metadata = dict(parent_session.metadata_ or {})
            metadata.pop("current_sub_agent_group_id", None)
            metadata.pop("sub_agent_group_child_session_ids", None)
            metadata["subtask_merge_contract"] = merge_contract
            parent_session.metadata_ = metadata
            context.db.add(parent_session)
            await context.db.commit()
        else:
            merge_contract = build_subtask_merge_contract(
                parent_session=parent_session,
                child_sessions=child_sessions,
                accepted_subthreads=accepted_subthreads,
                rejected_subthreads=rejected_subthreads,
                tool_calls_by_session=tool_calls_by_session,
            )

        return {
            "parent_session_id": parent_session_id,
            "evidence_profile": evidence_profile,
            "count": len(child_sessions),
            "accepted_count": len(accepted_subthreads),
            "rejected_count": len(rejected_subthreads),
            "merge_contract": merge_contract,
            "subthreads": accepted_subthreads,
            "accepted_subthreads": accepted_subthreads,
            "rejected_subthreads": rejected_subthreads,
            "summary": {
                "completed": sum(1 for row in child_sessions if str(row.status or "").strip().lower() == "completed"),
                "failed": sum(
                    1 for row in child_sessions if str(row.status or "").strip().lower() in {"failed", "error"}
                ),
                "active": sum(1 for row in child_sessions if str(row.status or "").strip().lower() == "active"),
                "accepted": len(accepted_subthreads),
                "rejected": len(rejected_subthreads),
                "tool_names": sorted(
                    {
                        tool
                        for item in accepted_subthreads + rejected_subthreads
                        for tool in (item.get("tool_names") or [])
                    }
                ),
            },
        }
