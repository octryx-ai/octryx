"""Deterministic extractor for ``code_graph_summary`` bronze records.

Maps the compact module outline produced by the native code-graph index
(files, defined symbols, resolved imports) into the knowledge graph as the
code-internals skeleton: one ``module`` node per code file with a symbol
summary in its description, ``part_of``/``imports`` edges, and a superseding
``code_index`` claim on the repository node. Symbol-level detail (methods,
fields, calls) intentionally stays in the code-graph tables.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..store import replace_claims_of_type, upsert_node
from .common import slugify
from .structured_code import ingest_code_structure

# Symbol kinds named in module descriptions, with the label used in prose.
_SYMBOL_KIND_LABELS = (
    ("class", "classes"),
    ("interface", "interfaces"),
    ("enum", "enums"),
    ("record", "records"),
    ("function", "functions"),
    ("route", "routes"),
)
_NAMES_PER_KIND = 15
_IMPORTS_NAMED = 15


def _module_description(module: dict[str, Any], repository: str) -> str:
    path = str(module.get("path") or "").strip()
    name = str(module.get("name") or path).strip()
    language = str(module.get("language") or "").strip()
    parts = [f"Code module {name} ({path}) in {repository}" + (f" — {language}" if language else "")]
    symbols = module.get("symbols") if isinstance(module.get("symbols"), dict) else {}
    for kind, label in _SYMBOL_KIND_LABELS:
        names = [str(item).strip() for item in (symbols.get(kind) or []) if str(item).strip()]
        if names:
            listed = ", ".join(names[:_NAMES_PER_KIND])
            suffix = f" (+{len(names) - _NAMES_PER_KIND} more)" if len(names) > _NAMES_PER_KIND else ""
            parts.append(f"Defines {label}: {listed}{suffix}")
    imports = [str(item).strip() for item in (module.get("imports") or []) if str(item).strip()]
    if imports:
        listed = ", ".join(imports[:_IMPORTS_NAMED])
        suffix = f" (+{len(imports) - _IMPORTS_NAMED} more)" if len(imports) > _IMPORTS_NAMED else ""
        parts.append(f"Imports: {listed}{suffix}")
    return ". ".join(parts) + "."


async def ingest_code_graph_record(
    db: AsyncSession, *, project_id: str | None, record: dict[str, Any]
) -> dict[str, int] | None:
    """Ingest one ``code_graph_summary`` bronze value into the knowledge graph."""
    repository = str(record.get("repository_name") or "").strip()
    modules = record.get("modules") if isinstance(record.get("modules"), list) else []
    if not repository or not modules:
        return None

    enriched = [
        {
            **module,
            "description": _module_description(module, repository),
        }
        for module in modules
        if isinstance(module, dict) and str(module.get("path") or module.get("name") or "").strip()
    ]
    counts = await ingest_code_structure(
        db, project_id=project_id, snapshot={"repository": repository, "modules": enriched}
    )

    stats = record.get("stats") if isinstance(record.get("stats"), dict) else {}
    commit = str(record.get("current_head_commit") or "").strip() or None
    repo_node = await upsert_node(
        db,
        project_id=project_id,
        node_type="repository",
        node_key=slugify(f"repo-{repository}"),
        display_name=repository,
        description="",
        aliases=[repository, repository.split("/")[-1]],
    )
    statement = (
        f"{repository} code index"
        + (f" at commit {commit[:12]}" if commit else "")
        + f": {int(stats.get('file_count') or 0)} code files, "
        + f"{int(stats.get('node_count') or 0)} symbols, "
        + f"{int(stats.get('edge_count') or 0)} relations"
    )
    # A code index supersedes the previous one — stale stats claims are noise.
    await replace_claims_of_type(
        db,
        project_id=project_id,
        subject_node_id=repo_node.id,
        claim_type="code_index",
        claims=[
            {
                "statement": statement,
                "valid_from_label": (commit or "")[:12] or None,
                "source_refs": [f"repo:{repository}"],
            }
        ],
    )
    return counts


__all__ = ["ingest_code_graph_record"]
