"""Tool definitions for the development, code-intelligence and browser/python domain."""

from __future__ import annotations

import copy

from .code_graph import CODE_GRAPH_DEFINITIONS
from .code_intelligence import CODE_INTELLIGENCE_DEFINITIONS
from .runtime import RUNTIME_DEFINITIONS
from .session import SESSION_DEFINITIONS
from .snapshots_lsp import SNAPSHOT_LSP_DEFINITIONS


def get_development_definitions() -> dict[str, dict]:
    """Return OpenAI-compatible tool definitions for development tools."""
    # A fresh copy per call: callers may change the returned definitions without touching the shared table.
    return copy.deepcopy(
        {
            **RUNTIME_DEFINITIONS,
            **CODE_INTELLIGENCE_DEFINITIONS,
            **CODE_GRAPH_DEFINITIONS,
            **SESSION_DEFINITIONS,
            **SNAPSHOT_LSP_DEFINITIONS,
        }
    )
