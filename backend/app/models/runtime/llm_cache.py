import uuid

from sqlalchemy import JSON, Column, DateTime, Index, Integer, String

from ...db import Base
from ...time_utils import utc_now


def uuid_pk():
    return str(uuid.uuid4())


class LLMCacheEntry(Base):
    __tablename__ = "llm_cache_entries"
    __table_args__ = (
        Index(
            "ix_llm_cache_entries_prompt_provider_model",
            "prompt_hash",
            "provider_id",
            "model_id",
        ),
    )

    id = Column(String(36), primary_key=True, default=uuid_pk)
    prompt_hash = Column(String(64), nullable=False, index=True)
    provider_id = Column(String(100), nullable=False, index=True)
    model_id = Column(String(200), nullable=False, index=True)
    response_json = Column(JSON, nullable=False)
    hit_count = Column(Integer, nullable=False, default=0)
    cache_scope = Column(String(40), nullable=False, default="default", index=True)
    created_at = Column(DateTime, default=utc_now, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
