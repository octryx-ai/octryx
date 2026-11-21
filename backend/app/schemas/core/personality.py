from pydantic import BaseModel, ConfigDict


class PersonalityUpdate(BaseModel):
    language: str | None = None
    detail_level: str | None = None
    communication_style: str | None = None
    output_format: str | None = None
    custom_prompt: str | None = None
    timezone: str | None = None


class PersonalityResponse(BaseModel):
    id: str
    user_id: str
    language: str
    detail_level: str
    communication_style: str
    output_format: str
    custom_prompt: str | None
    timezone: str
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)
