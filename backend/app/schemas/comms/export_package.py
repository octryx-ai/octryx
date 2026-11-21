from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from ..core.workspace_ref import OptionalWorkspaceId

PackageType = Literal["agent", "skill", "task"]


class ExportPackageCreateRequest(BaseModel):
    package_type: PackageType
    entity_id: str = Field(min_length=1, max_length=64)


class ImportPackageRequest(BaseModel):
    package_id: str | None = Field(default=None, min_length=1, max_length=64)
    package_json: dict[str, Any] | None = None
    overwrite_existing: bool = False
    target_project_id: OptionalWorkspaceId = Field(default=None, min_length=1, max_length=64)
    name_override: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_package_source(self) -> ImportPackageRequest:
        if not self.package_id and not self.package_json:
            raise ValueError("Either package_id or package_json is required")
        return self
