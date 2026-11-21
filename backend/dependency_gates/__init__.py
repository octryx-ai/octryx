"""Repository-local dependency adoption gates.

This package is governance tooling, not product code. It sits outside ``backend/app`` and outside
``[tool.setuptools.packages.find] include = ["app*"]``, so the built wheel does not contain it and no module under
``backend/app`` imports it. It is not sandboxed away from the runtime: ``Dockerfile`` copies the whole ``backend/``
tree into the image and the API runs from that source tree with ``WORKDIR /app/backend``, so the package is on the
container import path unless it is excluded from the build context.

What is true is that importing it does nothing: every module here depends only on the standard library, and an import
reads no file, resolves no dependency, opens no socket and writes nothing.

``tests/test_pydantic_ai_removed.py`` rejects ``pydantic-ai-slim`` in the declarations and the lock graph.
"""

from .harness_boundary import Violation, format_violations, scan_boundary
from .manifest import (
    GateDriftError,
    GateManifest,
    attestation_state,
    canonical_payload_digest,
    load_manifest,
)
from .repository_drift import check_manifest_against_repository

__all__ = [
    "GateDriftError",
    "GateManifest",
    "Violation",
    "attestation_state",
    "canonical_payload_digest",
    "check_manifest_against_repository",
    "format_violations",
    "load_manifest",
    "scan_boundary",
]
