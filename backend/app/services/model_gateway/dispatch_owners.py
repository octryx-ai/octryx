"""Pinned inventory of every provider-dispatch owner in the backend.

A provider client is a billable, policy-bearing resource, so "who may build one
and on whose behalf" is a product fact rather than an implementation detail. This
module states that fact once:

- ``authority`` — the engine runtime chain. It *consumes* the admission contract
  (``agent/core/runtime/runtime_admission_contract.py``) and must never resolve a
  project itself; the caller that owns the turn does that.
- ``admitted`` — an auxiliary owner that dispatches a chat. It must obtain its
  admission from :mod:`.dispatch_admission` before it constructs a client.
- ``catalog_only`` — a provider-scoped admin surface. It builds a client to read
  the model catalog or readiness and never chats, so the deny-everything
  unverified admission is the correct value for it.

The inventory is enforced from two sides. At runtime
:func:`dispatch_owner` refuses an unregistered key, so an owner cannot reach the
admission boundary without declaring itself. In the suite
``tests/model_gateway/test_dispatch_owner_inventory.py`` re-derives the dispatch
sites from the source tree and fails when a module dispatches, or builds a
gateway client, without appearing here.
"""

from __future__ import annotations

from collections.abc import Mapping

from .dispatch_owner_record import (
    DISPATCH_MODE_ADMITTED,
    DISPATCH_MODE_AUTHORITY,
    DISPATCH_MODE_CATALOG_ONLY,
    DispatchOwner,
)


def _owner(key: str, category: str, module: str, mode: str, boundary_module: str = "") -> DispatchOwner:
    return DispatchOwner(
        key=key, category=category, module=module, mode=mode, boundary_module=boundary_module
    )


# Keyed by the value an owner passes to the admission boundary. The key is also
# the audited ``dispatch_owner`` evidence value, so it names the boundary that
# resolved the project rather than the file that happened to call it.
DISPATCH_OWNERS: Mapping[str, DispatchOwner] = {
    owner.key: owner
    for owner in (
        _owner(
            "engine_runtime_chain",
            "main chat turn",
            "app/agent/engine/runtime/_engine_runtime_fallback.py",
            DISPATCH_MODE_AUTHORITY,
        ),
        _owner(
            "prepare_agent_run",
            "main chat turn",
            "app/agent/core/context/run_context.py",
            DISPATCH_MODE_ADMITTED,
        ),
        _owner(
            "chat_turn_task_extraction",
            "chat pre-turn task extraction",
            "app/web/_helpers/chat_turn_start.py",
            DISPATCH_MODE_ADMITTED,
        ),
        _owner(
            "knowledge_graph_runtime",
            "knowledge graph extraction/summarization/keywords",
            "app/services/knowledge_graph/llm_runtime.py",
            DISPATCH_MODE_ADMITTED,
        ),
        _owner(
            "knowledge_temporal_graph",
            "knowledge temporal graph extraction (Graphiti)",
            "app/services/knowledge/temporal/graphiti_llm.py",
            DISPATCH_MODE_ADMITTED,
            # Runtime selection and admission (extract tag, Workspace model policy) live here.
            boundary_module="app/services/knowledge/temporal/graph_model_selection.py",
        ),
        _owner(
            "knowledge_research",
            "knowledge package research (source planning and selection)",
            "app/services/knowledge/research/model.py",
            DISPATCH_MODE_ADMITTED,
        ),
        _owner(
            "knowledge_search_answer",
            "knowledge search short cited answer",
            "app/services/knowledge/answer/model.py",
            DISPATCH_MODE_ADMITTED,
        ),
        _owner(
            "knowledge_memory_capture",
            "knowledge memory capture at turn end (off unless the Workspace enables it)",
            "app/services/knowledge/memory/capture_model.py",
            DISPATCH_MODE_ADMITTED,
        ),
        _owner(
            # Dispatches through the Memory capture's bounded client; admitted in its own module.
            "knowledge_episode_summary",
            "knowledge session episode summary at turn end (off unless the Workspace enables it)",
            "app/services/knowledge/memory/capture_model.py",
            DISPATCH_MODE_ADMITTED,
            boundary_module="app/services/knowledge/episodes/summary_model.py",
        ),
        _owner(
            "workflow_proposal",
            "workflow proposal (closed-catalog structured answer, user confirms)",
            "app/services/workflow_routing/proposal_model.py",
            DISPATCH_MODE_ADMITTED,
        ),
        _owner(
            # The independent reviewer of a workflow run; the Workspace is the run's.
            "workflow_run_review",
            "workflow run independent review (no tools, closed verdict)",
            "app/services/workflow_runs/review/model.py",
            DISPATCH_MODE_ADMITTED,
        ),
        _owner(
            # One work item analysis; the Workspace is the item's, the policy its analysis setting.
            "work_item_analysis",
            "work item analysis",
            "app/services/work_item_analysis/governed_run.py",
            DISPATCH_MODE_ADMITTED,
        ),
        _owner(
            "secure_work_plan_worker",
            "secure-work worker",
            "app/services/secure_work/plans/llm_work_plan.py",
            DISPATCH_MODE_ADMITTED,
        ),
        _owner(
            "call_agent",
            "sub-agent/call-agent",
            "app/services/call_agent/service.py",
            DISPATCH_MODE_ADMITTED,
            boundary_module="app/services/call_agent/provider_admission.py",
        ),
        _owner(
            "session_summarizer",
            "summarizer",
            "app/agent/core/runtime/summarizer.py",
            DISPATCH_MODE_ADMITTED,
            boundary_module="app/agent/core/runtime/_summarizer_runtime.py",
        ),
        _owner(
            "security_analyzer_llm_risk",
            "risk analysis",
            "app/services/security_analyzer/llm_risk.py",
            DISPATCH_MODE_ADMITTED,
        ),
        _owner(
            # The inbound Anthropic Messages route an external coding client
            # (octryx-claude) calls; the Workspace comes from the gateway token.
            "model_gateway_inbound_anthropic",
            "external coding client model gateway",
            "app/services/model_gateway/inbound/admission.py",
            DISPATCH_MODE_ADMITTED,
        ),
        _owner(
            "admin_control_plane_model_sync",
            "admin test surface",
            "app/services/admin/provider/admin_control_plane_service.py",
            DISPATCH_MODE_CATALOG_ONLY,
        ),
        _owner(
            "admin_provider_model_sync",
            "admin test surface",
            "app/services/admin/provider/admin_provider_service.py",
            DISPATCH_MODE_CATALOG_ONLY,
        ),
        _owner(
            "provider_model_sync",
            "admin test surface",
            "app/services/provider/service.py",
            DISPATCH_MODE_CATALOG_ONLY,
        ),
        _owner(
            "model_catalog_sync",
            "admin test surface",
            "app/services/model_catalog/sync.py",
            DISPATCH_MODE_CATALOG_ONLY,
        ),
    )
}

DISPATCH_OWNER_MODULES = frozenset(
    module for owner in DISPATCH_OWNERS.values() for module in owner.modules
)


def dispatch_owner(key: str) -> DispatchOwner:
    """Return the registered owner, or fail closed for an unregistered key.

    An owner that is not in the inventory cannot obtain an admission, which is
    the point: registering is how a new dispatch consumer becomes reviewable.
    """

    owner = DISPATCH_OWNERS.get(str(key or "").strip())
    if owner is None:
        raise ValueError(
            "Unregistered provider-dispatch owner. Add it to "
            "app/services/model_gateway/dispatch_owners.py before dispatching."
        )
    return owner


def owners_for_mode(mode: str) -> tuple[DispatchOwner, ...]:
    return tuple(owner for owner in DISPATCH_OWNERS.values() if owner.mode == mode)



__all__ = [
    "DISPATCH_OWNERS",
    "DISPATCH_OWNER_MODULES",
    "dispatch_owner",
    "owners_for_mode",
]
