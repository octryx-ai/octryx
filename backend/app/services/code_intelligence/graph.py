"""Graph artifact builders and native persistence for code intelligence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.code_intelligence.graph_extractor import build_native_code_graph_payload
from app.services.code_intelligence.storage_runtime import (
    _code_graph_artifact_dir,
    _coerce_dict,
    _coerce_list,
    _now_iso,
    _truncate,
)


def _extract_import_targets(text: str, *, language: str) -> list[str]:
    targets: list[str] = []
    if language == "python":
        import re

        targets.extend(re.findall(r"^\s*from\s+([A-Za-z0-9_\.]+)\s+import\b", text, flags=re.MULTILINE))
        targets.extend(re.findall(r"^\s*import\s+([A-Za-z0-9_\.]+)", text, flags=re.MULTILINE))
    elif language in {"typescript", "javascript"}:
        import re

        targets.extend(re.findall(r"from\s+['\"]([^'\"]+)['\"]", text))
        targets.extend(re.findall(r"require\(\s*['\"]([^'\"]+)['\"]\s*\)", text))
    elif language == "go":
        import re

        targets.extend(re.findall(r"^\s*import\s+\"([^\"]+)\"", text, flags=re.MULTILINE))
        targets.extend(re.findall(r"^\s*\"([^\"]+)\"", text, flags=re.MULTILINE))
    elif language == "java":
        import re

        targets.extend(re.findall(r"^\s*import\s+([A-Za-z0-9_\.]+);", text, flags=re.MULTILINE))
    elif language in {"c", "cpp"}:
        import re

        targets.extend(re.findall(r"#include\s+[<\"]([^\">]+)[>\"]", text))
    return [target.strip() for target in targets if str(target).strip()]


def _module_candidates(relative_path: str, language: str) -> set[str]:
    path = Path(relative_path)
    candidates = {relative_path, path.stem}
    without_suffix = str(path.with_suffix(""))
    candidates.add(without_suffix)
    normalized = without_suffix.replace("/", ".")
    candidates.add(normalized)
    if language == "python" and path.name == "__init__.py":
        candidates.add(normalized.rsplit(".", 1)[0] if "." in normalized else path.parent.name)
    return {candidate for candidate in candidates if candidate}


def _best_graph_report(snapshot: dict[str, Any], *, node_count: int, edge_count: int, import_edge_count: int) -> str:
    language_pairs = sorted(
        _coerce_dict(snapshot.get("languages")).items(), key=lambda item: (-int(item[1]), str(item[0]))
    )
    top_files = sorted(
        _coerce_list(snapshot.get("files")),
        key=lambda item: (-int(item.get("line_count") or 0), str(item.get("path") or "")),
    )[:5]
    lines = [
        "# Code Graph Report",
        "",
        f"- Files: {int(snapshot.get('file_count') or 0)}",
        f"- Symbols: {int(snapshot.get('symbol_count') or 0)}",
        f"- Graph nodes: {node_count}",
        f"- Graph edges: {edge_count}",
        f"- Import edges: {import_edge_count}",
        "",
        "## Languages",
    ]
    if language_pairs:
        lines.extend([f"- {language}: {count}" for language, count in language_pairs[:8]])
    else:
        lines.append("- none")
    lines.extend(["", "## Largest files"])
    if top_files:
        lines.extend(
            f"- {item.get('path')}: {int(item.get('line_count') or 0)} lines"
            for item in top_files
            if isinstance(item, dict)
        )
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


async def _maybe_build_graphify_artifacts(
    *, repository_id: str, repo_root: Path, snapshot: dict[str, Any]
) -> dict[str, Any]:
    output_dir = _code_graph_artifact_dir(repository_id)
    graph_json_path = output_dir / "graph.json"
    graph_report_path = output_dir / "CODE_GRAPH_REPORT.md"

    graph_payload = build_native_code_graph_payload(repo_root=repo_root, snapshot=snapshot)
    import_edge_count = sum(1 for edge in _coerce_list(graph_payload.get("edges")) if edge.get("kind") == "imports")
    graph_payload = {
        "repo_root": str(repo_root),
        "generated_at": _now_iso(),
        **graph_payload,
    }
    report = _best_graph_report(
        snapshot,
        node_count=int(graph_payload.get("node_count") or 0),
        edge_count=int(graph_payload.get("edge_count") or 0),
        import_edge_count=import_edge_count,
    )
    graph_json_path.write_text(json.dumps(graph_payload, indent=2), encoding="utf-8")
    graph_report_path.write_text(report, encoding="utf-8")
    return {
        "status": "ready",
        "backend": "code_graph",
        "output_dir": str(output_dir),
        "graph_path": str(graph_json_path),
        "report_path": str(graph_report_path),
        "node_count": int(graph_payload.get("node_count") or 0),
        "edge_count": int(graph_payload.get("edge_count") or 0),
        "import_edge_count": import_edge_count,
        "unresolved_reference_count": int(graph_payload.get("unresolved_reference_count") or 0),
        "graph_payload": graph_payload,
        "report_excerpt": _truncate(report, max_chars=1200),
    }


__all__ = ["_best_graph_report", "_extract_import_targets", "_module_candidates", "_maybe_build_graphify_artifacts"]
