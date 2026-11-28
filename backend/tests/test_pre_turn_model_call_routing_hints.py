"""A stored routing hint never decides the next turn's runtime resolution, and routing modules import no provider factory or runtime resolution."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.workflow_proposals


ERROR_EVIDENCE = "I am seeing a stack trace: the simulation failed with a SQLServerException after a read timed out."






_ROUTING_MODULES = (
    "app/web/_helpers/chat_turn_prepare.py",
    "app/services/session/turn_prepare.py",
    "app/services/session/turn_routing_resolution.py",
    "app/services/session/turn_runtime_selection.py",
    "app/services/session/turn_agent_selection.py",
    "app/services/session/turn_start.py",
    "app/services/execution_strategy_service.py",
)


_FORBIDDEN_ROUTING_IMPORTS = {
    "get_provider",
    "resolve_control_plane_runtimes",
    "resolve_control_plane_runtime",
    "_resolve_control_plane_runtimes_impl",
}








def test_routing_modules_import_no_provider_factory_or_runtime_resolution():
    backend_root = Path(__file__).resolve().parents[1]
    for relative in _ROUTING_MODULES:
        tree = ast.parse((backend_root / relative).read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imported.update(alias.name for alias in node.names)
                assert "providers" not in module.split("."), f"{relative} imports {module}"
                assert not module.endswith("control_plane.resolution"), f"{relative} imports {module}"
            elif isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
        assert not imported & _FORBIDDEN_ROUTING_IMPORTS, f"{relative} imports {imported & _FORBIDDEN_ROUTING_IMPORTS}"
