"""Deterministic extractor for ``repository_manifest`` bronze records.

Maps the manifest scan (dependencies, Dockerfiles, CI pipelines, Helm charts,
Kubernetes manifests) into the knowledge graph:

- ``library`` nodes shared ACROSS repositories (same group:artifact = same
  node) with ``depends_on`` edges carrying the per-repo version — answers
  "which repos use X?" deterministically.
- ``container_image`` nodes for base images and deployed images, with
  ``based_on`` (Dockerfile FROM) and ``deploys`` (Helm/K8s) edges — the bridge
  from source repo to what actually runs.
- Superseding ``ci_pipeline`` / ``container_build`` claims on the repository
  node (a re-scan replaces them; stale build facts are noise).
"""

from __future__ import annotations

from .images import _normalized_image, _upsert_image_node
from .ingest import ingest_repository_manifest

__all__ = ["_normalized_image", "_upsert_image_node", "ingest_repository_manifest"]
