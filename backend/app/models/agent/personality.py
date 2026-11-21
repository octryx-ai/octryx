import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now


def uuid_pk():
    return str(uuid.uuid4())


class Personality(Base):
    __tablename__ = "personalities"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    user_id = Column(String(36), ForeignKey("users.id"), unique=True, nullable=False)
    language = Column(String(10), default="en")
    detail_level = Column(String(20), default="standard")
    communication_style = Column(String(50), default="technical")
    output_format = Column(String(50), default="full")
    custom_prompt = Column(Text, nullable=True)
    timezone = Column(String(50), default="UTC")
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    user = relationship("User", back_populates="personality")
