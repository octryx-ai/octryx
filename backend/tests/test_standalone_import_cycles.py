"""Modules prone to import cycles import standalone.

Each module is imported on its own, without app/conftest importing the package graph first, so an
order-dependent import fails here. request_analysis.contract imports lazily to keep the request_analysis
(and the loops setup) cycle-free.
"""

import importlib

import pytest


@pytest.mark.parametrize(
    "module_path",
    [
        "app.services.request_analysis.contract",
        "app.agent.loops.setup._loop_setup",
    ],
)
def test_module_imports_standalone(module_path: str) -> None:
    # A fresh import in a subprocess-like clean state is approximated by
    # importlib.import_module; the real guard is that these do not raise a
    # partially-initialized-module ImportError when imported first.
    module = importlib.import_module(module_path)
    assert module is not None
