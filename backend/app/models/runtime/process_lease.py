"""Liveness leases of the platform processes that own running turns."""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Index, String

from ...db import Base


class RuntimeProcessLease(Base):
    """One platform process's liveness lease; ``expires_at`` is measured on the database clock."""

    __tablename__ = "runtime_process_leases"
    __table_args__ = (Index("ix_runtime_process_leases_expires_at", "expires_at"),)

    id = Column(String(36), primary_key=True)
    started_at = Column(DateTime, nullable=False)
    heartbeat_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)


__all__ = ["RuntimeProcessLease"]
