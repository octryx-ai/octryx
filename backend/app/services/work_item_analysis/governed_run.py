"""The governed model run of one work item analysis (``services/governed_agent_run``).

1. The Workspace's ``model_policy`` setting (``name@revision``) resolves to the ordered gateway aliases of
   that published revision (``model_call.load_policy_aliases``); the aliases are admitted through
   ``admit_runtimes_for_dispatch`` under this module's own dispatch owner ``work_item_analysis``
   (``model_call.admitted_runtimes``): the project's model grant and its data policy apply.
2. Every request is a ``GovernedModelCall`` (guardrail scan, platform budget, alias failover, usage
   accounting) plus the analysis cost cap: once the run has spent ``cost_cap_usd`` no further request is
   made (``failed`` / ``cost_cap_reached``).
3. The tool surface is fixed: ``knowledge_search``, ``knowledge_read`` and ``work_item_context`` are
   required (a hidden, forbidden or approval-bound one is a refusal before any model request); the
   read-only ticket tools of the item's source are offered when the Workspace allows them, and the ones it
   does not are recorded as ``unavailable``. Every call goes through the registry's governance chain under
   the session's enforced ``read_only`` class. ``work_item_context`` is pinned to the analysed item.
4. Every tool output is kept for the citation check (``contract.check_citations``).
5. Each request is bounded by the Workspace's ``max_output_tokens`` setting (default 8192); the model that
   answered is recorded.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...agent.harness.runtime import HarnessRuntime
from ...tools.definitions import get_all_definitions
from ...tools.visibility import tool_visibility_decision
from ..governed_agent_run.context import ExecutionContext
from ..governed_agent_run.final_text import harness_final_text
from ..governed_agent_run.governed_tool import is_registered_tool, tool_requires_approval
from ..governed_agent_run.model_call import (
    GovernedModelCall,
    RuntimeResolver,
    admitted_runtimes,
    load_policy_aliases,
)
from ..governed_agent_run.refusals import RunRefusal, denied, failed, needs_configuration
from ..governed_agent_run.tool_context import build_run_tool_context
from ..governed_agent_run.tools import AgentToolCall, AgentToolSurface
from ..model_policy.references import ReferenceShapeError, parse_reference
from ..tool_access_policy import tool_project_policy_decision

DISPATCH_OWNER = "work_item_analysis"
CORE_TOOLS = ("knowledge_search", "knowledge_read", "work_item_context")
SOURCE_TOOLS: dict[str, tuple[str, ...]] = {
    "jira": ("search_jira_tickets", "get_jira_ticket"),
    "servicenow": ("list_servicenow_incidents", "get_servicenow_record"),
}
CONTEXT_TOOL = "work_item_context"
REQUEST_LIMIT = 12
_ADMITTED_PROFILE = {"status": "allowed"}


@dataclass
class RunOutcome:
    text: str = ""
    refusal: RunRefusal | None = None
    cost_usd: Decimal = Decimal("0")
    tokens_in: int = 0
    tokens_out: int = 0
    offered: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)
    tool_outputs: list[str] = field(default_factory=list)
    model: str | None = None


def _usable(name: str, config: dict[str, Any], catalog: dict[str, Any]) -> str | None:
    """``None`` when the Workspace offers ``name`` to this run, else the closed refusal code."""
    if name not in catalog or not is_registered_tool(name):
        return "tool_unavailable"
    if not tool_visibility_decision(name, config).visible or not tool_project_policy_decision(name, config).allowed:
        return "tool_denied_by_policy"
    if tool_requires_approval(name, config):
        return "tool_requires_approval"
    return None


def tool_surface(project_config: dict[str, Any], source_type: str) -> tuple[AgentToolSurface, list[str]]:
    catalog = get_all_definitions()
    for name in CORE_TOOLS:
        code = _usable(name, project_config, catalog)
        if code == "tool_unavailable":
            raise needs_configuration(code)
        if code is not None:
            raise denied(code)
    optional = SOURCE_TOOLS.get(source_type, ())
    offered = [*CORE_TOOLS, *(name for name in optional if _usable(name, project_config, catalog) is None)]
    unavailable = [name for name in optional if name not in offered]
    surface = AgentToolSurface(tuple(catalog[name] for name in offered), frozenset(offered), frozenset(),
                               frozenset())
    return surface, unavailable


class CappedModelCall(GovernedModelCall):
    """A governed call that makes no further request once the run has spent its cost cap."""

    def __init__(self, *args: Any, cost_cap_usd: Decimal, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._cost_cap_usd = cost_cap_usd
        self.model: str | None = None

    async def __call__(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> dict[str, Any]:
        if self.cost_usd >= self._cost_cap_usd:
            raise failed("cost_cap_reached")
        response = await super().__call__(messages, tools)
        self.model = str((response or {}).get("model") or "")[:200] or self.model
        return response


class RecordingToolCall:
    """The run's tool closure: ``work_item_context`` pinned to the item, every output kept."""

    def __init__(self, inner: AgentToolCall, work_item_id: str, outputs: list[str]) -> None:
        self._inner = inner
        self._work_item_id = work_item_id
        self._outputs = outputs

    async def __call__(self, call: dict[str, Any]) -> str:
        function = call.get("function") if isinstance(call, dict) else None
        if isinstance(function, dict) and function.get("name") == CONTEXT_TOOL:
            arguments = json.dumps({"work_item": self._work_item_id, "include_session_digests": False})
            call = {**call, "function": {**function, "arguments": arguments}}
        text = await self._inner(call)
        self._outputs.append(text)
        return text


def _settle(outcome: RunOutcome, call: CappedModelCall | None) -> RunOutcome:
    if call is not None:
        outcome.cost_usd, outcome.tokens_in, outcome.tokens_out = call.cost_usd, call.tokens_in, call.tokens_out
        outcome.model = call.model
    return outcome


async def run_governed_analysis(
    db: AsyncSession,
    context: ExecutionContext,
    *,
    model_policy: str | None,
    cost_cap_usd: Decimal,
    max_output_tokens: int,
    system_prompt: str,
    task: str,
    work_item_id: str,
    source_type: str,
    resolve_runtimes: RuntimeResolver | None = None,
    get_provider: Callable[..., Any] | None = None,
) -> RunOutcome:
    """Run the analysis; every refusal is returned in ``outcome.refusal`` with the cost spent so far."""
    outcome = RunOutcome()
    call: CappedModelCall | None = None
    try:
        tool_context = await build_run_tool_context(db, context)
        surface, outcome.unavailable = tool_surface(tool_context.project_config, source_type)
        outcome.offered = sorted(surface.tool_names)
        try:
            policy_ref = parse_reference(model_policy or "")
        except ReferenceShapeError:
            raise needs_configuration("model_policy_unresolved") from None
        aliases = await load_policy_aliases(db, context.workspace_id, policy_ref)
        options = {} if resolve_runtimes is None else {"resolve_runtimes": resolve_runtimes}
        runtimes = await admitted_runtimes(
            db, workspace_id=context.workspace_id, aliases=aliases, requires_tools=True, owner=DISPATCH_OWNER,
            **options,
        )
        call = CappedModelCall(db, context, runtimes, get_provider=get_provider, dispatch_owner=DISPATCH_OWNER,
                               max_tokens=max_output_tokens, cost_cap_usd=cost_cap_usd)
        runtime = HarnessRuntime(
            execution_profile=_ADMITTED_PROFILE,
            model_call=call,
            base_messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": task}],
            tool_definitions=list(surface.definitions),
            tool_call=RecordingToolCall(AgentToolCall(surface, tool_context), work_item_id, outcome.tool_outputs),
            request_limit=REQUEST_LIMIT,
        )
        outcome.text = await harness_final_text(runtime, task)
    except RunRefusal as refusal:
        outcome.refusal = refusal
    return _settle(outcome, call)


__all__ = [
    "CORE_TOOLS",
    "DISPATCH_OWNER",
    "SOURCE_TOOLS",
    "CappedModelCall",
    "RunOutcome",
    "run_governed_analysis",
    "tool_surface",
]
