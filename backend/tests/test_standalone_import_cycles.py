"""Modules prone to import cycles import standalone."""

import importlib

import pytest


@pytest.mark.parametrize(
    "module_path",
    [
        "app.services.request_analysis.contract",
    ],
)
def test_module_imports_standalone(module_path: str) -> None:
    # In-process import_module only approximates a clean interpreter; the guard is the absence of a
    # partially-initialized-module ImportError when the module is imported first.
    module = importlib.import_module(module_path)
    assert module is not None
