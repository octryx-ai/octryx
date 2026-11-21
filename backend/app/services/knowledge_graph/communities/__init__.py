"""Community layer (tier 3): cluster the graph and summarize each cluster.

Detection is deterministic: connected components over active edges, with large
components split by hub (highest-degree) nodes so clusters stay readable. At
team-instance scale this matches Leiden's intent without a native dependency;
swapping in Leiden later only changes ``detect_communities``.

Reports: a deterministic structural summary is always written; when a governed
``generate`` callable is provided (summarize role), an LLM community report
replaces it. Community summaries are embedded for tier-3 retrieval.
"""

from __future__ import annotations

from .build import build_communities
from .detection import _MAX_COMMUNITY_SIZE, _community_key, _structural_summary, detect_communities
from .reports import REPORT_ANSWER_CONTRACT, GenerateFn, _parse_report, build_report_prompt
from .search import global_search, search_communities

__all__ = [
    "REPORT_ANSWER_CONTRACT",
    "GenerateFn",
    "_MAX_COMMUNITY_SIZE",
    "_community_key",
    "_parse_report",
    "_structural_summary",
    "build_communities",
    "build_report_prompt",
    "detect_communities",
    "global_search",
    "search_communities",
]
