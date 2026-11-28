from __future__ import annotations

import ast
from collections import defaultdict
from collections.abc import Iterable
from functools import cache

import pytest

from tests.guards._dynamic_loaders import detected_sites, dynamic_edges, modelled_sites
from tests.guards._import_graph import ENTRY_FILE_PREFIX, ModuleIndex, app_sources, index_sources, reachable
from tests.guards._support import BACKEND, REPO_ROOT, Accepted, Allowed, comparison_problems, entry_problems
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")

# Process entry points: images, compose, dev-start.sh, `-m` subprocesses and operator CLIs.
ENTRY_MODULES = (
    "app.main",
    "app.worker_main",
    "app.code_indexer_main",
    "app.services.office.render_server",
    "app.services.python_runtime_entrypoint",
    "app.services.browser_runtime_entrypoint",
    "app.services.office.neutral_presentation_template",
    "app.services.knowledge.eval.run",
    "app.services.knowledge.eval.library_run",
    "app.services.knowledge.eval.change_typing",
)

ENTRY_FILE_GLOBS = (
    "backend/alembic/env.py",
    "backend/alembic/versions/*.py",
    "backend/scripts/*.py",
    "backend/regen_guides.py",
    "deployment/demo/seed_demo.py",
)


ALLOWED_UNREACHED: tuple[Allowed | Accepted, ...] = (
    Accepted("app.services.workflow_runs.seeds",
             "the package marker of a data folder (the phased-workflow JSON seeds, read by path from "
             "workflow_runs.seeding)"),
)

# Data folders need a package marker; the exemption holds only while the marker carries no code.
DATA_PACKAGE_MARKERS = ("app/services/workflow_runs/seeds/__init__.py",)


def entry_files() -> dict[str, str]:
    files = {}
    for pattern in ENTRY_FILE_GLOBS:
        for path in sorted(REPO_ROOT.glob(pattern)):
            files[path.relative_to(BACKEND, walk_up=True).as_posix()] = path.read_text(encoding="utf-8")
    return files


def unreached(index: ModuleIndex) -> set[str]:
    roots = [*ENTRY_MODULES, *(name for name in index.trees if name.startswith(ENTRY_FILE_PREFIX))]
    return index.app_modules - reachable(index, roots, dynamic_edges(index))


def by_package(modules: Iterable[str]) -> list[str]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for module in sorted(modules):
        package, _, name = module.rpartition(".")
        grouped[package].append(name)
    return [f"{package}: {', '.join(names)}" for package, names in sorted(grouped.items())]


def marker_problems(sources: dict[str, str]) -> list[str]:
    problems = []
    for path in DATA_PACKAGE_MARKERS:
        body = ast.parse(sources[path]).body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            body = body[1:]
        if body:
            problems.append(f"data package marker holds code: {path}")
    return problems


@cache
def _repository_index() -> ModuleIndex:
    return index_sources({**app_sources(), **entry_files()})


def test_entry_points_exist() -> None:
    index = _repository_index()
    assert [module for module in ENTRY_MODULES if module not in index.trees] == []
    assert len(entry_files()) >= len(ENTRY_FILE_GLOBS)


def test_every_dynamic_loader_is_modelled() -> None:
    sites = {f"{module}: {kind}" for module, kind in detected_sites(_repository_index())}
    problems = comparison_problems(sites, [Accepted(f"{m}: {k}", "") for m, k in modelled_sites()],
                                   what="dynamic loader (model it in _dynamic_loaders)")
    assert not problems, "\n".join(problems)


def test_unreached_modules_equal_the_allowlist() -> None:
    found = unreached(_repository_index())
    new = found - {entry.key for entry in ALLOWED_UNREACHED}
    problems = entry_problems(ALLOWED_UNREACHED) + comparison_problems(found, ALLOWED_UNREACHED, what="unreached module")
    assert not problems, "\n  ".join([f"{len(problems)} unreached module guard problem(s):", *problems,
                                      "new unreached modules by package:", *by_package(new)])


def test_mutation_orphan_module_is_reported() -> None:
    sources = {**app_sources(), **entry_files(), "app/services/_guard_planted_orphan.py": "VALUE = 1\n"}
    found = unreached(index_sources(sources))
    assert "app.services._guard_planted_orphan" in found
    assert comparison_problems(found, ALLOWED_UNREACHED, what="unreached module")


def test_mutation_unmodelled_dynamic_loader_is_reported() -> None:
    planted = "import importlib\n\ndef load(name):\n    return importlib.import_module(name)\n"
    sources = {**app_sources(), **entry_files(), "app/services/_guard_planted_loader.py": planted}
    sites = detected_sites(index_sources(sources))
    assert ("app.services._guard_planted_loader", "computed import_module") in sites - modelled_sites()


def test_mutation_import_from_entry_point_reaches_the_module() -> None:
    sources = {
        "app/__init__.py": "",
        "app/main.py": "from app import used\n",
        "app/used.py": "import importlib\nX = importlib.import_module('app.lazy')\n",
        "app/lazy.py": "",
        "app/dead.py": "",
    }
    assert unreached(index_sources(sources)) == {"app.dead"}


def test_mutation_orphan_inside_a_listed_package_is_reported() -> None:
    sources = {**app_sources(), **entry_files(), "app/services/knowledge/retention/_guard_planted.py": "VALUE = 1\n"}
    found = unreached(index_sources(sources))
    assert comparison_problems(found, ALLOWED_UNREACHED, what="unreached module") == [
        "new unreached module: app.services.knowledge.retention._guard_planted",
    ]


def test_mutation_python_code_in_the_seed_data_package_is_reported() -> None:
    sources = {**app_sources(), **entry_files(), "app/services/workflow_runs/seeds/loader.py": "VALUE = 1\n"}
    found = unreached(index_sources(sources))
    assert comparison_problems(found, ALLOWED_UNREACHED, what="unreached module") == [
        "new unreached module: app.services.workflow_runs.seeds.loader",
    ]


def test_data_package_markers_hold_no_code() -> None:
    assert marker_problems(app_sources()) == []


def test_mutation_code_in_the_seed_marker_is_reported() -> None:
    sources = {**app_sources(), DATA_PACKAGE_MARKERS[0]: '"""Seeds."""\n\ndef orphan():\n    return 1\n'}
    assert marker_problems(sources) == [f"data package marker holds code: {DATA_PACKAGE_MARKERS[0]}"]
