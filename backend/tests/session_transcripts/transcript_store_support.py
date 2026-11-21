"""Session transcripts: the artifact store on the filesystem in a temp dir.

``artifact_dir`` is autouse: a test module that imports it by name gets it for every test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.artifact_store import service as artifact_service


@pytest.fixture(autouse=True)
def artifact_dir(tmp_path, monkeypatch) -> Path:
    monkeypatch.setattr(artifact_service.settings, "artifact_store_dir", str(tmp_path))
    monkeypatch.setattr(artifact_service.settings, "artifact_store_backend", "filesystem")
    return tmp_path
