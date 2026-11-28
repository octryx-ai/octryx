"""A Workspace's Git token for one Bitbucket repository (Git over HTTPS); the value lives in stored_secrets."""

from __future__ import annotations

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def _uuid() -> str:
    return str(uuid.uuid4())


class RepositoryGitToken(WorkspaceBound, Base):
    __tablename__ = "repository_git_tokens"
    __table_args__ = (
        UniqueConstraint("project_id", "host_base", "repository_key", name="uq_repository_git_tokens_repository"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    # The Data Center instance (``https://host[/context]``) the token was checked against; it is sent nowhere else.
    host_base = Column(String(500), nullable=False)
    # ``bitbucket:<KEY>/<slug>`` (key upper-case, slug lower-case), the repository key of the workflow runs.
    repository_key = Column(String(300), nullable=False)
    secret_id = Column(String(36), ForeignKey("stored_secrets.id"), nullable=False)
    set_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    set_at = Column(DateTime, nullable=False, default=utc_now)


__all__ = ["RepositoryGitToken"]
