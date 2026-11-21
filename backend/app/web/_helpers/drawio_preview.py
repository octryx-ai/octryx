"""Standalone diagram preview page for diagram artifacts.

The page itself is the built frontend entry ``diagram-preview.html``
(``frontend/chat/src/chat/diagramPreviewEntry.tsx``), which renders the same
React ``DiagramViewer`` used inline in chat. The draw.io embed protocol and
the app.diagrams.net editor deep link therefore live exclusively in the
frontend (``drawioEditorUrl.ts``); this module only injects the diagram
payload into the built template.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

_PAYLOAD_MARKER = (
    '<script id="diagram-preview-payload" type="application/json">null</script>'
)


def _template_path() -> Path:
    return Path(__file__).resolve().parents[1] / "static" / "chat" / "diagram-preview.html"


def render_diagram_preview_html(payload: dict) -> str:
    data = {
        "xml": str(payload.get("diagram_xml") or ""),
        "title": str(payload.get("title") or "Diagram"),
        "diagram_id": str(payload.get("diagram_id") or ""),
    }
    template_path = _template_path()
    if not template_path.is_file():
        return _missing_template_page(data["title"])
    template = template_path.read_text(encoding="utf-8")
    encoded = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    filled = template.replace(
        _PAYLOAD_MARKER,
        f'<script id="diagram-preview-payload" type="application/json">{encoded}</script>',
        1,
    )
    if filled == template:
        return _missing_template_page(data["title"])
    return filled


def _missing_template_page(title: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8" /><title>{html.escape(title)}</title></head>
<body style="font-family: system-ui, sans-serif; background: #111827; color: #f8fafc;">
  <p style="padding: 2rem;">
    The diagram preview page is not built. Run <code>npm run build</code> in
    <code>frontend/chat</code> to generate it.
  </p>
</body>
</html>"""
