"""Tool definitions that create Office documents and build presentation, Word and Excel scripts."""

from __future__ import annotations

# ruff: noqa: E501

OFFICE_BUILDER_DEFINITIONS: dict[str, dict] = {
    "create_office_document": {
        "type": "function",
        "function": {
            "name": "create_office_document",
            "description": "Create a new Office document inside the workspace, optionally from a configured Office template. When available, the active corporate identity default template is used for PPTX, DOCX, and XLSX.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "doc_type": {"type": "string"},
                    "template_key": {"type": "string"},
                    "template_path": {"type": "string"},
                    "template_data": {"type": "object"},
                },
                "required": ["file_path"],
            },
        },
    },
    "build_presentation_script": {
        "type": "function",
        "function": {
            "name": "build_presentation_script",
            "description": "Build a PowerPoint deck by generating and executing a Python script against the corporate template.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "slides": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "layout_type": {"type": "string"},
                                "title": {"type": "string"},
                                "subtitle": {"type": "string"},
                                "footer": {"type": "string"},
                                "quote": {"type": "string"},
                                "author": {"type": "string"},
                                "body": {"type": "string"},
                                "bullets": {"type": "array", "items": {"type": "string"}},
                                "items": {"type": "array", "items": {"type": "string"}},
                                "headers": {"type": "array", "items": {"type": "string"}},
                                "rows": {"type": "array", "items": {"type": "array", "items": {}}},
                                "insight": {"type": "string"},
                                "chart": {"type": "object"},
                                "table": {"type": "object"},
                                "steps": {"type": "array", "items": {"type": "object"}},
                                "columns": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "label": {"type": "string"},
                                            "body": {"type": "string"},
                                        },
                                    },
                                },
                            },
                            "required": ["layout_type"],
                        },
                    },
                },
                "required": ["file_path", "slides"],
            },
        },
    },
    "build_word_template_script": {
        "type": "function",
        "function": {
            "name": "build_word_template_script",
            "description": "Build a Word document from a configured or default DOCX/DOTX template by generating and executing an editable Python script. Supports citation styles like IEEE, APA, MLA, Chicago, and Harvard.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "template_key": {"type": "string"},
                    "template_path": {"type": "string"},
                    "template_data": {"type": "object"},
                    "citation_style": {
                        "type": "string",
                        "enum": ["none", "ieee", "apa", "mla", "chicago", "harvard"],
                    },
                    "include_bibliography": {"type": "boolean"},
                    "sources": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "key": {"type": "string"},
                                "title": {"type": "string"},
                                "author": {"type": "string"},
                                "authors": {"type": "array", "items": {"type": "string"}},
                                "publisher": {"type": "string"},
                                "organization": {"type": "string"},
                                "url": {"type": "string"},
                                "year": {"type": ["string", "integer"]},
                                "published_at": {"type": "string"},
                                "accessed_at": {"type": "string"},
                                "doi": {"type": "string"},
                                "isbn": {"type": "string"},
                                "source_type": {"type": "string"},
                            },
                        },
                    },
                    "sections": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "layout_type": {"type": "string"},
                                "title": {"type": "string"},
                                "subtitle": {"type": "string"},
                                "body": {"type": ["string", "array"]},
                                "bullets": {"type": "array", "items": {"type": "string"}},
                                "items": {"type": "array", "items": {"type": "string"}},
                                "headers": {"type": "array", "items": {"type": "string"}},
                                "rows": {"type": "array", "items": {"type": "array", "items": {}}},
                                "quote": {"type": "string"},
                                "author": {"type": "string"},
                                "formula": {"type": "string"},
                                "levels": {"type": "string"},
                                "chart": {"type": "object"},
                                "steps": {"type": "array", "items": {"type": "object"}},
                                "citations": {"type": "array", "items": {"type": ["string", "integer"]}},
                                "source_ids": {"type": "array", "items": {"type": ["string", "integer"]}},
                            },
                            "required": ["layout_type"],
                        },
                    },
                },
                "required": ["file_path", "sections"],
            },
        },
    },
    "build_excel_template_script": {
        "type": "function",
        "function": {
            "name": "build_excel_template_script",
            "description": "Build an Excel workbook from a configured or default XLSX/XLTX template by generating and executing an editable Python script.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "template_key": {"type": "string"},
                    "template_path": {"type": "string"},
                    "template_data": {"type": "object"},
                    "sheets": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "layout_type": {"type": "string"},
                                "title": {"type": "string"},
                                "start_cell": {"type": "string"},
                                "headers": {"type": "array", "items": {"type": "string"}},
                                "rows": {"type": "array", "items": {"type": "array", "items": {}}},
                                "formulas": {"type": "object"},
                                "kpis": {"type": "array", "items": {"type": "object"}},
                                "column_headers": {"type": "array", "items": {"type": "string"}},
                                "row_headers": {"type": "array", "items": {"type": "string"}},
                                "values": {"type": "array", "items": {"type": "array", "items": {}}},
                                "chart": {"type": "object"},
                                "charts": {"type": "array", "items": {"type": "object"}},
                                "sparklines": {"type": "array", "items": {"type": "object"}},
                                "validations": {"type": "array", "items": {"type": "object"}},
                                "conditional_formats": {"type": "array", "items": {"type": "object"}},
                                "pivot_table": {"type": "object"},
                                "pivot_tables": {"type": "array", "items": {"type": "object"}},
                                "auto_filter_range": {"type": "string"},
                            },
                            "required": ["layout_type"],
                        },
                    },
                },
                "required": ["file_path", "sheets"],
            },
        },
    },
}
