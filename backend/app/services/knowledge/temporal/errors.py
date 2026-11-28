"""The fixed failure taxonomy of the knowledge graph, importable without Graphiti."""

from __future__ import annotations

from enum import StrEnum


class GraphStoreState(StrEnum):
    UNAVAILABLE = "unavailable"
    UNAUTHORIZED = "unauthorized"
    CONTRACT_VIOLATION = "contract_violation"


class GraphStoreError(Exception):
    def __init__(self, state: GraphStoreState) -> None:
        super().__init__(f"graph store {state.value}")
        self.state = state


class GraphNotConfiguredError(Exception):
    pass


class GraphModelUnavailableError(Exception):
    def __init__(self, state: str, reason: str) -> None:
        super().__init__(f"graph model {state}: {reason}")
        self.state = state
        self.reason = reason


__all__ = ["GraphModelUnavailableError", "GraphNotConfiguredError", "GraphStoreError", "GraphStoreState"]
