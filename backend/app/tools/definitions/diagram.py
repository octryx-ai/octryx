"""Tool definitions for diagram domain."""

from __future__ import annotations

import copy

DIAGRAM_DEFINITIONS: dict[str, dict] = {
    "get_shape_library": {
        "type": "function",
        "function": {
            "name": "get_shape_library",
            "description": (
                "Load draw.io shape library documentation with exact style syntax and available shape names. "
                "Use this before create_diagram for vendor-specific or icon-specific diagrams such as AWS, Azure, GCP, "
                "Kubernetes, Cisco, and network diagrams."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "library": {
                        "type": "string",
                        "description": (
                            "Shape library name. Examples: aws4, azure2, gcp2, kubernetes, network, flowchart."
                        ),
                    },
                    "shape_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional requested services or icon names to match inside the selected library. "
                            'Examples: ["eks", "sqs", "dynamodb", "codepipeline"].'
                        ),
                    },
                },
                "required": ["library"],
            },
        },
    },
    "create_diagram": {
        "type": "function",
        "function": {
            "name": "create_diagram",
            "description": (
                "Create a draw.io diagram. WHEN: after the required evidence exists — for AWS/Kubernetes "
                "topology diagrams call the topology snapshot first and draw only its diagram_brief "
                "nodes/edges; for code diagrams call code_structure_snapshot first. WHEN NOT: do not "
                "invent nodes or relationships that are not in the collected evidence. "
                "Pass ONLY <mxCell> elements in 'xml' — NO wrapper tags (<mxGraphModel>, <root>, <mxfile>). "
                "The wrapper is added automatically. "
                "For vendor-specific diagrams, first call get_shape_library and use the exact documented shape syntax. "
                "Example xml value: "
                '<mxCell id="n1" value="EKS" '
                'style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FF9900;strokeColor=#232F3E;fontColor=#ffffff;" '
                'vertex="1" parent="1"><mxGeometry x="80" y="80" width="160" height="60" as="geometry"/></mxCell>'
                '<mxCell id="n2" value="SQS" '
                'style="rounded=1;whiteSpace=wrap;html=1;fillColor=#FF9900;strokeColor=#232F3E;fontColor=#ffffff;" '
                'vertex="1" parent="1"><mxGeometry x="320" y="80" width="160" height="60" as="geometry"/></mxCell>'
                '<mxCell id="e1" edge="1" source="n1" target="n2" parent="1"><mxGeometry relative="1" '
                'as="geometry"/></mxCell>'
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "xml": {
                        "type": "string",
                        "description": (
                            "ONLY <mxCell> elements. No wrapper tags. "
                            "Shape syntax: <mxCell id='X' value='Label' style='rounded=1;whiteSpace=wrap;html=1;' "
                            "vertex='1' parent='1'><mxGeometry x='80' y='80' width='160' height='60' "
                            "as='geometry'/></mxCell>. "
                            "Connector syntax: <mxCell id='eX' edge='1' source='fromId' target='toId' "
                            "parent='1'><mxGeometry relative='1' as='geometry'/></mxCell>. "
                            "Close every tag with </mxCell> not </Cell>. "
                            "For AWS/Azure/GCP/Kubernetes/Cisco icons, call get_shape_library first and use the exact "
                            "mxgraph.* shape syntax from that library. "
                            "AWS fallback style: fillColor=#FF9900;strokeColor=#232F3E;fontColor=#ffffff. "
                            "Space nodes 200px apart."
                        ),
                    },
                    "title": {"type": "string", "description": "Short diagram title"},
                },
                "required": ["xml", "title"],
            },
        },
    },
    "append_diagram": {
        "type": "function",
        "function": {
            "name": "append_diagram",
            "description": (
                "Continue a truncated create_diagram call. "
                "Pass ONLY the continuation <mxCell> elements — no wrapper tags. "
                "Do NOT restart with <mxGraphModel> or <root>."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "xml": {"type": "string", "description": "Continuation mxCell elements only"},
                    "base_xml": {
                        "type": "string",
                        "description": "The partial xml from the previous truncated call",
                    },
                    "title": {"type": "string", "description": "Diagram title"},
                },
                "required": ["xml"],
            },
        },
    },
    "edit_diagram": {
        "type": "function",
        "function": {
            "name": "edit_diagram",
            "description": (
                "Replace the current draw.io diagram with an updated version. "
                "Pass ONLY the new <mxCell> elements (no wrapper tags) — same format as create_diagram. "
                "Use after create_diagram when the user requests changes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "xml": {
                        "type": "string",
                        "description": "Complete updated draw.io mxGraph XML.",
                    },
                    "title": {
                        "type": "string",
                        "description": "Title of the diagram",
                    },
                    "change_description": {
                        "type": "string",
                        "description": "Brief description of what changed",
                    },
                },
                "required": ["xml", "title", "change_description"],
            },
        },
    },
}


def get_diagram_definitions() -> dict[str, dict]:
    # A fresh copy per call: callers may change the returned definitions without touching the shared table.
    return copy.deepcopy(DIAGRAM_DEFINITIONS)
