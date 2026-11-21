from sqlalchemy import Column, DateTime, String, Text

from ...db import Base
from ...time_utils import utc_now


class SystemConfig(Base):
    """Global key-value configuration store editable via the Admin UI."""

    __tablename__ = "system_config"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
