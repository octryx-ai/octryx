from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from ..core.workspace_ref import OptionalWorkspaceId


class DataExportJobCreateRequest(BaseModel):
    export_type: Literal[
        "admin_config_backup",
        "project_backup",
        "knowledge_export",
        "user_data_gdpr",
        "task_definitions",
        "agent_definitions",
    ]
    scope_type: Literal["project", "user", "global"]
    scope_id: str | None = Field(default=None, min_length=1)
    format: Literal["json", "csv", "yaml", "zip"] = "json"
    include_sensitive: bool = False


class DataImportJobCreateRequest(BaseModel):
    import_type: Literal["admin_config_backup", "knowledge", "tasks", "users", "skills", "agent_definitions"]
    source_format: Literal["json", "csv", "yaml"] = "json"
    payload_json: Any | None = None
    payload_text: str | None = None
    target_project_id: OptionalWorkspaceId = Field(default=None, min_length=1)
    overwrite_existing: bool = False
    restore_sections: list[str] | None = None
    # Workspace restore: platform-wide skills that already exist are kept unless this is set.
    overwrite_skills: bool = False

    @model_validator(mode="after")
    def validate_payload(self) -> DataImportJobCreateRequest:
        if self.payload_json is None and not str(self.payload_text or "").strip():
            raise ValueError("payload_json or payload_text is required")
        return self
