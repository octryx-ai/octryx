"""Runtime path/coercion/snapshot helpers for code intelligence storage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.code_intelligence.storage_constants import _CODE_INTELLIGENCE_DIR, _REPO_ROOT

from ...time_utils import utc_now_aware


def _now_iso() -> str:
    return utc_now_aware().isoformat()


def _code_intelligence_root() -> Path:
    _CODE_INTELLIGENCE_DIR.mkdir(parents=True, exist_ok=True)
    return _CODE_INTELLIGENCE_DIR


def _repository_storage_dir(repository_id: str) -> Path:
    path = _code_intelligence_root() / repository_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _latest_snapshot_path(repository_id: str) -> Path:
    return _repository_storage_dir(repository_id) / "latest.json"


def _zoekt_index_dir(repository_id: str) -> Path:
    path = _repository_storage_dir(repository_id) / "zoekt-index"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _scip_index_dir(repository_id: str) -> Path:
    path = _repository_storage_dir(repository_id) / "scip"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _scip_snapshot_dir(repository_id: str, language: str) -> Path:
    path = _scip_index_dir(repository_id) / f"{language}-snapshot"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _scip_native_index_path(repository_id: str, language: str) -> Path:
    return _scip_index_dir(repository_id) / f"{language}-native-index.json"


def _code_graph_artifact_dir(repository_id: str) -> Path:
    path = _repository_storage_dir(repository_id) / "code_graph"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _structure_artifact_dir(repository_id: str) -> Path:
    path = _repository_storage_dir(repository_id) / "structure"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _normalize_path(raw: Any) -> Path:
    value = Path(str(raw or "").strip()).expanduser()
    return value.resolve() if value.is_absolute() else (_REPO_ROOT / value).resolve()


def _coerce_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _coerce_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _truncate(value: str, *, max_chars: int = 400) -> str:
    text = str(value or "")
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


def _read_snapshot(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_snapshot(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def _normalize_repository_payload(payload: dict[str, Any]) -> dict[str, Any]:
    provider = str(payload.get("provider") or "local").strip().lower() or "local"
    index_backend = str(payload.get("index_backend") or "auto").strip().lower() or "auto"
    semantic_backend = str(payload.get("semantic_backend") or "auto").strip().lower() or "auto"
    structure_backend = str(payload.get("structure_backend") or "auto").strip().lower() or "auto"
    graph_backend = str(payload.get("graph_backend") or "disabled").strip().lower() or "disabled"
    config_json = _coerce_dict(payload.get("config_json"))
    repo_root = _normalize_path(payload.get("repo_root"))
    return {
        "name": str(payload.get("name") or repo_root.name or "repository").strip() or "repository",
        "description": str(payload.get("description") or "").strip(),
        "repo_root": str(repo_root),
        "provider": provider,
        "remote_url": str(payload.get("remote_url") or "").strip() or None,
        "default_branch": str(payload.get("default_branch") or "main").strip() or "main",
        "index_backend": index_backend,
        "semantic_backend": semantic_backend,
        "structure_backend": structure_backend,
        "graph_backend": graph_backend,
        "config_json": config_json,
        "is_active": bool(payload.get("is_active", True)),
    }
