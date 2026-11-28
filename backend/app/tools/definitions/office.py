"""Tool definitions for the Office document domain."""

from __future__ import annotations

import copy

# ruff: noqa: E501
from .office_builders import OFFICE_BUILDER_DEFINITIONS

_OFFICE_EDITING_DEFINITIONS: dict[str, dict] = {
    "read_office_document": {
        "type": "function",
        "function": {
            "name": "read_office_document",
            "description": "Read an Office document in text, outline, annotated, stats, issues, or html mode.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "view": {"type": "string"},
                    "start": {"type": "integer"},
                    "end": {"type": "integer"},
                    "max_lines": {"type": "integer"},
                },
                "required": ["file_path"],
            },
        },
    },
    "get_office_document_info": {
        "type": "function",
        "function": {
            "name": "get_office_document_info",
            "description": "Get Office document stats such as pages, words, sheets, or slides.",
            "parameters": {
                "type": "object",
                "properties": {"file_path": {"type": "string"}},
                "required": ["file_path"],
            },
        },
    },
    "validate_office_document": {
        "type": "function",
        "function": {
            "name": "validate_office_document",
            "description": "Validate an Office document and list structure or content issues.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "issue_type": {"type": "string"},
                    "limit": {"type": "integer"},
                    "render": {"type": "boolean", "description": "Also render the document once (opt-in)."},
                },
                "required": ["file_path"],
            },
        },
    },
    "get_office_element": {
        "type": "function",
        "function": {
            "name": "get_office_element",
            "description": "Read one Office document element by path with bounded child depth.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "path": {"type": "string"},
                    "depth": {"type": "integer"},
                },
                "required": ["file_path", "path"],
            },
        },
    },
    "query_office_elements": {
        "type": "function",
        "function": {
            "name": "query_office_elements",
            "description": "Query multiple Office document elements by selector.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "selector": {"type": "string"},
                },
                "required": ["file_path", "selector"],
            },
        },
    },
    "set_office_property": {
        "type": "function",
        "function": {
            "name": "set_office_property",
            "description": "Set one or more properties on an Office document element.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "path": {"type": "string"},
                    "properties": {"type": "object"},
                },
                "required": ["file_path", "path", "properties"],
            },
        },
    },
    "add_office_element": {
        "type": "function",
        "function": {
            "name": "add_office_element",
            "description": 'Add an Office document element such as a paragraph, table, shape, chart, or slide. For PowerPoint slides, use the layout name, for example {"layout":"Title and Bulletpoints"} instead of numeric layout IDs.',
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "parent_path": {"type": "string"},
                    "element_type": {"type": "string"},
                    "properties": {"type": "object"},
                    "index": {"type": "integer"},
                },
                "required": ["file_path", "parent_path", "element_type"],
            },
        },
    },
    "remove_office_element": {
        "type": "function",
        "function": {
            "name": "remove_office_element",
            "description": "Remove an element from an Office document.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "path": {"type": "string"},
                },
                "required": ["file_path", "path"],
            },
        },
    },
    "fill_office_template": {
        "type": "function",
        "function": {
            "name": "fill_office_template",
            "description": "Fill a configured or explicit DOCX, XLSX, or PPTX template with JSON data. When available, the active corporate identity default template is used when no explicit template is provided.",
            "parameters": {
                "type": "object",
                "properties": {
                    "template_path": {"type": "string"},
                    "template_key": {"type": "string"},
                    "output_path": {"type": "string"},
                    "data": {"type": "object"},
                },
                "required": ["output_path", "data"],
            },
        },
    },
    "read_excel_cell": {
        "type": "function",
        "function": {
            "name": "read_excel_cell",
            "description": "Read one Excel cell or range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "path": {"type": "string"},
                },
                "required": ["file_path", "path"],
            },
        },
    },
    "set_excel_cell": {
        "type": "function",
        "function": {
            "name": "set_excel_cell",
            "description": "Set one Excel cell value.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "path": {"type": "string"},
                    "value": {},
                },
                "required": ["file_path", "path", "value"],
            },
        },
    },
    "create_excel_chart": {
        "type": "function",
        "function": {
            "name": "create_excel_chart",
            "description": "Create a chart in an Excel workbook.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "parent_path": {"type": "string"},
                    "chart_type": {"type": "string"},
                    "properties": {"type": "object"},
                },
                "required": ["file_path", "chart_type"],
            },
        },
    },
    "get_presentation_html": {
        "type": "function",
        "function": {
            "name": "get_presentation_html",
            "description": "Render a PowerPoint presentation as HTML.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                },
                "required": ["file_path"],
            },
        },
    },
}


def get_office_definitions() -> dict[str, dict]:
    # A fresh copy per call: callers may change the returned definitions without touching the shared table.
    return copy.deepcopy({**OFFICE_BUILDER_DEFINITIONS, **_OFFICE_EDITING_DEFINITIONS})
