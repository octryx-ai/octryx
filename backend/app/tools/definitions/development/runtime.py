"""Tool definitions for HTTP, system context, document ingestion, browser and Python sessions."""

from __future__ import annotations

# ruff: noqa: E501

RUNTIME_DEFINITIONS: dict[str, dict] = {
    "http_request": {
        "type": "function",
        "function": {
            "name": "http_request",
            "description": (
                "Execute an outbound HTTP request for APIs or health checks. "
                "Mutating requests require approval when the runtime can track a session."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "method": {"type": "string"},
                    "url": {"type": "string"},
                    "headers": {"type": "object", "additionalProperties": {"type": "string"}},
                    "query": {"type": "object", "additionalProperties": {"type": "string"}},
                    "body": {"type": "string"},
                    "timeout_sec": {"type": "integer"},
                },
                "required": ["url"],
            },
        },
    },
    "get_system_context": {
        "type": "function",
        "function": {
            "name": "get_system_context",
            "description": "Return the current OS, shell, workspace root, command hints, and available binaries",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "get_current_time": {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": (
                "Return current local and UTC time without shell-specific date commands. "
                "When relative_days is set, use target_local_date for the resulting local "
                "calendar date."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "relative_days": {"type": "integer"},
                },
            },
        },
    },
    "ingest_document_source": {
        "type": "function",
        "function": {
            "name": "ingest_document_source",
            "description": (
                "Download or ingest a local PDF, DOCX, XLSX, PPTX, image, HTML, or text file into a research bundle. "
                "PDF/Office/image files are parsed with lit/liteparse, and sources.json and citations.json are "
                "written for document Q&A with query_document_knowledge."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "HTTP(S) source URL to download and ingest"},
                    "path": {
                        "type": "string",
                        "description": "Local workspace path or uploaded file path to ingest",
                    },
                    "file_path": {"type": "string", "description": "Alias for path"},
                    "topic": {"type": "string", "description": "Research topic used for bundle naming"},
                    "bundle_id": {"type": "string", "description": "Optional stable research bundle id"},
                    "citation_style": {
                        "type": "string",
                        "enum": ["ieee", "apa", "mla", "chicago", "harvard", "none"],
                    },
                    "max_pages": {"type": "integer", "description": "Maximum document pages to parse with lit"},
                },
            },
        },
    },
    "list_repository_readme_status": {
        "type": "function",
        "function": {
            "name": "list_repository_readme_status",
            "description": "List README coverage for repository top-level folders and module directories",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "top_level_limit": {"type": "integer"},
                    "module_limit": {"type": "integer"},
                },
                "required": ["path"],
            },
        },
    },
    "generate_repository_readmes": {
        "type": "function",
        "function": {
            "name": "generate_repository_readmes",
            "description": "Generate root, top-level, and missing module README files for a local repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
                "required": ["path"],
            },
        },
    },
    "browser_open_url": {
        "type": "function",
        "function": {
            "name": "browser_open_url",
            "description": "Open a URL in a persistent browser session. Use this before snapshot/click/type.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "browser_session_id": {"type": "string"},
                    "timeout_ms": {"type": "integer"},
                    "wait_until": {"type": "string"},
                    "user_agent": {"type": "string"},
                },
                "required": ["url"],
            },
        },
    },
    "browser_snapshot": {
        "type": "function",
        "function": {
            "name": "browser_snapshot",
            "description": "Return stable element refs from the current browser page. Refresh refs after navigation or major DOM changes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "browser_session_id": {"type": "string"},
                    "max_elements": {"type": "integer"},
                },
            },
        },
    },
    "browser_click": {
        "type": "function",
        "function": {
            "name": "browser_click",
            "description": "Click an element by ref from the latest browser snapshot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "browser_session_id": {"type": "string"},
                    "ref": {"type": "string"},
                    "timeout_ms": {"type": "integer"},
                },
                "required": ["ref"],
            },
        },
    },
    "browser_type": {
        "type": "function",
        "function": {
            "name": "browser_type",
            "description": "Type text into an element by ref from the latest browser snapshot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "browser_session_id": {"type": "string"},
                    "ref": {"type": "string"},
                    "text": {"type": "string"},
                    "submit": {"type": "boolean"},
                },
                "required": ["ref", "text"],
            },
        },
    },
    "browser_press": {
        "type": "function",
        "function": {
            "name": "browser_press",
            "description": "Press a key in the current browser page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "browser_session_id": {"type": "string"},
                    "key": {"type": "string"},
                },
                "required": ["key"],
            },
        },
    },
    "browser_take_screenshot": {
        "type": "function",
        "function": {
            "name": "browser_take_screenshot",
            "description": "Save a screenshot from the current browser page into the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "browser_session_id": {"type": "string"},
                    "path": {"type": "string"},
                    "full_page": {"type": "boolean"},
                },
            },
        },
    },
    "browser_close": {
        "type": "function",
        "function": {
            "name": "browser_close",
            "description": "Close the current browser automation session.",
            "parameters": {
                "type": "object",
                "properties": {
                    "browser_session_id": {"type": "string"},
                },
            },
        },
    },
    "python_exec_code": {
        "type": "function",
        "function": {
            "name": "python_exec_code",
            "description": "Execute Python code in a persistent interactive Python session.",
            "parameters": {
                "type": "object",
                "properties": {
                    "python_session_id": {"type": "string"},
                    "code": {"type": "string"},
                },
                "required": ["code"],
            },
        },
    },
    "python_list_variables": {
        "type": "function",
        "function": {
            "name": "python_list_variables",
            "description": "List currently defined variables in the interactive Python session.",
            "parameters": {
                "type": "object",
                "properties": {
                    "python_session_id": {"type": "string"},
                },
            },
        },
    },
    "python_close_session": {
        "type": "function",
        "function": {
            "name": "python_close_session",
            "description": "Close the current interactive Python session.",
            "parameters": {
                "type": "object",
                "properties": {
                    "python_session_id": {"type": "string"},
                },
            },
        },
    },
}
