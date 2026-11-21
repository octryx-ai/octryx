"""Deterministic code-structure snapshot tool.

Mirrors the ``aws_topology_snapshot`` pattern for source code: a bounded,
read-only, evidence-only collection of packages, classes/interfaces/enums,
fields, methods, and literal relations (extends/implements from declaration
lines, imports as ``uses`` edges, package containment). The result carries a
``diagram_brief`` that the deterministic diagram builders render from —
no invented members, no heuristic guessing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .code_impl._code_structure_parsers import LANGUAGE_SUFFIXES, language_for_suffix, parse_file_structure
from .context import ToolContext

_DEFAULT_MAX_FILES = 500
_MAX_FILES_CAP = 2000
_DEFAULT_MAX_SYMBOLS = 60
_MAX_SYMBOLS_CAP = 400
_MAX_MEMBERS_PER_CLASS = 12
_MAX_EDGES = 300
# Real DSL config repos carry central declaration files well above 512KB
# (a large INI project file ~600KB); node output stays bounded by
# max_symbols/_MAX_EDGES regardless of file size.
_MAX_FILE_BYTES = 2_000_000

_EXCLUDED_DIR_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".idea",
        ".vscode",
        "__pycache__",
        "node_modules",
        "target",
        "build",
        "dist",
        "out",
        ".venv",
        "venv",
        ".mypy_cache",
        ".pytest_cache",
        ".gradle",
        "vendor",
        "generated",
    }
)


def _bounded_int(value: Any, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed <= 0:
        return default
    return min(parsed, maximum)


def _requested_languages(params: dict[str, Any]) -> set[str]:
    requested = {
        str(item).strip().lower()
        for item in (params.get("languages") or [])
        if str(item).strip()
    }
    known = requested & set(LANGUAGE_SUFFIXES)
    return known or set(LANGUAGE_SUFFIXES)


def _search_roots(workspace_root: Path, params: dict[str, Any], warnings: list[str]) -> list[Path]:
    raw_paths = [str(item).strip() for item in (params.get("paths") or []) if str(item).strip()]
    if not raw_paths:
        return [workspace_root]
    roots: list[Path] = []
    for raw in raw_paths:
        candidate = (workspace_root / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
        if not str(candidate).startswith(str(workspace_root)):
            warnings.append(f"path outside workspace skipped: {raw}")
            continue
        if not candidate.exists():
            warnings.append(f"path not found: {raw}")
            continue
        roots.append(candidate)
    return roots


def _iter_source_files(roots: list[Path], languages: set[str], max_files: int) -> tuple[list[tuple[Path, str]], bool]:
    suffixes = {suffix: language for language in languages for suffix in LANGUAGE_SUFFIXES[language]}
    selected: list[tuple[Path, str]] = []
    truncated = False
    for root in roots:
        if root.is_file():
            language = language_for_suffix(root.suffix)
            if language in languages:
                selected.append((root, language))
            continue
        # sorted walk => deterministic file order independent of mtime
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if any(part in _EXCLUDED_DIR_NAMES for part in path.parts):
                continue
            language = suffixes.get(path.suffix.lower(), "")
            if not language:
                continue
            if len(selected) >= max_files:
                truncated = True
                return selected, truncated
            selected.append((path, language))
    return selected, truncated


def _bounded_members(members: list[str]) -> tuple[list[str], int]:
    if len(members) <= _MAX_MEMBERS_PER_CLASS:
        return list(members), 0
    hidden = len(members) - _MAX_MEMBERS_PER_CLASS
    return [*members[:_MAX_MEMBERS_PER_CLASS], f"+{hidden} more"], hidden


def _resolve_relation_target(
    name: str,
    *,
    package: str,
    imports: list[str],
    refs_by_simple_name: dict[str, list[str]],
) -> str:
    candidates = refs_by_simple_name.get(name) or []
    if not candidates:
        return ""
    if len(candidates) == 1:
        return candidates[0]
    same_package_ref = f"class:{package}.{name}" if package else f"class:{name}"
    if same_package_ref in candidates:
        return same_package_ref
    for imported in imports:
        imported_ref = f"class:{imported}"
        if imported.rsplit(".", 1)[-1] == name and imported_ref in candidates:
            return imported_ref
    return ""


def _package_quota_selection(
    class_nodes: dict[str, dict[str, Any]],
    max_symbols: int,
    relation_degree: Any,
    warnings: list[str],
) -> list[str]:
    """Round-robin across package directories, degree-first within each.

    Every package keeps at least one node (as long as the package count fits
    the symbol bound); per-package truncation is stated explicitly instead of
    silently dropping whole modules.
    """
    by_package: dict[str, list[dict[str, Any]]] = {}
    for node in class_nodes.values():
        by_package.setdefault(str(node["attributes"].get("package") or ""), []).append(node)
    for members in by_package.values():
        members.sort(key=lambda item: (-relation_degree(item), item["ref"]))
    package_order = sorted(by_package)
    selected_refs: list[str] = []
    round_index = 0
    while len(selected_refs) < max_symbols:
        took_any = False
        for package in package_order:
            members = by_package[package]
            if round_index >= len(members) or len(selected_refs) >= max_symbols:
                continue
            selected_refs.append(members[round_index]["ref"])
            took_any = True
        if not took_any:
            break
        round_index += 1
    kept_by_package: dict[str, int] = {}
    for ref in selected_refs:
        package = str(class_nodes[ref]["attributes"].get("package") or "")
        kept_by_package[package] = kept_by_package.get(package, 0) + 1
    for package in package_order:
        total = len(by_package[package])
        kept = kept_by_package.get(package, 0)
        if kept < total:
            warnings.append(
                f"package {package or '(root)'}: {kept} of {total} blocks selected (max_symbols)"
            )
    return selected_refs


def collect_code_structure_snapshot(workspace_root: str | Path, params: dict[str, Any]) -> dict[str, Any]:
    root = Path(workspace_root).resolve()
    warnings: list[str] = []
    if not root.exists() or not root.is_dir():
        return {"error": f"workspace root not found: {root}"}

    max_files = _bounded_int(params.get("max_files"), default=_DEFAULT_MAX_FILES, maximum=_MAX_FILES_CAP)
    max_symbols = _bounded_int(params.get("max_symbols"), default=_DEFAULT_MAX_SYMBOLS, maximum=_MAX_SYMBOLS_CAP)
    languages = _requested_languages(params)
    roots = _search_roots(root, params, warnings)

    files, files_truncated = _iter_source_files(roots, languages, max_files)
    if files_truncated:
        warnings.append(f"file enumeration truncated at max_files={max_files}")
    if not files:
        # An empty workspace is not evidence: report it explicitly instead of
        # returning a zero-node "success" that downstream renderers could
        # mistake for a parsed codebase.
        return {
            "error": (
                "no matching source files found in the session workspace; "
                "fetch the repository first (for example with prepare_bitbucket_repository) "
                "and then rerun code_structure_snapshot"
            ),
            "workspace": str(root),
            "scope": {
                "languages": sorted(languages) if languages else [],
                "paths": [str(item) for item in (params.get("paths") or [])],
            },
            "warnings": warnings,
        }

    parsed_files: list[dict[str, Any]] = []
    counts_by_language: dict[str, int] = {}
    for path, language in files:
        try:
            if path.stat().st_size > _MAX_FILE_BYTES:
                warnings.append(f"file skipped (too large): {path.relative_to(root)}")
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            warnings.append(f"file unreadable: {path.relative_to(root)} ({exc.__class__.__name__})")
            continue
        relative = str(path.relative_to(root))
        structure = parse_file_structure(relative, text, language)
        structure["file"] = relative
        structure["language"] = language
        counts_by_language[language] = counts_by_language.get(language, 0) + 1
        parsed_files.append(structure)

    # ── assemble nodes ──────────────────────────────────────────────────────
    class_nodes: dict[str, dict[str, Any]] = {}
    refs_by_simple_name: dict[str, list[str]] = {}
    packages: dict[str, int] = {}
    for structure in parsed_files:
        package = str(structure.get("package") or "")
        for declared in structure.get("types") or []:
            name = str(declared.get("name") or "")
            if not name:
                continue
            qualified = f"{package}.{name}" if package else name
            ref = f"class:{qualified}"
            if ref in class_nodes:
                continue
            fields, fields_hidden = _bounded_members(list(declared.get("fields") or []))
            methods, methods_hidden = _bounded_members(list(declared.get("methods") or []))
            extra_attributes = dict(declared.get("attributes") or {})
            class_nodes[ref] = {
                "ref": ref,
                "type": str(declared.get("kind") or "class"),
                "label": name,
                "attributes": {
                    **extra_attributes,
                    "package": package,
                    "file": structure["file"],
                    "language": structure["language"],
                    "fields": fields,
                    "methods": methods,
                    "fields_truncated": fields_hidden,
                    "methods_truncated": methods_hidden,
                },
                "_relations": {
                    "extends": list(declared.get("extends") or []),
                    "implements": list(declared.get("implements") or []),
                    "uses": list(declared.get("uses") or []),
                    "uses_packages": list(declared.get("uses_packages") or []),
                    "imports": list(structure.get("imports") or []),
                },
            }
            refs_by_simple_name.setdefault(name, []).append(ref)
            if package:
                packages[package] = packages.get(package, 0) + 1

    # ── select nodes deterministically (bounded) ────────────────────────────
    symbols_truncated = len(class_nodes) > max_symbols
    if symbols_truncated:
        warnings.append(f"class selection truncated at max_symbols={max_symbols} of {len(class_nodes)}")

    def _relation_degree(node: dict[str, Any]) -> int:
        relations = node["_relations"]
        return len(relations["extends"]) + len(relations["implements"]) + len(relations["uses"])

    if "terraform" in counts_by_language:
        # Module-quota selection: infrastructure snapshots must represent
        # EVERY module directory. A global degree-first cut silently drops
        # weakly-wired modules from the brief; round-robin across packages
        # (degree-first within each) keeps per-module coverage deterministic.
        selected_refs = _package_quota_selection(class_nodes, max_symbols, _relation_degree, warnings)
    else:
        selected_refs = [
            node["ref"]
            for node in sorted(class_nodes.values(), key=lambda item: (-_relation_degree(item), item["ref"]))
        ][:max_symbols]
    selected_set = set(selected_refs)

    selected_nodes: list[dict[str, Any]] = []
    selected_packages: set[str] = set()
    selected_count_by_package: dict[str, int] = {}
    for ref in sorted(selected_refs):
        node = class_nodes[ref]
        package = node["attributes"]["package"]
        if package:
            selected_packages.add(package)
            selected_count_by_package[package] = selected_count_by_package.get(package, 0) + 1
        selected_nodes.append({key: value for key, value in node.items() if key != "_relations"})
    for package in sorted(selected_packages):
        selected_nodes.append(
            {
                "ref": f"package:{package}",
                "type": "package",
                "label": package,
                "attributes": {
                    "class_count": packages.get(package, 0),
                    "selected_count": selected_count_by_package.get(package, 0),
                },
            }
        )

    # ── edges from literal evidence only ────────────────────────────────────
    edges: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str, str]] = set()
    edges_truncated = False

    def _add_edge(source_ref: str, target_ref: str, edge_type: str) -> None:
        nonlocal edges_truncated
        if not source_ref or not target_ref or source_ref == target_ref:
            return
        key = (source_ref, target_ref, edge_type)
        if key in seen_edges:
            return
        if len(edges) >= _MAX_EDGES:
            edges_truncated = True
            return
        seen_edges.add(key)
        edges.append({"source_ref": source_ref, "target_ref": target_ref, "type": edge_type})

    for ref in sorted(selected_set):
        node = class_nodes[ref]
        package = node["attributes"]["package"]
        relations = node["_relations"]
        if package:
            _add_edge(ref, f"package:{package}", "belongs_to")
        for edge_type in ("extends", "implements"):
            for name in relations[edge_type]:
                target = _resolve_relation_target(
                    name, package=package, imports=relations["imports"], refs_by_simple_name=refs_by_simple_name
                )
                if target in selected_set:
                    _add_edge(ref, target, edge_type)
        # per-type literal references (e.g. `Plugins = ...` lists)
        for name in relations["uses"]:
            target = _resolve_relation_target(
                name, package=package, imports=relations["imports"], refs_by_simple_name=refs_by_simple_name
            )
            if target in selected_set:
                _add_edge(ref, target, "uses")
        # `${Prefix_Rest}` placeholder references -> package nodes; only an
        # unambiguous match to a known package counts, own package is covered
        # by belongs_to already
        for candidate in relations["uses_packages"]:
            matches = [
                selected
                for selected in sorted(selected_packages)
                if selected.lower() == candidate or selected.lower().rsplit(".", 1)[-1] == candidate
            ]
            if len(matches) == 1 and matches[0] != package:
                _add_edge(ref, f"package:{matches[0]}", "uses")
        for imported in relations["imports"]:
            simple = imported.rsplit(".", 1)[-1]
            imported_ref = f"class:{imported}"
            if imported_ref not in selected_set:
                candidates = refs_by_simple_name.get(simple) or []
                if len(candidates) != 1 or candidates[0] not in selected_set:
                    continue
                imported_ref = candidates[0]
            # extends/implements already carries the stronger literal relation
            if (ref, imported_ref, "extends") in seen_edges or (ref, imported_ref, "implements") in seen_edges:
                continue
            _add_edge(ref, imported_ref, "uses")
    if edges_truncated:
        warnings.append(f"edge selection truncated at max_edges={_MAX_EDGES}")

    return {
        "workspace": str(root),
        "generated_at": datetime.now(UTC).isoformat(),
        "service_summary": {
            "file_count": len(parsed_files),
            "class_count": len(class_nodes),
            "package_count": len(packages),
            "counts_by_language": counts_by_language,
        },
        "scope": {
            "paths": [str(item) for item in (params.get("paths") or [])],
            "languages": sorted(languages),
            "max_files": max_files,
            "max_symbols": max_symbols,
        },
        "diagram_brief": {
            "selected_nodes": selected_nodes,
            "selected_edges": edges,
            "truncated": bool(files_truncated or symbols_truncated or edges_truncated),
        },
        "warnings": warnings,
    }


class CodeStructureSnapshotTool:
    name = "code_structure_snapshot"
    description = (
        "Return a bounded, read-only, diagram-ready code-structure snapshot of the workspace: packages, "
        "classes/interfaces/enums with declared fields and methods, and literal extends/implements/uses "
        "relations. Use this before drawing class, component, or data-model diagrams of source code."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        workspace_root = str(context.workspace_root or "").strip()
        if not workspace_root:
            return {"error": "workspace root is not configured for this session"}
        return collect_code_structure_snapshot(workspace_root, params or {})
