from __future__ import annotations

import importlib
from pathlib import Path

_DEFAULT_WORKSPACE_ROOT = Path(__file__).resolve().parents[3]


def resolve_app_workspace_root() -> Path:
    """Resolve the repository root used for repo-aware project capabilities."""

    try:
        web_context = importlib.import_module("app.web._context")
        candidate = getattr(web_context, "WORKSPACE_ROOT", None)
        if candidate:
            return Path(candidate).resolve()
    except Exception:
        pass
    return _DEFAULT_WORKSPACE_ROOT.resolve()

