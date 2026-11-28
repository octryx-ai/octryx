"""Static guard: no ungoverned Agent Definition writer may exist."""

from __future__ import annotations

import pathlib

import pytest

from app.services.agent_definition_writers import (
    GOVERNED_LIFECYCLE_MODULES,
    WRITER_SPECS,
    AgentDefinitionWriter,
    AgentDefinitionWriterClass,
    writer_entry_modules,
    writer_owner_modules,
)
from tests.services.agents.agent_definition_writer_rows_support import aggregate_relationship_names
from tests.support.agent_definition_writer_scan_support import (
    REASON_RELATIONSHIP_WRITE,
    scan_app_tree,
    scan_source,
)

APP_ROOT = pathlib.Path(__file__).resolve().parents[3] / "app"


#: The two functions that open the governed write boundary. An entry module that
#: references neither is registered as governed without being governed.
BOUNDARY_SYMBOLS = ("governed_agent_definition_write", "governs_agent_definition_write")


def _module_source(module: str) -> str:
    path = APP_ROOT.parent / pathlib.Path(*module.split("."))
    candidates = (path.with_suffix(".py"), path / "__init__.py")
    for candidate in candidates:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    raise AssertionError(f"registered module {module} does not exist on disk")


def test_every_aggregate_writer_module_is_registered():
    discovered = scan_app_tree(APP_ROOT)
    unregistered = sorted(set(discovered) - writer_owner_modules())
    assert not unregistered, (
        "these modules write the Agent Definition aggregate but are not in "
        "app.services.agent_definition_writers: "
        f"{ {module: sorted(discovered[module]) for module in unregistered} }"
    )


def test_every_registered_owner_module_still_writes_the_aggregate():
    discovered = set(scan_app_tree(APP_ROOT))
    stale = sorted(
        module
        for module in writer_owner_modules() - GOVERNED_LIFECYCLE_MODULES
        if module not in discovered
    )
    assert not stale, f"registered writers that no longer write the aggregate: {stale}"


@pytest.mark.parametrize("module", sorted(writer_entry_modules()))
def test_every_entry_module_opens_the_governed_boundary(module: str):
    source = _module_source(module)
    assert any(symbol in source for symbol in BOUNDARY_SYMBOLS), (
        f"{module} is registered as a governed writer entry point but references "
        f"neither of {BOUNDARY_SYMBOLS}"
    )


def test_the_agent_group_delete_is_a_registered_relationship_writer():
    module = "app.services.agent_group.crud"
    assert module in writer_entry_modules()
    assert module in writer_owner_modules()
    assert REASON_RELATIONSHIP_WRITE in scan_source(_module_source(module))


def test_the_relationship_names_are_read_off_the_mappers():
    names = aggregate_relationship_names()
    assert {"agents", "steps"} <= names
    # A relationship whose target is not the aggregate must not widen the rule.
    assert "group" not in names
    assert "project" not in names


def test_every_writer_class_has_its_modules_declared():
    for writer, spec in WRITER_SPECS.items():
        assert spec.entry_modules, writer
        assert spec.owner_modules, writer


def test_the_revision_lifecycle_is_the_only_governed_exception():
    assert GOVERNED_LIFECYCLE_MODULES == {"app.services.agent_definition_revisions"}
    assert not GOVERNED_LIFECYCLE_MODULES & {
        module for spec in WRITER_SPECS.values() for module in spec.owner_modules
    }


def test_every_writer_enum_member_has_a_spec():
    assert set(WRITER_SPECS) == set(AgentDefinitionWriter)


def test_only_bootstrap_writers_publish():
    for writer, spec in WRITER_SPECS.items():
        expected = spec.writer_class is AgentDefinitionWriterClass.BOOTSTRAP
        assert spec.publishes is expected, writer
