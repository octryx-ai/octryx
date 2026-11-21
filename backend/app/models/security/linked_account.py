"""A platform user's account on an external platform (``services/linked_accounts``): the one home that reviewer,
author and assignee resolution reads.

One row per user and platform. ``account_id`` holds an Atlassian account id, ``username`` an SCM login or a
Jira/Bitbucket Server username (``services/linked_accounts/contract.PLATFORMS`` says which one a platform uses).
``verification_status`` is ``unverified`` until a Workspace connection confirmed the account, ``verified`` once it
did and ``failed`` when the connection did not know it; any change of the identifier resets it to ``unverified``.
"""

import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now


def uuid_pk() -> str:
    return str(uuid.uuid4())


class UserLinkedAccount(Base):
    __tablename__ = "user_linked_accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "platform", name="uq_user_linked_accounts_user_platform"),
        Index("ix_user_linked_accounts_platform_account", "platform", "account_id"),
        Index("ix_user_linked_accounts_platform_username", "platform", "username"),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    platform = Column(String(40), nullable=False)
    account_id = Column(String(255), nullable=True)
    username = Column(String(255), nullable=True)
    display_name = Column(String(255), nullable=True)
    verification_status = Column(String(20), nullable=False, default="unverified")
    verified_at = Column(DateTime, nullable=True)
    verification_json = Column(JSON, default=dict, nullable=False)
    source = Column(String(40), nullable=False, default="self")
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    user = relationship("User", foreign_keys=[user_id])
