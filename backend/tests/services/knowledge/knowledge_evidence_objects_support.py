"""Shared helpers for the test_knowledge_evidence_objects_* modules."""

from __future__ import annotations

from app.services.knowledge.identity.workspace import WorkspaceId
from tests.knowledge_evidence_seed_support import new_workspace_id

PAYLOAD = b"Alpha datacenter in Zurich.\n\nBeta paragraph.\n"


def _workspace() -> WorkspaceId:
    return WorkspaceId.parse(new_workspace_id())
