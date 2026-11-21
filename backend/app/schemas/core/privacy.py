from pydantic import BaseModel, Field


class RetentionPolicyRequest(BaseModel):
    entity_type: str = Field(min_length=1, max_length=80)
    ttl_days: int = Field(ge=1, le=3650)
    action: str = Field(min_length=1, max_length=20)
    is_active: bool = True


class DeletionRequestCreate(BaseModel):
    target_user_id: str = Field(min_length=1, max_length=36)
    reason: str | None = Field(default=None, max_length=4000)
