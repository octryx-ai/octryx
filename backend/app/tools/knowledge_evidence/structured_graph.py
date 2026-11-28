"""``graph_neighbors``, ``config_vs_manual`` and ``ops_chain``: the deterministic structured graph."""

from __future__ import annotations

import json
from typing import Any

from ...services.knowledge.ledger.errors import EvidenceLedgerError
from ...services.knowledge.structured.config_report import handbook_vs_reality
from ...services.knowledge.structured.navigate import graph_neighbors, ops_chain
from ..context import ToolContext
from ._scope import authorized_workspace, failure

# Inside the inline tool-result limit; lists are cut whole items at a time and say so.
RESULT_BUDGET_BYTES = 11000
CONFIG_LIMIT = 20


_CITATION_KEYS = ("cite_as", "page", "section", "line")


def _compact(value: Any) -> Any:
    if isinstance(value, dict):
        if "cite_as" in value and "evidence_key" in value:
            return {key: value[key] for key in _CITATION_KEYS if value.get(key) is not None}
        return {key: _compact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_compact(item) for item in value]
    return value


def _fit(result: dict[str, Any], lists: tuple[str, ...]) -> dict[str, Any]:
    trimmed = dict(result)
    cut: dict[str, int] = {}
    while len(json.dumps(trimmed, ensure_ascii=False, default=str)) > RESULT_BUDGET_BYTES:
        name = max(lists, key=lambda key: len(trimmed.get(key) or []))
        if not trimmed.get(name):
            break
        trimmed[name] = list(trimmed[name])[:-1]
        cut[name] = cut.get(name, 0) + 1
    if cut:
        trimmed["not_shown"] = cut
    return trimmed


class _StructuredTool:
    name = ""
    lists: tuple[str, ...] = ()

    async def _answer(self, params: dict, context: ToolContext, authorized) -> dict[str, Any]:
        raise NotImplementedError

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        authorized = await authorized_workspace(params, context)
        if type(authorized) is dict:
            return authorized
        try:
            result = await self._answer(params, context, authorized)
        except EvidenceLedgerError as error:
            return failure(error.state.value)
        if result.get("state") == "invalid_request":
            return failure("invalid_request")
        return _fit(_compact(result), self.lists)


class GraphNeighborsTool(_StructuredTool):
    name = "graph_neighbors"
    description = "The cited one-hop facts of an entity in the Workspace's structured graph. Read-only."
    lists = ("facts", "nodes")

    async def _answer(self, params, context, authorized):
        return await graph_neighbors(context.db, authorized=authorized, entity=params.get("entity"))


class ConfigVsManualTool(_StructuredTool):
    name = "config_vs_manual"
    description = "Configured settings against the manual (Handbook vs. reality), cited. Read-only."
    lists = ("undocumented_in_known_section", "unknown_section", "deviations", "unresolved_placeholders",
             "inconsistencies", "documented_unused")

    async def _answer(self, params, context, authorized):
        if not any(params.get(key) for key in ("parameter", "file", "section")) and params.get("overview") is not True:
            return {"state": "invalid_request"}
        return await handbook_vs_reality(
            context.db, authorized=authorized, parameter=params.get("parameter"), file=params.get("file"),
            section=params.get("section"), limit=CONFIG_LIMIT,
        )


class OpsChainTool(_StructuredTool):
    name = "ops_chain"
    description = "The cited operations chain of a ticket, change or service. Read-only."
    lists = ("facts", "configuration", "records")

    async def _answer(self, params, context, authorized):
        return await ops_chain(context.db, authorized=authorized, ticket=params.get("ticket") or params.get("change"),
                               service=params.get("service"))


__all__ = ["ConfigVsManualTool", "GraphNeighborsTool", "OpsChainTool"]
