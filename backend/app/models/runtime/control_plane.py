import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from ...db import Base
from ...db.workspace_bound import WorkspaceBound
from ...time_utils import utc_now


def uuid_pk():
    return str(uuid.uuid4())


def _string_list(value: list | None) -> list[str]:
    return [str(item).strip() for item in (value or []) if str(item).strip()]


class ControlPlaneConfig(Base):
    __tablename__ = "control_plane_config"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    name = Column(String(100), unique=True, nullable=False, default="default")
    provider_id = Column(String(36), ForeignKey("llm_providers.id"), nullable=True)
    model_id = Column(String(200), nullable=True)
    max_output_tokens_default = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    provider = relationship("LLMProvider")
    runtime_targets = relationship(
        "ControlPlaneRuntimeTarget",
        back_populates="config",
        cascade="all, delete-orphan",
        order_by="ControlPlaneRuntimeTarget.priority",
    )


class ControlPlaneRuntimeTarget(WorkspaceBound, Base):
    __workspace_column__ = None
    __workspace_owners__ = {"provider_id": "llm_providers"}
    __tablename__ = "control_plane_runtime_targets"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    config_id = Column(String(36), ForeignKey("control_plane_config.id"), nullable=False)
    provider_id = Column(String(36), ForeignKey("llm_providers.id"), nullable=False)
    model_id = Column(String(200), nullable=False)
    priority = Column(Integer, nullable=False, default=1)
    is_active = Column(Boolean, default=True)
    use_case_tags_json = Column(JSON, default=list)
    # Governed model capabilities the target serves, validated against the admin capability catalog;
    # ``turn_runtime_requirement`` reads them. Separate from the free-form use-case tags.
    capability_tags_json = Column(JSON, default=list)
    # Override of the sampling catalog (``agent/providers/sampling_capabilities``): True/False forces
    # whether the model gets an explicit temperature; None (default) lets the catalog decide.
    accepts_temperature = Column(Boolean, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    config = relationship("ControlPlaneConfig", back_populates="runtime_targets")
    provider = relationship("LLMProvider")

    @property
    def use_case_tags(self) -> list[str]:
        return _string_list(self.use_case_tags_json)

    @use_case_tags.setter
    def use_case_tags(self, value: list[str]):
        self.use_case_tags_json = [str(item).strip() for item in (value or []) if str(item).strip()]

    @property
    def capability_tags(self) -> list[str]:
        return _string_list(self.capability_tags_json)

    @capability_tags.setter
    def capability_tags(self, value: list[str]):
        tags = (str(item).strip() for item in (value or []))
        self.capability_tags_json = list(dict.fromkeys(tag for tag in tags if tag))
