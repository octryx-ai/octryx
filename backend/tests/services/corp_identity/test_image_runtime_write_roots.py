"""Every runtime write root the code derives from the source tree is writable in the image."""

from __future__ import annotations

import importlib
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
IMAGE_ROOT = Path("/app")


def _runtime_write_roots() -> dict[str, Path]:
    request_audit = importlib.import_module("app.middleware.audit.request_audit")
    from app.services import corp_identity_service
    from app.services.analytics import service as analytics_service
    from app.web._helpers import workspace_artifacts

    return {
        "corporate identities": corp_identity_service.CORP_IDENTITY_ROOT,
        "office templates": workspace_artifacts._workspace_root() / "uploads" / "office-templates",
        "audit fallback": request_audit.AUDIT_FALLBACK_DEFAULT_FILE.parent,
        "report exports": analytics_service.REPORT_EXPORT_DIR,
    }


def _chowned_image_dirs() -> set[str]:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    joined = dockerfile.replace("\\\n", " ")
    owned: set[str] = set()
    for line in joined.splitlines():
        if "chown -R 10001:10001" in line:
            owned.update(re.findall(r"chown -R 10001:10001 ([^&\n]+)", line)[0].split())
    return owned


def test_every_source_tree_write_root_is_created_and_owned_by_the_runtime_user() -> None:
    owned = {Path(entry) for entry in _chowned_image_dirs()}
    missing = {}
    for name, root in _runtime_write_roots().items():
        in_image = IMAGE_ROOT / Path(root).resolve().relative_to(REPO_ROOT)
        if not any(in_image == directory or directory in in_image.parents for directory in owned):
            missing[name] = str(in_image)
    assert not missing, f"not writable by uid 10001 in the image: {missing}"
