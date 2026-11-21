"""A check the platform proposes after a correction repeated (From Correction to Check; see the
check proposals API contract). The proposal's parts are JSON as the contract names them; the columns
the list filters and orders by are their own."""

import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, String

from ...db import Base
from ...time_utils import utc_now


def uuid_pk():
    return "chp_" + uuid.uuid4().hex


class CheckProposal(Base):
    __tablename__ = "check_proposals"

    id = Column(String(40), primary_key=True, default=uuid_pk)
    workspace_id = Column(String(36), nullable=False, index=True)
    signature_id = Column(String(64), nullable=False, index=True)
    state = Column(String(20), nullable=False, default="proposed", index=True)
    evidence = Column(JSON, nullable=False, default=dict)
    draft = Column(JSON, nullable=False, default=dict)
    message = Column(JSON, nullable=False, default=dict)
    old_instances = Column(JSON, nullable=False, default=dict)
    proof = Column(JSON, nullable=False, default=dict)
    severity = Column(String(20), nullable=False, default="warning")
    enabled = Column(Boolean, nullable=False, default=True)
    author = Column(JSON, nullable=False, default=dict)
    edits = Column(JSON, nullable=False, default=list)
    decision = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now, index=True)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)
