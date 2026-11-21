"""Canonical LSP service package."""

from .protocol import _EXT_TO_LANG, _LSP_SERVERS, _detect_language, _encode_message, _lsp_uri, _parse_messages
from .wiring import LspClient, LspClientManager, lsp_manager

__all__ = [
    "_detect_language",
    "_encode_message",
    "_EXT_TO_LANG",
    "_LSP_SERVERS",
    "_lsp_uri",
    "_parse_messages",
    "LspClient",
    "LspClientManager",
    "lsp_manager",
]
