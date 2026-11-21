"""The LSP queries a client offers: definitions, references, hover and symbols, diagnostics."""

from __future__ import annotations

import asyncio
from pathlib import Path

from .protocol import _detect_language, _lsp_uri


class LspQueriesMixin:
    """Document and workspace queries; the host class provides ``_request`` and ``_notify``."""

    async def _open_doc(self, path: str) -> None:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        language = _detect_language(path) or "plaintext"
        await self._notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": _lsp_uri(path),
                    "languageId": language,
                    "version": 1,
                    "text": text,
                }
            },
        )
        await asyncio.sleep(0.3)

    async def _close_doc(self, path: str) -> None:
        await self._notify("textDocument/didClose", {"textDocument": {"uri": _lsp_uri(path)}})

    def _td_pos(self, path: str, line: int, col: int) -> dict:
        return {
            "textDocument": {"uri": _lsp_uri(path)},
            "position": {"line": line - 1, "character": col - 1},
        }

    async def go_to_definition(self, path: str, line: int, col: int) -> list[dict]:
        await self._open_doc(path)
        result = await self._request("textDocument/definition", self._td_pos(path, line, col))
        await self._close_doc(path)
        if not result:
            return []
        if isinstance(result, dict):
            result = [result]
        locations = []
        for loc in result or []:
            uri = loc.get("uri") or loc.get("targetUri", "")
            location_range = loc.get("range") or loc.get("targetRange", {})
            start = location_range.get("start", {})
            locations.append(
                {
                    "uri": uri,
                    "path": uri.replace("file://", ""),
                    "line": start.get("line", 0) + 1,
                    "col": start.get("character", 0) + 1,
                }
            )
        return locations

    async def find_references(
        self,
        path: str,
        line: int,
        col: int,
        include_declaration: bool = True,
    ) -> list[dict]:
        await self._open_doc(path)
        result = await self._request(
            "textDocument/references",
            {
                **self._td_pos(path, line, col),
                "context": {"includeDeclaration": include_declaration},
            },
        )
        await self._close_doc(path)
        locations = []
        for loc in result or []:
            uri = loc.get("uri", "")
            location_range = loc.get("range", {})
            start = location_range.get("start", {})
            locations.append(
                {
                    "uri": uri,
                    "path": uri.replace("file://", ""),
                    "line": start.get("line", 0) + 1,
                    "col": start.get("character", 0) + 1,
                }
            )
        return locations

    async def hover(self, path: str, line: int, col: int) -> dict:
        await self._open_doc(path)
        result = await self._request("textDocument/hover", self._td_pos(path, line, col))
        await self._close_doc(path)
        if not result:
            return {"content": ""}
        contents = result.get("contents", "")
        if isinstance(contents, dict):
            text = contents.get("value") or contents.get("language") or str(contents)
        elif isinstance(contents, list):
            text = "\n".join(c.get("value", c) if isinstance(c, dict) else str(c) for c in contents)
        else:
            text = str(contents)
        return {"content": text}

    async def document_symbols(self, path: str) -> list[dict]:
        await self._open_doc(path)
        result = await self._request("textDocument/documentSymbol", {"textDocument": {"uri": _lsp_uri(path)}})
        await self._close_doc(path)
        symbols = []
        for sym in result or []:
            location_range = sym.get("range") or sym.get("location", {}).get("range", {})
            start = location_range.get("start", {})
            symbols.append(
                {
                    "name": sym.get("name", ""),
                    "kind": sym.get("kind", 0),
                    "line": start.get("line", 0) + 1,
                    "col": start.get("character", 0) + 1,
                }
            )
        return symbols

    async def workspace_symbols(self, query: str) -> list[dict]:
        result = await self._request("workspace/symbol", {"query": query})
        symbols = []
        for sym in result or []:
            location = sym.get("location", {})
            uri = location.get("uri", "")
            location_range = location.get("range", {})
            start = location_range.get("start", {})
            symbols.append(
                {
                    "name": sym.get("name", ""),
                    "kind": sym.get("kind", 0),
                    "uri": uri,
                    "path": uri.replace("file://", ""),
                    "line": start.get("line", 0) + 1,
                    "col": start.get("character", 0) + 1,
                }
            )
        return symbols

    async def get_diagnostics(self, path: str) -> list[dict]:
        await self._open_doc(path)
        result = await self._request(
            "textDocument/diagnostic",
            {"textDocument": {"uri": _lsp_uri(path)}},
            timeout=5.0,
        )
        await self._close_doc(path)
        items = []
        for diag in (result or {}).get("items") or []:
            location_range = diag.get("range", {})
            start = location_range.get("start", {})
            items.append(
                {
                    "line": start.get("line", 0) + 1,
                    "col": start.get("character", 0) + 1,
                    "severity": diag.get("severity", 1),
                    "message": diag.get("message", ""),
                    "source": diag.get("source", ""),
                }
            )
        return items
