"""The harness boundary reads no ambient credentials or process environment and keeps telemetry, dynamic imports and instrumentation switched off."""

from __future__ import annotations

from pathlib import Path

import pytest

from dependency_gates.harness_boundary import FRAMEWORK_CREDENTIAL_ENV_NAMES
from tests.harness_boundary_contract_support import BOUNDARY_MODULE, OUTSIDE_MODULE, _rules, _scan

# --- ambient credentials ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "statement",
    ["value = os.environ.get('REGION')", "value = os.environ['REGION']", "value = os.getenv('REGION')"],
)
def test_the_boundary_reads_no_process_environment(tmp_path: Path, statement: str):
    violations = _scan(tmp_path, {BOUNDARY_MODULE: f"import os\n\n{statement}\n"})
    assert _rules(violations) == {"ambient-environment"}


def test_an_unqualified_environment_read_is_caught_too(tmp_path: Path):
    violations = _scan(tmp_path, {BOUNDARY_MODULE: "from os import getenv\n\nvalue = getenv('REGION')\n"})
    assert _rules(violations) == {"ambient-environment"}


@pytest.mark.parametrize(
    "source",
    [
        "import os as operating_system\n\nvalue = operating_system.getenv('REGION')\n",
        "from os import getenv as read_environment\n\nvalue = read_environment('REGION')\n",
        "from os import environ as process_environment\n\nvalue = process_environment['REGION']\n",
    ],
)
def test_environment_aliases_do_not_bypass_the_boundary(tmp_path: Path, source: str):
    violations = _scan(tmp_path, {BOUNDARY_MODULE: source})
    assert _rules(violations) == {"ambient-environment"}


@pytest.mark.parametrize("name", sorted(FRAMEWORK_CREDENTIAL_ENV_NAMES))
def test_no_framework_credential_variable_is_named_in_the_boundary(tmp_path: Path, name: str):
    violations = _scan(tmp_path, {BOUNDARY_MODULE: f'CREDENTIAL = "{name}"\n'})
    assert _rules(violations) == {"ambient-credential-name"}


def test_an_environment_read_outside_the_boundary_is_not_this_contracts_business(tmp_path: Path):
    violations = _scan(tmp_path, {OUTSIDE_MODULE: "import os\n\nvalue = os.getenv('REGION')\n"})
    assert violations == []


# --- telemetry ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("statement", ["import logfire", "import logfire_api", "from logfire import configure"])
def test_logfire_is_unreachable_anywhere_in_the_backend(tmp_path: Path, statement: str):
    violations = _scan(tmp_path, {OUTSIDE_MODULE: f"{statement}\n"})
    assert _rules(violations) == {"telemetry-import"}


def test_opentelemetry_is_unreachable_inside_the_boundary(tmp_path: Path):
    violations = _scan(tmp_path, {BOUNDARY_MODULE: "from opentelemetry import trace\n"})
    assert _rules(violations) == {"telemetry-import"}


def test_opentelemetry_outside_the_boundary_belongs_to_its_own_adoption_gate(tmp_path: Path):
    """OpenTelemetry is `selected_needs_gate` in the component register. This contract does not pre-empt that gate."""
    violations = _scan(tmp_path, {OUTSIDE_MODULE: "from opentelemetry import trace\n"})
    assert violations == []


def test_the_instrumentation_switch_may_only_be_the_literal_false(tmp_path: Path):
    source = "from pydantic_ai import Agent\n\nagent = Agent(model, instrument=True)\n"
    violations = _scan(tmp_path, {BOUNDARY_MODULE: source})
    assert _rules(violations) == {"telemetry-instrumentation"}


def test_agent_construction_must_disable_instrumentation_explicitly(tmp_path: Path):
    source = "from pydantic_ai import Agent as HarnessAgent\n\nagent = HarnessAgent(model)\n"
    violations = _scan(tmp_path, {BOUNDARY_MODULE: source})
    assert _rules(violations) == {"telemetry-instrumentation"}


@pytest.mark.parametrize(
    "source",
    [
        "import importlib\n\nmodule = importlib.import_module('pydantic_ai.providers.bedrock')\n",
        "from importlib import import_module\n\nmodule = import_module('pydantic_ai')\n",
        "module = __import__('pydantic_ai')\n",
    ],
)
def test_dynamic_import_mechanisms_are_unreachable_inside_the_boundary(tmp_path: Path, source: str):
    violations = _scan(tmp_path, {BOUNDARY_MODULE: source})
    assert "dynamic-import" in _rules(violations)


def test_an_explicitly_disabled_instrumentation_switch_passes(tmp_path: Path):
    source = "from pydantic_ai import Agent\n\nagent = Agent(model)\nagent.instrument = False\n"
    assert _scan(tmp_path, {BOUNDARY_MODULE: source}) == []


def test_the_removed_constructor_keyword_does_not_count_as_switching_instrumentation_off(tmp_path: Path):
    """Pydantic AI 2.51 has no `instrument=` keyword; only the attribute on the constructed instance counts."""
    source = "from pydantic_ai import Agent\n\nagent = Agent(model, instrument=False)\n"
    violations = _scan(tmp_path, {BOUNDARY_MODULE: source})
    assert _rules(violations) == {"telemetry-instrumentation"}


@pytest.mark.parametrize(
    "source",
    [
        "from pydantic_ai import Agent\n\nagent = Agent(model)\nagent.instrument = True\n",
        "from pydantic_ai import Agent\n\nagent = Agent(model)\nagent.instrument = False\nAgent.instrument_all()\n",
    ],
)
def test_instrumentation_cannot_be_switched_on_afterwards(tmp_path: Path, source: str):
    violations = _scan(tmp_path, {BOUNDARY_MODULE: source})
    assert _rules(violations) == {"telemetry-instrumentation"}


@pytest.mark.parametrize(
    "statement",
    ["from genai_prices import UpdatePrices\n", "import genai_prices\n", "from pydantic_ai.prices import update\n"],
)
def test_the_price_data_updater_is_unreachable_inside_the_boundary(tmp_path: Path, statement: str):
    violations = _scan(tmp_path, {BOUNDARY_MODULE: statement})
    assert _rules(violations) & {"price-data-import", "framework-module"}
