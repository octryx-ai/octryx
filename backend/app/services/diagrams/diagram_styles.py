"""Drawio styles of the deterministic diagram renderers."""

from __future__ import annotations


def edge_style(*, dashed: bool = False) -> str:
    dashed_bit = "dashed=1;" if dashed else ""
    return (
        "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
        f"strokeWidth=2;strokeColor=#6c8ebf;endArrow=block;{dashed_bit}"
    )


def uml_class_container_style() -> str:
    return (
        "shape=swimlane;rounded=0;whiteSpace=wrap;html=1;startSize=26;"
        "fillColor=#ffffff;strokeColor=#000000;fontStyle=1;"
    )


def uml_class_row_style() -> str:
    return "text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;spacingLeft=8;fontSize=11;"
