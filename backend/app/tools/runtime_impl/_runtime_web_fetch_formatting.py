"""Formatting helpers for runtime web fetch tool responses."""

from __future__ import annotations

import re
from typing import Any

from ..markup import html_to_markdown
from ._runtime_cli_helpers import _truncate


def _is_html_content(content_type: str, text: str) -> bool:
    return "html" in content_type or text.lstrip().startswith("<")


def _markdown_to_text(markdown: str) -> str:
    return re.sub(r"\[[^\]]+\]\(([^)]+)\)", r"\1", markdown)


def format_web_fetch_content(text: str, *, content_type: str, requested_format: str) -> dict[str, Any]:
    fmt = requested_format.lower()

    if fmt == "html":
        return {"content": _truncate(text), "format": "html"}

    if _is_html_content(content_type, text) and fmt in ("markdown", "text"):
        converted = html_to_markdown(text)
        if fmt == "text":
            converted = _markdown_to_text(converted)
        return {"content": _truncate(converted), "format": fmt}

    return {"content": _truncate(text), "format": "text"}
