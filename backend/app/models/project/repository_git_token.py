"""A per-repository Git token of a Workspace: Git over HTTPS for one Bitbucket repository.

A Bitbucket Data Center connection signed in with the OpenID Connect client credentials grant reads the REST API,
but ``/scm/...`` answers 500 for that Bearer token, so a server-side clone or push fails. An author therefore enters
a Bitbucket HTTP access token (repository or project scope) when registering the repository; it is checked against
exactly that repository and then used for Git only (``services/knowledge/sources/repository_git_token.py``).

One row per Workspace and repository (``host_base`` + ``repository_key`` ``bitbucket:<KEY>/<slug>``): the Knowledge
source sync and the workflow runs of the same Workspace on the same repository use it. The value lives only in
``stored_secrets`` (Fernet with the instance ``encryption_key``, ``services/secret``); this row holds its id and who
set it when, never the value. The foreign key makes this table a secret holder for ``services/secret/release.py``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint

from ...db import Base
from ...time_utils import utc_now


def _uuid() -> str:
    return str(uuid.uuid4())


class RepositoryGitToken(Base):
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
