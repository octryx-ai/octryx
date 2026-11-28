"""Community layer: cluster the graph and summarize each cluster."""

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
