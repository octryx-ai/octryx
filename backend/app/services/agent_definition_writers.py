"""The inventory of Agent Definition aggregate writers. A published revision is authoritative only if every writer of
the live aggregate is listed here."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AgentDefinitionWriterClass(StrEnum):
    PRODUCTION = "production"
    BOOTSTRAP = "bootstrap"


class AgentDefinitionWriter(StrEnum):
    """Every writer of the live aggregate, by stable audit key."""

    PANEL_AGENT_CRUD = "panel_agent_crud"
    PANEL_AGENT_GROUP_DELETE = "panel_agent_group_delete"
    PACKAGE_IMPORT = "package_import"
    ADMIN_TOOL_CREATE = "admin_tool_create"
    ADMIN_TOOL_UPDATE = "admin_tool_update"
    AGENT_DESIGNER_DOCUMENT = "agent_designer_document"
    BOOTSTRAP_PLATFORM_AGENTS = "bootstrap_platform_agents"


@dataclass(frozen=True, slots=True)
class AgentDefinitionWriterSpec:
    writer: AgentDefinitionWriter
    writer_class: AgentDefinitionWriterClass
    entry_modules: tuple[str, ...]
    owner_modules: tuple[str, ...]
    description: str

    @property
    def publishes(self) -> bool:
        return self.writer_class is AgentDefinitionWriterClass.BOOTSTRAP


_SPECS: tuple[AgentDefinitionWriterSpec, ...] = (
    AgentDefinitionWriterSpec(
        writer=AgentDefinitionWriter.PANEL_AGENT_CRUD,
        writer_class=AgentDefinitionWriterClass.PRODUCTION,
        entry_modules=("app.services.admin.governance.admin_agent_service",),
        owner_modules=("app.services.admin.governance.admin_agent_service",),
        description="Admin panel agent builder: definition and step create/update/delete/reorder.",
    ),
    AgentDefinitionWriterSpec(
        writer=AgentDefinitionWriter.PANEL_AGENT_GROUP_DELETE,
        writer_class=AgentDefinitionWriterClass.PRODUCTION,
        entry_modules=("app.services.agent_group.crud",),
        owner_modules=("app.services.agent_group.crud",),
        description=(
            "Admin panel agent-group delete: detaches every member definition, "
            "which rewrites the checksum-bearing group_id."
        ),
    ),
    AgentDefinitionWriterSpec(
        writer=AgentDefinitionWriter.PACKAGE_IMPORT,
        writer_class=AgentDefinitionWriterClass.PRODUCTION,
        entry_modules=("app.services.export_package.upsert",),
        owner_modules=("app.services.export_package.upsert",),
        description="Import package: upsert a definition and replace its steps.",
    ),
    AgentDefinitionWriterSpec(
        writer=AgentDefinitionWriter.ADMIN_TOOL_CREATE,
        writer_class=AgentDefinitionWriterClass.PRODUCTION,
        entry_modules=("app.tools.admin_impl._admin_agents",),
        owner_modules=("app.tools.admin_impl._admin_agents",),
        description="Model-facing admin_create_agent tool.",
    ),
    AgentDefinitionWriterSpec(
        writer=AgentDefinitionWriter.ADMIN_TOOL_UPDATE,
        writer_class=AgentDefinitionWriterClass.PRODUCTION,
        entry_modules=("app.tools.admin_impl._admin_agents",),
        owner_modules=("app.tools.admin_impl._admin_agents",),
        description="Model-facing admin_update_agent tool.",
    ),
    AgentDefinitionWriterSpec(
        writer=AgentDefinitionWriter.AGENT_DESIGNER_DOCUMENT,
        writer_class=AgentDefinitionWriterClass.PRODUCTION,
        entry_modules=("app.services.agent_designer.service",),
        owner_modules=("app.services.agent_designer.service",),
        description="Visual Agent Designer: replace a definition's header and ordered steps from one document.",
    ),
    AgentDefinitionWriterSpec(
        writer=AgentDefinitionWriter.BOOTSTRAP_PLATFORM_AGENTS,
        writer_class=AgentDefinitionWriterClass.BOOTSTRAP,
        entry_modules=("app.services.platform_agents.seeding",),
        owner_modules=("app.services.platform_agents.seeding",),
        description="Startup seeding of the platform agents Assistant, Engineer and Reviewer.",
    ),
)

WRITER_SPECS: dict[AgentDefinitionWriter, AgentDefinitionWriterSpec] = {
    spec.writer: spec for spec in _SPECS
}

#: The revision lifecycle itself writes the aggregate when restoring a published
#: revision. It *is* the governed boundary, so it is listed separately
#: rather than as a writer that has to pass through the boundary again.
GOVERNED_LIFECYCLE_MODULES: frozenset[str] = frozenset(
    {"app.services.agent_definition_revisions"}
)


def writer_spec(writer: AgentDefinitionWriter) -> AgentDefinitionWriterSpec:
    spec = WRITER_SPECS.get(writer)
    if spec is None:  # pragma: no cover - the enum and the table are one unit
        raise KeyError(f"unregistered agent definition writer: {writer!r}")
    return spec


def writer_owner_modules() -> frozenset[str]:
    modules = {module for spec in _SPECS for module in spec.owner_modules}
    return frozenset(modules | GOVERNED_LIFECYCLE_MODULES)


def writer_entry_modules() -> frozenset[str]:
    return frozenset(module for spec in _SPECS for module in spec.entry_modules)


__all__ = [
    "GOVERNED_LIFECYCLE_MODULES",
    "writer_entry_modules",
    "WRITER_SPECS",
    "AgentDefinitionWriter",
    "AgentDefinitionWriterClass",
    "AgentDefinitionWriterSpec",
    "writer_owner_modules",
    "writer_spec",
]
