"""The fixed failure taxonomy of the knowledge graph, importable without Graphiti.

The projector and the retrieval routes map these onto fixed tokens and states.
"""

from __future__ import annotations

from enum import StrEnum


class GraphStoreState(StrEnum):
    UNAVAILABLE = "unavailable"
    UNAUTHORIZED = "unauthorized"
    CONTRACT_VIOLATION = "contract_violation"


class GraphStoreError(Exception):
    """A graph store failure with a fixed state and no server text."""

    def __init__(self, state: GraphStoreState) -> None:
        super().__init__(f"graph store {state.value}")
        self.state = state


class GraphNotConfiguredError(Exception):
    """The embedding space the graph needs is absent; no value is rendered."""


class GraphModelUnavailableError(Exception):
    """No governed model may serve graph extraction for this Workspace; ``reason`` is fixed."""

    def __init__(self, state: str, reason: str) -> None:
        super().__init__(f"graph model {state}: {reason}")
        self.state = state
        self.reason = reason


__all__ = ["GraphModelUnavailableError", "GraphNotConfiguredError", "GraphStoreError", "GraphStoreState"]
