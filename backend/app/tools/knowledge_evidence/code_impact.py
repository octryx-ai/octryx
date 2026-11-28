"""``knowledge_code_impact``: where a version change applies in a codebase."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...services.knowledge.code.codebase import Codebase, CodebaseRefusal, resolve_codebase
from ...services.knowledge.ledger.errors import EvidenceLedgerError
from ...services.knowledge.retrieval.locator import SourceRefs, within_budget
from ...services.knowledge.runtime import get_evidence_runtime
from ...services.knowledge.sources.repository_snapshot.remote import repository_location_link
from ...services.knowledge.sources.repository_snapshot.session_target import session_repository_target
from ...services.knowledge.temporal.errors import GraphStoreError
from ..context import ToolContext
from ..runtime_impl._runtime_cwd_resolution import _resolve_cwd
from ._scope import failure, knowledge_scope

MAX_LOCATIONS_SHOWN = 8


def _text_param(params: dict, name: str) -> str | None | bool:
    value = params.get(name)
    if value is None:
        return None
    if type(value) is not str:
        return False
    return value.strip() or None


def _explicit_root(path: str, context: ToolContext) -> Path | None:
    try:
        root = _resolve_cwd(context.workspace_root, path, context=context, allow_repo_fallback=True)
    except ValueError:
        return None
    return root if root.is_dir() else None


_REFUSAL_MESSAGES = {
    "needs_clarification": "Several repository sources are in this Workspace; name one as repository.",
    "needs_configuration": "No synced repository source or checkout is available for this Workspace.",
    "invalid_request": "The path or repository is not one this Workspace has.",
}


def _refused(refusal: CodebaseRefusal) -> dict[str, Any]:
    return {
        "error": _REFUSAL_MESSAGES.get(refusal.state, _REFUSAL_MESSAGES["invalid_request"]),
        "state": refusal.state,
        "reason": refusal.reason,
        "repositories": list(refusal.candidates),
    }


class KnowledgeCodeImpactTool:
    name = "knowledge_code_impact"
    description = (
        "List the places in the session's repository checkout or the Workspace's repository source that a "
        "product version change applies to, each with its cited change fact. Read-only. "
        "In the answer, cite each affected repository file using the item's links at the recorded commit, "
        "alongside the change-fact source. A migration-guide link alone does not locate the code impact."
    )

    def __init__(self, *, session_key: str | None = None) -> None:
        # The launcher session key of an MCP connection (never a tool argument); ``None`` in the chat.
        self._session_key = session_key

    async def _codebase(self, params: dict, context: ToolContext, project_id: str) -> Codebase | dict[str, Any]:
        path, repository = _text_param(params, "path"), _text_param(params, "repository")
        if path is False or repository is False:
            return failure("invalid_request")
        explicit_root = None
        if path is not None and path != ".":
            explicit_root = _explicit_root(path, context)
            if explicit_root is None:
                return failure("invalid_request")
        session_root = Path(context.workspace_root).resolve() if context.workspace_root else None
        session_target = None
        if self._session_key:
            session_target = await session_repository_target(
                context.db, user_id=str(context.user_id), workspace_id=project_id, session_key=self._session_key
            )
        resolved = await resolve_codebase(
            context.db,
            project_id=project_id,
            explicit_root=explicit_root,
            repository=repository,
            session_root=session_root,
            session_target=session_target,
        )
        return _refused(resolved) if isinstance(resolved, CodebaseRefusal) else resolved

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        scope = await knowledge_scope(params, context)
        if type(scope) is dict:
            return scope
        codebase = await self._codebase(params, context, scope.primary.project_id)
        if type(codebase) is dict:
            return codebase
        from ...services.knowledge.code.service import code_impact

        try:
            result = await code_impact(
                context.db,
                runtime=get_evidence_runtime(),
                scope=scope,
                codebase=codebase,
                product=params.get("product"),
                to_version=params.get("to_version"),
                from_version=params.get("from_version"),
            )
        except EvidenceLedgerError as error:
            return failure(error.state.value)
        except GraphStoreError:
            return failure("unavailable")
        blobs = {}
        if codebase.repository is not None:
            from app.services.knowledge.code.repository_reads import indexed_blobs

            paths = {loc.path for item in result.items for loc in item.locations}
            blobs = await indexed_blobs(context.db, connector_id=codebase.repository.connector_id, paths=paths)
        return _answer(result, scope, codebase, blobs)


def _answer(result, scope, codebase: Codebase, blobs: dict[str, str] | None = None) -> dict[str, Any]:
    sources = SourceRefs()
    repository = codebase.repository
    impact_all = []
    for item in result.items:
        shown = item.locations[:MAX_LOCATIONS_SHOWN]
        entry = {
            "kind": item.fact.relation,
            "fact": item.fact.fact,
            "version": item.fact.version,
            "reason": item.reason,
            "source": sources.ref(item.fact.citation),
            # path:line, the element found there
            "at": [f"{loc.path}:{loc.line} {loc.value}" for loc in shown],
            "more_locations": max(0, len(item.locations) - MAX_LOCATIONS_SHOWN),
        }
        if repository is not None:
            # The file at the commit, opened at the line: the host blob, else the platform viewer.
            workspace_id = scope.primary.project_id
            entry["links"] = [
                repository_location_link(repository, workspace_id, loc.path, loc.line, (blobs or {}).get(loc.path))
                for loc in shown
            ]
        impact_all.append(entry)
    impact = within_budget(impact_all, reserve=2500)
    answer: dict[str, Any] = {
        "state": result.state,
        "product": result.product,
        "from_version": result.from_version,
        "to_version": result.to_version,
        "codebase": codebase.kind,
        "commit": result.commit,
        # The Workspace whose change facts were joined: the session's own, or a bound library.
        "facts_workspace": scope.name_of(result.facts_workspace_id),
        "elements_scanned": result.elements_scanned,
        "facts_considered": result.facts_considered,
        "impacted_fact_count": len(impact_all),
        "impacted_facts_not_shown": len(impact_all) - len(impact),
        "impact": impact,
        # Cite a change by copying the cite_as of its source.
        "sources": sources.listing(),
    }
    if repository is not None:
        answer["repository"] = {"key": repository.connector_key, "url": repository.repository_url}
    return answer


__all__ = ["KnowledgeCodeImpactTool"]
