"""The Pydantic AI reachability boundary as a source contract over the real harness package, with a negative per
boundary item; ``--noconftest`` is required because conftest imports ``app.main``."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from dependency_gates.harness_boundary import (
    ALLOWED_FRAMEWORK_IMPORTS,
    APP_ROOT,
    BOUNDARY_PACKAGE,
    FORBIDDEN_MODULE_PREFIXES,
    FORBIDDEN_SYMBOLS,
    forbidden_prefix,
    format_violations,
    scan_boundary,
)
from tests.repo_contracts.harness_boundary_contract_support import BOUNDARY_MODULE, OUTSIDE_MODULE, _rules, _scan


def test_backend_app_keeps_the_framework_inside_the_boundary():
    violations = scan_boundary(APP_ROOT)
    assert violations == [], f"the Pydantic AI boundary is breached:\n{format_violations(violations)}"


def test_the_scan_really_read_the_backend():
    modules = list(APP_ROOT.rglob("*.py"))
    assert len(modules) > 1000, f"expected the full backend/app tree, found only {len(modules)} modules"


def test_the_clean_verdict_covers_the_real_boundary():
    package = APP_ROOT / BOUNDARY_PACKAGE
    sources = {str(path.relative_to(package)): path.read_text(encoding="utf-8") for path in package.rglob("*.py")}
    assert sorted(name for name, text in sources.items() if "from pydantic_graph" in text) == []
    assert [name for name, text in sources.items()
            if re.search(r"^\s*(from|import)\s+pydantic_ai\b", text, re.MULTILINE)] == []


def test_a_provider_import_inside_the_boundary_is_rejected(tmp_path: Path):
    violations = _scan(tmp_path, {BOUNDARY_MODULE: "from pydantic_ai.providers.bedrock import BedrockProvider\n"})
    assert _rules(violations) == {"framework-module", "framework-symbol"}


def test_any_provider_class_is_rejected_even_from_an_allowed_module(tmp_path: Path):
    violations = _scan(tmp_path, {BOUNDARY_MODULE: "from pydantic_ai import Agent, OpenAIProvider\n"})
    assert [violation.rule for violation in violations] == ["framework-symbol"]
    assert "OpenAIProvider" in violations[0].detail


def test_an_allowed_import_outside_the_boundary_package_is_still_rejected(tmp_path: Path):
    violations = _scan(tmp_path, {OUTSIDE_MODULE: "from pydantic_ai import Agent\n"})
    assert _rules(violations) == {"framework-import-site"}


def test_a_bare_framework_import_is_rejected_inside_the_boundary(tmp_path: Path):
    violations = _scan(tmp_path, {BOUNDARY_MODULE: "import pydantic_ai\n"})
    assert _rules(violations) == {"framework-bare-import"}


def test_attribute_reach_into_the_framework_is_rejected(tmp_path: Path):
    source = "import pydantic_ai\n\nprovider = pydantic_ai.providers.bedrock.BedrockProvider()\n"
    violations = _scan(tmp_path, {BOUNDARY_MODULE: source})
    assert _rules(violations) == {"framework-bare-import", "framework-attribute"}


def test_one_attribute_chain_yields_one_violation_naming_the_whole_path(tmp_path: Path):
    source = "import pydantic_ai\n\nprovider = pydantic_ai.providers.bedrock.BedrockProvider()\n"
    violations = _scan(tmp_path, {BOUNDARY_MODULE: source})
    chains = [violation for violation in violations if violation.rule == "framework-attribute"]
    assert len(chains) == 1
    assert "pydantic_ai.providers.bedrock.BedrockProvider" in chains[0].detail


@pytest.mark.parametrize(
    "statement",
    [
        "from pydantic_ai.models.fallback import FallbackModel",
        "from pydantic_ai.providers.gateway import GatewayProvider",
        "from pydantic_ai.mcp import MCPServerStdio",
    ],
)
def test_every_module_the_activation_boundary_names_is_unreachable(tmp_path: Path, statement: str):
    violations = _scan(tmp_path, {BOUNDARY_MODULE: f"{statement}\n"})
    assert "framework-module" in _rules(violations)


def test_a_forbidden_symbol_of_an_allowed_module_is_rejected(tmp_path: Path):
    violations = _scan(tmp_path, {BOUNDARY_MODULE: "from pydantic_ai.models import Model, infer_model\n"})
    assert [violation.rule for violation in violations] == ["framework-symbol"]
    assert "infer_model" in violations[0].detail


def test_the_graph_framework_is_not_open_anywhere(tmp_path: Path):
    violations = _scan(tmp_path, {BOUNDARY_MODULE: "from pydantic_graph import GraphBuilder\n"})
    assert violations, "the graph framework has no allowed names any more"


def test_an_unlisted_framework_module_is_rejected_rather_than_assumed_safe(tmp_path: Path):
    violations = _scan(tmp_path, {BOUNDARY_MODULE: "from pydantic_ai.direct import model_request\n"})
    assert _rules(violations) == {"framework-module"}


def test_the_governed_adapter_shape_passes(tmp_path: Path):
    source = (
        "from pydantic_ai import Agent, RunContext, ToolDefinition\n"
        "from pydantic_ai.messages import ModelMessage\n"
        "from pydantic_ai.models import Model, ModelRequestParameters, StreamedResponse\n"
        "from pydantic_ai.settings import ModelSettings\n"
        "from pydantic_ai.toolsets import AbstractToolset, ToolsetTool\n"
        "from pydantic_ai.usage import RunUsage\n"
        "\n"
        "\n"
        "class OctryxModel(Model):\n"
        "    '''Wraps the Octryx model closure; constructs no framework provider.'''\n"
        "\n"
        "\n"
        "class GovernedToolset(AbstractToolset):\n"
        "    '''Wraps the governed tool closure.'''\n"
        "\n"
        "\n"
        "def build(model: Model, toolset: AbstractToolset) -> Agent:\n"
        "    agent = Agent(model, toolsets=[toolset])\n"
        "    agent.instrument = False\n"
        "    return agent\n"
    )
    violations = _scan(tmp_path, {BOUNDARY_MODULE: source})
    assert violations == [], format_violations(violations)


def test_no_allowed_module_sits_under_aforbidden_prefix():
    for module in ALLOWED_FRAMEWORK_IMPORTS:
        assert forbidden_prefix(module) is None, module


def test_aforbidden_prefix_ending_in_a_dot_covers_submodules_only():
    assert forbidden_prefix("pydantic_ai.models") is None
    assert forbidden_prefix("pydantic_ai.models.fallback") is not None
    assert forbidden_prefix("pydantic_ai.providers") is not None


def test_the_contract_is_not_empty():
    assert ALLOWED_FRAMEWORK_IMPORTS and FORBIDDEN_MODULE_PREFIXES and FORBIDDEN_SYMBOLS


def test_every_forbidden_symbol_names_the_boundary_item_it_protects():
    assert all(reason.strip() for reason in FORBIDDEN_SYMBOLS.values())
