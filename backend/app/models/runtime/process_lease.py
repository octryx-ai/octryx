"""Liveness leases of the platform processes that own running turns (runtime robustness R1).

A chat turn runs as an in-process task of exactly one platform process (API or
worker). When that process dies, nothing it owned can settle itself, so every
process holds one lease row here and renews it on a fixed heartbeat. A running
session or Product Run Attempt whose owning process has no unexpired lease is
owned by nobody and is settled explicitly as ``interrupted_by_restart``.

The row carries only the random per-boot process id and database-clock instants:
no host name, no PID, no free text.
"""

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
