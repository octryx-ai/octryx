from __future__ import annotations

from functools import cache

import pytest

from tests.guards._engine_branches import engine_branches
from tests.guards._engine_branches_allowlist import ALLOWED_SPECIAL_CASES
from tests.guards._import_graph import ModuleIndex, app_sources, index_sources
from tests.guards._support import assert_guard, comparison_problems, counted
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")

# The only places allowed to know engines and providers by name.
DRIVER_LAYER = (
    "app/agent/providers/",
    "app/services/model_gateway/litellm/",
    "app/services/model_gateway/inbound/",
    "app/services/agent_gateway/engine_keys.py",
    "app/services/knowledge_embedding/drivers/",
)


@cache
def _repository_index() -> ModuleIndex:
    return index_sources(app_sources())


def special_cases(index: ModuleIndex) -> set[str]:
    modules = [module for module in index.app_modules if not index.paths[module].startswith(DRIVER_LAYER)]
    return counted(engine_branches(index, modules))


def test_engine_special_cases_equal_the_allowlist() -> None:
    assert_guard(special_cases(_repository_index()), ALLOWED_SPECIAL_CASES, what="engine special case")


_PLANTED = '''
ENGINE_PLANTED = "codex"
TOOL_LIMITS = {"openai": 96}


def pick(provider, engine, model):
    if provider == "litellm_gateway":
        return 1
    if engine in (ENGINE_PLANTED, "claude_code"):
        return 2
    match provider:
        case "gemini":
            return 3
    return 4 if model.startswith("anthropic.") else 0
'''


_PLANTED_PATH = "app/services/_guard_planted_branch.py"


def test_mutation_planted_branches_are_reported() -> None:
    found = special_cases(index_sources({**app_sources(), _PLANTED_PATH: _PLANTED}))
    assert {key for key in found if key.startswith(_PLANTED_PATH)} == {
        f"{_PLANTED_PATH}::<module>: {{'openai': ...}}",
        f"{_PLANTED_PATH}::pick: provider == 'litellm_gateway'",
        f"{_PLANTED_PATH}::pick: engine in (ENGINE_PLANTED, 'claude_code')",
        f"{_PLANTED_PATH}::pick: case 'gemini'",
        f"{_PLANTED_PATH}::pick: model.startswith('anthropic.')",
    }
    assert comparison_problems(found, ALLOWED_SPECIAL_CASES, what="engine special case")


def test_mutation_new_branch_on_a_listed_name_in_a_listed_module_is_reported() -> None:
    path = "app/services/devices/seat_quota.py"
    sources = app_sources()
    planted = sources[path] + "\n\ndef _guard_planted(engine):\n    return 1 if engine == ENGINE_CODEX else 0\n"
    found = special_cases(index_sources({**sources, path: planted}))
    assert comparison_problems(found, ALLOWED_SPECIAL_CASES, what="engine special case") == [
        f"new engine special case: {path}::_guard_planted: engine == ENGINE_CODEX",
    ]


def test_mutation_repeated_identical_site_is_counted() -> None:
    planted = "def pick(engine):\n    if engine == 'codex':\n        return 1\n    if engine == 'codex':\n        return 2\n"
    found = special_cases(index_sources({"app/__init__.py": "", "app/picked.py": planted}))
    assert found == {"app/picked.py::pick: engine == 'codex' (x2)"}


def test_mutation_driver_layer_may_branch() -> None:
    sources = {**app_sources(), "app/agent/providers/_guard_planted_branch.py": _PLANTED}
    found = special_cases(index_sources(sources))
    assert not any("_guard_planted_branch" in key for key in found)
