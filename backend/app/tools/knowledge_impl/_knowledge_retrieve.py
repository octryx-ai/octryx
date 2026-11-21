"""Hybrid knowledge retrieval tool: chunks + graph (+ communities) in one call."""

from __future__ import annotations

from typing import Any

from app.tools.context import ToolContext

from ...models import Project
from ...services.error_facts import error_text
from ...services.knowledge_access_policy import load_knowledge_access_policy
from ...services.knowledge_graph import (
    ROLE_SUMMARIZE,
    build_generate_fn,
    search_communities,
)
from ...services.knowledge_graph.communities import global_search
from ...services.knowledge_graph.llm_runtime import KnowledgeLLMUnavailableError
from ...services.knowledge_retrieval import (
    MODE_LOCAL,
    MODE_MIX,
    MODE_NAIVE,
    build_context_block,
    retrieve_knowledge,
)
from ._knowledge_workspace_scope import knowledge_workspace_scope

MODE_GLOBAL = "global"
_MODES = {MODE_NAIVE, MODE_LOCAL, MODE_MIX, MODE_GLOBAL}

# The registered provider-dispatch owner the global synthesis acts as; the same key
# names the refusal when a cross-Workspace project id is rejected here.
DISPATCH_OWNER = "knowledge_graph_runtime"


class KnowledgeRetrieveTool:
    name = "knowledge_retrieve"
    description = (
        "Hybrid knowledge retrieval over the project's knowledge base: passages (chunks), "
        "graph entities with their relationships, and community summaries."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if context.db is None:
            return {"error": "Database session is required"}
        # Authorize the raw model argument against the server-stamped turn
        # Workspace before it can become a database lookup key. Missing turn
        # context and foreign ids are typed zero-dispatch outcomes.
        scope = knowledge_workspace_scope(context, project_id=params.get("project_id"))
        if not scope.allowed:
            return scope.denial_result(owner=DISPATCH_OWNER)
        project = await context.db.get(Project, scope.selected_project_id)
        if not project or not project.is_active:
            return {"error": "project_id is required when no single active project is available"}
        query = str(params.get("query") or "").strip()
        if not query:
            return {"error": "query is required"}

        access_policy = await load_knowledge_access_policy(context.db, project_id=project.id)
        project_ids = list(access_policy.candidate_project_ids or [project.id])

        mode = str(params.get("mode") or MODE_MIX).strip().lower()
        if mode not in _MODES:
            mode = MODE_MIX
        limit = max(1, min(int(params.get("limit") or 8), 25))

        result: dict[str, Any] = {
            "project_id": project.id,
            "query": query,
            "mode": mode,
            "keywords": {},
            "chunks": [],
            "entities": [],
            "relations": [],
            "facts": [],
            "communities": [],
            "global_answer": None,
        }

        if mode in (MODE_NAIVE, MODE_LOCAL, MODE_MIX):
            retrieved = await retrieve_knowledge(
                context.db,
                query=query,
                project_ids=project_ids,
                mode=mode,
                chunk_limit=limit,
                node_limit=limit,
            )
            result["keywords"] = retrieved["keywords"]
            result["chunks"] = retrieved["chunks"]
            result["entities"] = retrieved["entities"]
            result["relations"] = retrieved["relations"]
            result["facts"] = retrieved["facts"]

        if mode in (MODE_GLOBAL, MODE_MIX):
            result["communities"] = await search_communities(
                context.db, query=query, project_ids=project_ids, limit=min(limit, 5)
            )
        if mode == MODE_GLOBAL:
            # Whole-system question: synthesize across community reports with the
            # governed summarize runtime; fall back to listing reports when no
            # runtime is configured (logged, explicit).
            try:
                generate = await build_generate_fn(
                    context.db,
                    # The turn's own Workspace first, then the whole federated
                    # candidate set: a global synthesis reads all of them, so an
                    # alias must be admitted by all of them.
                    project_ids=[*scope.anchor_ids, *project_ids],
                    role=ROLE_SUMMARIZE,
                    max_tokens=900,
                    require_role_match=True,
                )
                synthesis = await global_search(
                    context.db, query=query, generate=generate, project_ids=project_ids
                )
                result["global_answer"] = synthesis["answer"] or None
                result["communities_used"] = synthesis["communities_used"]
            except KnowledgeLLMUnavailableError as exc:
                # A Workspace-policy refusal keeps its typed payload instead of
                # being flattened into a free-text error the model has to guess at.
                admission = exc.to_result()
                if admission:
                    result["global_answer_admission"] = admission
                    result["global_answer_error"] = exc.state_reason
                else:
                    # Platform-authored facts (typed runtime failure or configuration gap).
                    result["global_answer_error"] = f"{type(exc).__name__}: {exc}"
            except Exception as exc:  # noqa: BLE001 - synthesis is best-effort
                result["global_answer_error"] = error_text("global_synthesis_failed", exc)

        context_sections = [build_context_block(result)]
        if result["global_answer"]:
            context_sections.insert(0, f"System answer:\n{result['global_answer']}")
        elif result["communities"]:
            community_lines = "\n".join(
                f"- {community['title']}: {community['summary']}" for community in result["communities"]
            )
            context_sections.insert(0, f"System overview:\n{community_lines}")
        result["context"] = "\n\n".join(section for section in context_sections if section).strip()
        result["counts"] = {
            "chunks": len(result["chunks"]),
            "entities": len(result["entities"]),
            "relations": len(result["relations"]),
            "facts": len(result["facts"]),
            "communities": len(result["communities"]),
        }
        return result
