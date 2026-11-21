"""Routers read ``_context``-owned values through the module, so a monkeypatch on it takes effect."""

from pathlib import Path

from app.web import _context as web_context
from app.web.routers import chat_upload_send


def test_web_context_router_reads_context_monkeypatch(monkeypatch) -> None:
    patched_workspace_root = Path("/tmp/wp-0173-router-root")

    monkeypatch.setattr(web_context, "WORKSPACE_ROOT", patched_workspace_root)

    assert chat_upload_send._context.WORKSPACE_ROOT == patched_workspace_root
