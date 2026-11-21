"""Log messages built from provider, connector or subprocess failures carry a closed code and a class name.

``logger.exception`` / ``exc_info`` stay allowed (operator-only tracebacks); the message arguments
never carry the exception text, a provider response body, or a caller's name.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import httpx
import pytest

from app.plugins.mcp import oauth as mcp_oauth
from app.plugins.mcp.models import OAuthConfig

APP = Path(__file__).resolve().parents[1] / "app"
LEAKY = "denied for ghp_X7" + "fakeTokenAbcdefghijklmnopqrstuvwxyz0123 at https://user:tok3n@idp.internal/token"

# Areas swept completely in X7: channel/MCP plugins, STT/TTS providers, the channel router and
# the scheduler. A new log call there must not reintroduce raw exception or response text.
SWEPT = [
    "plugins",
    "services/stt",
    "services/tts",
    "services/channel_router_runtime",
    "services/teams_calling",
    "services/speaker",
    "scheduler",
    "mash",
]
_LEVELS = {"debug", "info", "warning", "error", "critical"}
_SAFE_CALLS = {"error_text", "error_type", "error_facts", "len", "person_log_ref"}


def _raw_text_arguments(tree: ast.AST) -> list[int]:
    """Line numbers of log calls whose arguments use a bound exception or a ``.text`` body raw."""
    hits: list[int] = []

    def visit(node: ast.AST, bound: frozenset[str]) -> None:
        if isinstance(node, ast.ExceptHandler) and node.name:
            bound = bound | {node.name}
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _LEVELS
            and "log" in ast.unparse(node.func.value).lower()
        ):
            for argument in node.args:
                if _is_raw(argument, bound):
                    hits.append(node.lineno)
                    break
        for child in ast.iter_child_nodes(node):
            visit(child, bound)

    visit(tree, frozenset())
    return hits


def _is_raw(node: ast.AST, bound: frozenset[str]) -> bool:
    if isinstance(node, ast.Call):
        name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
        if name in _SAFE_CALLS:
            return False
    if isinstance(node, ast.Attribute):
        if node.attr in {"__name__", "code", "reason", "status_code", "value"}:
            return False
        if node.attr == "text":
            return True
    if isinstance(node, ast.Name):
        return node.id in bound
    return any(_is_raw(child, bound) for child in ast.iter_child_nodes(node))


@pytest.mark.parametrize("area", SWEPT)
def test_swept_areas_log_no_raw_exception_or_response_text(area):
    offenders = []
    for path in sorted((APP / area).rglob("*.py")):
        for line in _raw_text_arguments(ast.parse(path.read_text(encoding="utf-8"))):
            offenders.append(f"{path.relative_to(APP)}:{line}")
    assert offenders == []


def test_the_guard_catches_raw_exception_and_body_arguments():
    source = """
try:
    pass
except Exception as exc:
    logger.warning("failed: %s", exc)
    logger.warning(f"failed: {exc}")
    logger.warning("failed: %s", str(exc))
    logger.warning("body: %s", resp.text[:200])
    logger.warning("failed: %s", error_text("x_failed", exc))
    logger.warning("failed: %s", type(exc).__name__)
"""
    assert _raw_text_arguments(ast.parse(source)) == [5, 6, 7, 8]


@pytest.mark.asyncio
async def test_mcp_token_fetch_failure_logs_a_code_and_the_class(monkeypatch, caplog):
    class _FailingClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def post(self, *args, **kwargs):
            raise httpx.ConnectError(LEAKY)

    monkeypatch.setattr(mcp_oauth.httpx, "AsyncClient", _FailingClient)
    oauth = OAuthConfig(token_url="https://idp.internal/token", client_id="c", client_secret="s")

    with caplog.at_level(logging.WARNING, logger=mcp_oauth.__name__):
        assert await mcp_oauth._oauth_fetch_token(oauth) is False

    assert "mcp_oauth_token_fetch_failed error_type=ConnectError" in caplog.text
    for marker in ("ghp_X7fake", "tok3n", "idp.internal", "denied"):
        assert marker not in caplog.text
