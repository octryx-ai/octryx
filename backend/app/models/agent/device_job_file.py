"""A file a device job made on the person's Mac, fetched on their request (Octryx Mobile).

The device lists the files a turn changed by name (a ``files`` job event); nothing leaves the Mac until the owner
asks for one. Then a row here is ``pending`` until the channel asks the device (``sent``), and ``ready`` with the
content once the device sent it, or ``failed`` with the device's or the platform's reason. Content is kept for a
day (``services/devices/job_files``).
"""

from __future__ import annotations

import secrets

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, LargeBinary, String

from ...db import Base
from ...time_utils import utc_now


def job_file_pk() -> str:
    return f"jf_{secrets.token_hex(10)}"


class DeviceJobFile(Base):
    __tablename__ = "device_job_files"
    __table_args__ = (
        Index("ix_device_job_files_device_state", "device_id", "state"),
        Index("ix_device_job_files_owner_created", "owner_user_id", "created_at"),
    )

    id = Column(String(40), primary_key=True, default=job_file_pk)
    job_id = Column(String(40), ForeignKey("device_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    device_id = Column(String(40), ForeignKey("user_devices.id", ondelete="CASCADE"), nullable=False)
    owner_user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    path = Column(String(500), nullable=False)
    state = Column(String(20), nullable=False)
    reason = Column(String(60), nullable=True)
    size = Column(Integer, nullable=True)
    sha256 = Column(String(64), nullable=True)
    content = Column(LargeBinary, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, nullable=False)


__all__ = ["DeviceJobFile", "job_file_pk"]
