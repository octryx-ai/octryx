"""LSP (Language Server Protocol) tools for code intelligence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .context import ToolContext


def _resolve_path(raw: str, workspace_root: str | None) -> str:
    p = Path(raw)
    if p.is_absolute():
        return str(p)
    root = Path(workspace_root or Path.cwd()).resolve()
    return str((root / p).resolve())


async def _get_client(path: str, context: ToolContext):
    """Return a running LspClient for the given file, or None."""
    from ..services.lsp import _detect_language, lsp_manager

    lang = _detect_language(path)
    if not lang:
        return None, f"Unsupported file type: {Path(path).suffix}"
    workspace = str(context.workspace_root or Path.cwd())
    client = await lsp_manager.get_or_create(
        lang,
        workspace,
        db=context.db,
        project_config=context.project_config,
    )
    if not client:
        return None, f"Could not start LSP server for language '{lang}'. Is it installed?"
    return client, None


class LspGoToDefinitionTool:
    name = "lsp_go_to_definition"
    description = (
        "Jump to the definition of a symbol using the Language Server Protocol. "
        "Returns the file path and line number where the symbol is defined. "
        "Supported: .py (pylsp), .ts/.tsx/.js/.jsx (typescript-language-server), .go (gopls), .rs (rust-analyzer)."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        raw_path = str(params.get("path") or "").strip()
        line = int(params.get("line") or 0)
        col = int(params.get("col") or 1)
        if not raw_path or not line:
            return {"error": "path and line are required"}

        path = _resolve_path(raw_path, context.workspace_root)
        client, err = await _get_client(path, context)
        if err:
            return {"error": err}

        try:
            locations = await client.go_to_definition(path, line, col)
        except Exception as e:
            return {"error": str(e)}

        return {
            "locations": locations,
            "count": len(locations),
            "execution_runtime": getattr(client, "runtime_metadata", {}),
        }


class LspFindReferencesTool:
    name = "lsp_find_references"
    description = (
        "Find all references to the symbol at a given position using the Language Server Protocol. "
        "Returns file paths and line numbers of all usages."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        raw_path = str(params.get("path") or "").strip()
        line = int(params.get("line") or 0)
        col = int(params.get("col") or 1)
        include_declaration = bool(params.get("include_declaration", True))
        if not raw_path or not line:
            return {"error": "path and line are required"}

        path = _resolve_path(raw_path, context.workspace_root)
        client, err = await _get_client(path, context)
        if err:
            return {"error": err}

        try:
            locations = await client.find_references(path, line, col, include_declaration)
        except Exception as e:
            return {"error": str(e)}

        return {
            "locations": locations,
            "count": len(locations),
            "execution_runtime": getattr(client, "runtime_metadata", {}),
        }


class LspHoverTool:
    name = "lsp_hover"
    description = (
        "Get hover information (type signature, documentation) for the symbol at a given position. "
        "Uses the Language Server Protocol."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        raw_path = str(params.get("path") or "").strip()
        line = int(params.get("line") or 0)
        col = int(params.get("col") or 1)
        if not raw_path or not line:
            return {"error": "path and line are required"}

        path = _resolve_path(raw_path, context.workspace_root)
        client, err = await _get_client(path, context)
        if err:
            return {"error": err}

        try:
            result = await client.hover(path, line, col)
        except Exception as e:
            return {"error": str(e)}

        return {
            **result,
            "execution_runtime": getattr(client, "runtime_metadata", {}),
        }


class LspDocumentSymbolsTool:
    name = "lsp_document_symbols"
    description = (
        "List all symbols (functions, classes, variables) in a file using the Language Server Protocol. "
        "Returns name, kind, and position of each symbol."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        raw_path = str(params.get("path") or "").strip()
        if not raw_path:
            return {"error": "path is required"}

        path = _resolve_path(raw_path, context.workspace_root)
        client, err = await _get_client(path, context)
        if err:
            return {"error": err}

        try:
            symbols = await client.document_symbols(path)
        except Exception as e:
            return {"error": str(e)}

        return {
            "path": path,
            "symbols": symbols,
            "count": len(symbols),
            "execution_runtime": getattr(client, "runtime_metadata", {}),
        }


class LspWorkspaceSymbolsTool:
    name = "lsp_workspace_symbols"
    description = (
        "Search for symbols across the entire workspace using the Language Server Protocol. "
        "Returns matching symbols with their file paths and positions."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        query = str(params.get("query") or "").strip()
        raw_path = str(params.get("path") or "").strip()  # used to determine language
        if not query:
            return {"error": "query is required"}
        if not raw_path:
            return {"error": "path is required to determine language"}

        path = _resolve_path(raw_path, context.workspace_root)
        client, err = await _get_client(path, context)
        if err:
            return {"error": err}

        try:
            symbols = await client.workspace_symbols(query)
        except Exception as e:
            return {"error": str(e)}

        return {
            "query": query,
            "symbols": symbols,
            "count": len(symbols),
            "execution_runtime": getattr(client, "runtime_metadata", {}),
        }


class LspDiagnosticsTool:
    name = "lsp_diagnostics"
    description = (
        "Get live diagnostics (errors, warnings) for a file using the Language Server Protocol. "
        "More accurate than check_file_syntax as the server understands imports and types."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        raw_path = str(params.get("path") or "").strip()
        if not raw_path:
            return {"error": "path is required"}

        path = _resolve_path(raw_path, context.workspace_root)
        client, err = await _get_client(path, context)
        if err:
            return {"error": err}

        try:
            diagnostics = await client.get_diagnostics(path)
        except Exception as e:
            return {"error": str(e)}

        errors = [d for d in diagnostics if d.get("severity") == 1]
        warnings = [d for d in diagnostics if d.get("severity") == 2]
        return {
            "path": path,
            "valid": len(errors) == 0,
            "diagnostics": diagnostics,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "execution_runtime": getattr(client, "runtime_metadata", {}),
        }
