from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.code_quality.repo_detection import AUTO_DETECTORS, REPO_LOCAL_DETECTORS, _unknown_payload
from app.services.code_quality.repo_files import _find_repo_root
from app.services.code_quality.toolchain_profile import (
    _finalize_code_quality_config,
    _repo_quality_overrides_from_project_config,
)


def load_repo_code_quality_config(cwd: Path, *, project_config: dict[str, Any] | None = None) -> dict[str, Any]:
    repo_root = _find_repo_root(cwd)
    project_overrides = _repo_quality_overrides_from_project_config(project_config=project_config, repo_root=repo_root)

    def finalize(base_payload: dict[str, Any], *, repo_local_config: bool) -> dict[str, Any]:
        return _finalize_code_quality_config(
            base_payload,
            project_config=project_config,
            project_overrides=project_overrides,
            repo_local_config=repo_local_config,
        )

    for detector in REPO_LOCAL_DETECTORS:
        base_payload = detector(repo_root)
        if base_payload is not None:
            return finalize(base_payload, repo_local_config=True)
    for detector in AUTO_DETECTORS:
        base_payload = detector(repo_root)
        if base_payload is not None:
            return finalize(base_payload, repo_local_config=False)
    return finalize(_unknown_payload(repo_root), repo_local_config=False)


__all__ = [
    "load_repo_code_quality_config",
]
