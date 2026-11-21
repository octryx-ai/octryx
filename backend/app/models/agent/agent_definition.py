import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, false
from sqlalchemy.orm import relationship

from ...db import Base
from ...time_utils import utc_now
from ..json_text import dump_json_dict, dump_string_list, safe_json_dict, safe_string_list


def uuid_pk():
    return str(uuid.uuid4())


class AgentDefinition(Base):
    __tablename__ = "agent_definitions"
    __table_args__ = (UniqueConstraint("builtin_key", name="uq_agent_definitions_builtin_key"),)

    id = Column(String(36), primary_key=True, default=uuid_pk)
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=True, index=True)
    group_id = Column(String(36), ForeignKey("agent_groups.id"), nullable=True, index=True)
    runtime_target_id = Column(String(36), ForeignKey("control_plane_runtime_targets.id"), nullable=True, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    goal = Column(Text, default="")
    agent_type = Column(String(50), default="diagnosis")
    thinking_level = Column(String(20), default="light")
    branch_prefix = Column(String(80), default="codex")
    system_prompt = Column(Text, default="")
    output_prompt = Column(Text, default="")
    skill_preferences_json = Column(Text, default="{}")
    require_self_review = Column(Boolean, default=False)
    # governed | none (services/agent_tool_surface.py); none is an enforced text-only boundary.
    tool_surface = Column(String(16), nullable=False, default="governed", server_default="governed")
    # Optional checked reply (services/agent_reply_contract.py): NULL is free text, else canonical JSON.
    reply_contract_json = Column(Text, nullable=True)
    # A built-in agent ships with the platform (``agent_builtins``);
    # the ceiling caps the run class a workflow may give this agent; the default workflow applies when a turn
    # names the agent explicitly and no workflow; the execution mode names the agent's work-item envelope.
    builtin_key = Column(String(40), nullable=True)
    capability_ceiling = Column(String(16), nullable=False, default="read_only", server_default="read_only")
    default_workflow_key = Column(String(180), nullable=True)
    execution_mode = Column(String(40), nullable=True)
    # The runtime preference is matched against the governed runtimes' capability tags; ``chat_selectable`` offers
    # it in the composer; ``tools_deny_json`` only narrows.
    runtime_preference = Column(String(16), nullable=True)
    chat_selectable = Column(Boolean, nullable=False, default=False, server_default=false())
    tools_deny_json = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    owner = relationship("User")
    project = relationship("Project")
    group = relationship("AgentGroup", back_populates="agents")
    runtime_target = relationship("ControlPlaneRuntimeTarget")
    steps = relationship(
        "AgentStep",
        back_populates="agent",
        order_by="AgentStep.position.asc()",
        cascade="all, delete-orphan",
    )

    @property
    def tools_deny(self) -> list[str]:
        return safe_string_list(self.tools_deny_json) if self.tools_deny_json else []

    @property
    def skill_preferences(self) -> dict[str, object]:
        return safe_json_dict(self.skill_preferences_json)

    @skill_preferences.setter
    def skill_preferences(self, value: dict[str, object] | None):
        self.skill_preferences_json = dump_json_dict(value)


class AgentStep(Base):
    __tablename__ = "agent_steps"

    id = Column(String(36), primary_key=True, default=uuid_pk)
    agent_id = Column(String(36), ForeignKey("agent_definitions.id"), nullable=False, index=True)
    position = Column(Integer, nullable=False, default=1)
    name = Column(String(200), nullable=False)
    step_type = Column(String(50), default="analysis")
    instructions = Column(Text, default="")
    success_criteria = Column(Text, default="")
    allowed_tools_json = Column(Text, default="[]")
    step_config_json = Column(Text, default="{}")
    is_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    agent = relationship("AgentDefinition", back_populates="steps")

    @property
    def allowed_tools(self) -> list[str]:
        return safe_string_list(self.allowed_tools_json)

    @allowed_tools.setter
    def allowed_tools(self, value: list[str] | tuple[str, ...] | None):
        self.allowed_tools_json = dump_string_list(value)

    @property
    def step_config(self) -> dict[str, object]:
        return safe_json_dict(self.step_config_json)

    @step_config.setter
    def step_config(self, value: dict[str, object] | None):
        self.step_config_json = dump_json_dict(value)
