"""Web research in a phase a Workspace lists (``device_runs.research_phases``)."""

from __future__ import annotations

import copy
from typing import Any

RESEARCH_TOOLS = ("web_search", "web_fetch")
# Knowledge-first: a knowledge search with hits counts as research too.
EVIDENCE_TOOLS = ("knowledge_search", *RESEARCH_TOOLS)
EVIDENCE_COUNTED = ("knowledge_hit", *RESEARCH_TOOLS)
RESEARCH_KEY = "research"
RESEARCH_SOURCE = "workspace_research_phases"
RESEARCH_NOTE = ("Ask the Workspace's knowledge first: knowledge_search finds the specifications, pages and "
                 "decisions this Workspace already has (an earlier spec of the same product, its rule values and "
                 "sources), and the repository holds the code. Reuse what is there and stay consistent with it. "
                 "Then research on the web only what the knowledge does not answer: search first, then open the "
                 "pages you cite (Claude Code: WebSearch and WebFetch; Codex: its built-in web search; or the "
                 "platform's web_search and web_fetch; all count; if one answers unavailable, use another at once). "
                 "Choose sources from results, never from memory. In a 'Sources' section of the file you write, cite "
                 "every source and mark where it came from: '(Workspace knowledge)' with its cite_as link, or "
                 "'(new research)' with its URL.")


def research_checks(minimum: int) -> list[dict[str, Any]]:
    return [
        {"type": "evidence_count", "params": {"tools": list(EVIDENCE_COUNTED), "min_count": minimum},
         "blocking": True,
         "source": RESEARCH_SOURCE,
         "description": f"Researched: at least {minimum} knowledge_search hits or web_search / web_fetch results"},
        {"type": "urls_cited", "params": {"min_count": minimum}, "blocking": True, "source": RESEARCH_SOURCE,
         "description": f"The written file cites at least {minimum} distinct source URLs (a Sources section)"},
    ]


def with_research(definition: dict[str, Any], minimum: int | None, *, brief: bool = False) -> dict[str, Any]:
    if not minimum:
        return definition
    from ...workflow_checks.library import MAX_CHECKS

    out = copy.deepcopy(definition)
    policy = dict(out.get("tool_policy") or {})
    policy["allowlist"] = list(dict.fromkeys([*(policy.get("allowlist") or []), *EVIDENCE_TOOLS]))
    policy["denylist"] = [tool for tool in policy.get("denylist") or [] if tool not in EVIDENCE_TOOLS]
    out["tool_policy"] = policy
    contract = dict(out.get("workflow_contract") or {})
    own = [check for check in contract.get("checks") or []
           if not (isinstance(check, dict) and check.get("source") == RESEARCH_SOURCE)]
    # First, so the library's MAX_CHECKS cut never drops them silently.
    contract["checks"] = [*research_checks(minimum), *own][:MAX_CHECKS]
    contract[RESEARCH_KEY] = {"rule": RESEARCH_NOTE, "tools": list(EVIDENCE_TOOLS), "min_sources": minimum}
    if brief:
        contract["when_to_use"] = f"{str(contract.get('when_to_use') or '').rstrip()}\n\n{RESEARCH_NOTE}".strip()
    out["workflow_contract"] = contract
    return out


async def research_min_sources(db: Any, run: Any, node: Any) -> int | None:
    from ..graph import NODE_PHASE

    if node is None or run is None or not getattr(run, "project_id", None) or getattr(node, "kind", None) != NODE_PHASE:
        return None
    from ...agent_gateway.policy import load_workspace_policy
    from ...devices.device_runs_keys import DEFAULTS, browser_phase_key, device_runs_section

    loaded = await load_workspace_policy(db, run.project_id)
    section = device_runs_section(loaded.policy.raw) if loaded.policy is not None else {}
    if browser_phase_key(str(run.workflow_key or ""), str(node.id)) not in set(section.get("research_phases") or []):
        return None
    minimum = section.get("research_min_sources")
    return minimum if type(minimum) is int and minimum >= 1 else DEFAULTS["research_min_sources"]


async def research_phase_definition(db: Any, run: Any, node: Any, *, brief: bool = False) -> dict[str, Any]:
    from ..phase_contract import phase_definition

    return with_research(phase_definition(run, node), await research_min_sources(db, run, node), brief=brief)


__all__ = ["RESEARCH_KEY", "RESEARCH_NOTE", "RESEARCH_SOURCE", "RESEARCH_TOOLS", "research_checks",
           "research_min_sources", "research_phase_definition", "with_research"]
