"""The Knowledge module never imports one of the listed outside Knowledge layers (contract §9.14).

The rule is structural (a second path would bypass the governed ledger): no module under
``app/services/knowledge`` imports a listed package, at module level or inside a function.
"""

from __future__ import annotations

import ast
from pathlib import Path

import app.services.knowledge as knowledge

OUTSIDE_LAYERS = frozenset(
    {
        "agent_learning",
        "document_ingestion",
        "engineering_knowledge",
        "knowledge_access_policy",
        "knowledge_chunking",
        "knowledge_code_bridge_context_service",
        "knowledge_code_bridge_service",
        "knowledge_embedding",
        "knowledge_eval",
        "knowledge_graph",
        "knowledge_medallion",
        "knowledge_prefetch",
        "knowledge_provenance_service",
        "knowledge_quality",
        "knowledge_quality_scoring",
        "knowledge_quality_validation",
        "knowledge_relation",
        "knowledge_result_compaction",
        "knowledge_retrieval",
        "knowledge_source_people",
        "knowledge_sync",
        "knowledge_trust",
        "mcp_knowledge",
        "memory",
        "prefetch",
        "project_memory",
        "repo_knowledge",
        "repo_project_memory_sync",
        "repo_project_memory_sync_service",
    }
)
MODULE_ROOT = Path(knowledge.__file__).parent


def _package_of(path: Path) -> list[str]:
    """Dotted package of a module file, as ``["app", "services", ...]``."""
    return list(path.relative_to(MODULE_ROOT.parents[2]).parent.parts)


def _imported_services(path: Path, package: list[str]) -> set[str]:
    """First segment below ``app.services`` of every import in ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)]
                parts = base + (node.module.split(".") if node.module else [])
                names = [alias.name for alias in node.names] if not node.module else []
            else:
                parts = (node.module or "").split(".")
                names = []
            candidates = [parts] + [parts + [name] for name in names]
        elif isinstance(node, ast.Import):
            candidates = [alias.name.split(".") for alias in node.names]
        else:
            continue
        for dotted in candidates:
            if dotted[:2] == ["app", "services"] and len(dotted) > 2:
                found.add(dotted[2])
    return found


def test_the_knowledge_module_imports_no_outside_layer() -> None:
    sources = sorted(MODULE_ROOT.rglob("*.py"))
    assert sources
    offenders = {
        path.relative_to(MODULE_ROOT).as_posix(): sorted(_imported_services(path, _package_of(path)) & OUTSIDE_LAYERS)
        for path in sources
    }
    assert {name: layers for name, layers in offenders.items() if layers} == {}


def test_the_boundary_check_sees_relative_and_nested_imports(tmp_path: Path) -> None:
    """The detector itself: a relative import of an outside layer inside a function is caught."""
    probe = tmp_path / "probe.py"
    probe.write_text("def f():\n    from ..knowledge_graph import store\n    return store\n", encoding="utf-8")
    assert _imported_services(probe, ["app", "services", "knowledge"]) == {"knowledge_graph"}
