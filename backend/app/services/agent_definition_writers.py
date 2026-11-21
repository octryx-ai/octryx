"""The inventory of Agent Definition aggregate writers.

A published revision is only authoritative if *every* writer of the
live ``AgentDefinition`` / ``AgentStep`` aggregate is accounted for. This module
is that account: one entry per writer, naming the module that owns it, the class
of write it performs, and what the governed boundary does for it.

Each entry names two different module sets, because they answer two different
questions and conflating them hid a gap:

``entry_modules``
    where the governed boundary is *opened*. The guard test reads these modules and
    fails if one of them does not reference
    ``governed_agent_definition_write`` / ``governs_agent_definition_write``, so a
    writer cannot be listed as governed while quietly not using the boundary.

``owner_modules``
    where the aggregate rows are actually constructed or mutated — which for a
    bootstrap writer is a helper module one level below its entry point. These are
    what the tree scan is compared against.

The inventory is pure data with no IO, which is what lets
``tests/test_agent_definition_writer_inventory.py`` assert it statically against
the source tree: a module that constructs, mutates, ``setattr``s, bulk-updates,
deletes, or *reaches through a relationship onto* the aggregate without appearing
here fails that test. Adding a writer is therefore a deliberate act with a recorded
classification, not an accident.

The relationship case is the one that was missed first time round:
``agent_group.crud.delete_agent_group`` never imports ``AgentDefinition``, it walks
``AgentGroup.agents`` and clears ``group_id`` — which is part of the revision
snapshot, so it is an authored-content write like any other.

Two classes exist, and the difference is the actor, not the trust level:

``production``
    An authenticated administrator, an imported package, or a model-facing
    admin tool authors content. The boundary snapshots, validates, and appends
    an immutable **draft** revision plus an audit row. It never publishes and
    never refuses the live write — publication stays a governed human action
    (``publish_revision``), and refusing here would break the panel before any
    UI could explain why.

``bootstrap``
    Shipped repository constants are seeded on application start. There is no
    interactive actor, and the whole shipped catalog is proven publishable by
    ``tests/test_agent_definition_revision_validation.py``. The boundary
    therefore **publishes** revision 1 for these writers, which is what makes
    ``published`` execution mode usable at all. A seed whose snapshot fails
    validation is recorded ``invalid`` and is *not* published; bootstrap
    continues, because a tenant-data defect must not fail application start.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AgentDefinitionWriterClass(StrEnum):
    """How the governed boundary treats a writer's output."""

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
    BOOTSTRAP_BUILTIN_AGENTS = "bootstrap_builtin_agents"
    BOOTSTRAP_SAMPLE_WORKSPACE = "bootstrap_sample_workspace"
    BOOTSTRAP_PLATFORM_AGENTS = "bootstrap_platform_agents"


@dataclass(frozen=True, slots=True)
class AgentDefinitionWriterSpec:
    """One inventory entry. See the module docstring for the two module sets."""

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
        writer=AgentDefinitionWriter.BOOTSTRAP_BUILTIN_AGENTS,
        writer_class=AgentDefinitionWriterClass.BOOTSTRAP,
        entry_modules=("app.services.agent_builtins",),
        owner_modules=("app.services.agent_builtins",),
        description="Startup creation of the built-in Coding agent (A3); no other agent ships as a row.",
    ),
    AgentDefinitionWriterSpec(
        writer=AgentDefinitionWriter.BOOTSTRAP_SAMPLE_WORKSPACE,
        writer_class=AgentDefinitionWriterClass.BOOTSTRAP,
        entry_modules=("app.services.sample_workspace_bootstrap.service",),
        owner_modules=(
            "app.services.sample_workspace_bootstrap.service",
            "app.services.sample_workspace_bootstrap.agent_steps",
        ),
        description="Startup seeding of the Acme Orders workspace definitions.",
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
    """Every module allowed to write the aggregate, lifecycle included."""
    modules = {module for spec in _SPECS for module in spec.owner_modules}
    return frozenset(modules | GOVERNED_LIFECYCLE_MODULES)


def writer_entry_modules() -> frozenset[str]:
    """Every module that must open the governed boundary."""
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
