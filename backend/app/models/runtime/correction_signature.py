"""One mistake recognised across runs, per Workspace, repository and app (From Correction to Check).

Every correction of an agent's work (a review finding fixed, a person's change request or pull request comment, a
red pipeline's cause, a refused call answered by the next one) is kept under its signature: the check kind, the
file pattern and the normalised message (``services/workflow_runs/corrections``). ``repeats`` counts the
occurrences, ``occurrences`` keeps the newest ``max_occurrences`` with their run and a redacted excerpt.
``services/check_proposals`` proposes a check when ``repeats`` reaches the Workspace's threshold;
``over_threshold_at`` is when it first did.
"""

from __future__ import annotations

import secrets

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint

from ...db import Base
from ...time_utils import utc_now


def correction_signature_pk() -> str:
    return f"sig_{secrets.token_hex(10)}"


class CorrectionSignature(Base):
    __tablename__ = "correction_signatures"
    __table_args__ = (
        UniqueConstraint("project_id", "repository", "app", "signature_key", name="uq_correction_signatures_key"),
        Index("ix_correction_signatures_project_seen", "project_id", "last_seen"),
    )

    id = Column(String(40), primary_key=True, default=correction_signature_pk)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    repository = Column(String(300), nullable=False)
    app = Column(String(200), nullable=False)
    signature_key = Column(String(32), nullable=False)
    check_kind = Column(String(40), nullable=False)
    kind_hint = Column(String(40), nullable=False)
    file_pattern = Column(String(300), nullable=False)
    message = Column(Text, nullable=False)
    repeats = Column(Integer, nullable=False, default=0)
    first_seen = Column(DateTime, nullable=False, default=utc_now)
    last_seen = Column(DateTime, nullable=False, default=utc_now)
    over_threshold_at = Column(DateTime, nullable=True)
    occurrences = Column(JSON, nullable=False, default=list)
