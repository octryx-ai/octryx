"""No import cycle runs when the app loads, and the cycle of packages (imports inside functions included) never grows."""

from __future__ import annotations

import warnings

from tests.guards._import_cycles import PACKAGE_CYCLE_BASELINE, import_time_cycles, largest_package_cycle
from tests.guards._import_graph import app_sources, index_sources


def test_no_module_level_import_cycle() -> None:
    assert import_time_cycles(index_sources(app_sources())) == []


def test_the_package_cycle_only_shrinks() -> None:
    size = len(largest_package_cycle(index_sources(app_sources())))
    assert size <= PACKAGE_CYCLE_BASELINE, f"the package cycle grew to {size}: break the new import instead"
    if size < PACKAGE_CYCLE_BASELINE:
        warnings.warn(f"can be lowered: PACKAGE_CYCLE_BASELINE {PACKAGE_CYCLE_BASELINE} -> {size}", stacklevel=1)


def test_mutation_two_modules_importing_each_other_at_load_are_a_cycle() -> None:
    index = index_sources({"app/__init__.py": "", "app/a.py": "from app import b\n", "app/b.py": "from . import a\n"})
    assert import_time_cycles(index) == [["app.a", "app.b"]]


def test_mutation_an_import_inside_a_function_or_for_type_checking_is_no_load_cycle() -> None:
    index = index_sources({"app/__init__.py": "", "app/a.py": "def f():\n    from app import b\n",
                           "app/b.py": "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from app import a\n"
                                       "from app import a\n"})
    assert import_time_cycles(index) == []


def test_mutation_a_package_loading_its_own_submodules_is_no_cycle() -> None:
    index = index_sources({"app/__init__.py": "", "app/pkg/__init__.py": "from .mod import X\n",
                           "app/pkg/mod.py": "from app.pkg import helper\nX = 1\n", "app/pkg/helper.py": ""})
    assert import_time_cycles(index) == []


def test_mutation_a_lazy_import_closing_a_loop_joins_the_package_cycle() -> None:
    index = index_sources({"app/__init__.py": "", "app/services/__init__.py": "",
                           "app/services/one.py": "from app.services import two\n",
                           "app/services/two.py": "def f():\n    from app.services import one\n"})
    assert largest_package_cycle(index) == ["app.services.one", "app.services.two"]
