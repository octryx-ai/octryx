"""The diagram intermediate representation every deterministic renderer builds before drawio XML."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DiagramNodeIR:
    id: str
    label: str
    style: str
    x: int
    y: int
    width: int
    height: int
    parent: str = "1"


@dataclass(frozen=True)
class DiagramEdgeIR:
    id: str
    source: str
    target: str
    label: str = ""
    style: str = ""
    points: tuple[tuple[int, int], ...] = ()
    parent: str = "1"
    # Relative label position along the edge (-1.0 source .. 1.0 target,
    # mxGraph semantics). None keeps the renderer default; distinct values
    # de-stack labels when several edges share an endpoint.
    label_position: float | None = None


@dataclass(frozen=True)
class DiagramIR:
    title: str
    renderer: str
    notation: str = ""
    nodes: tuple[DiagramNodeIR, ...] = ()
    edges: tuple[DiagramEdgeIR, ...] = ()
