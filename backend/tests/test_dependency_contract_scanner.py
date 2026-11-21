"""The import scanner classifies synthetic sources: undeclared required, deferred and guarded imports fail, extras and groups satisfy only what they may, and class bodies, handlers and typing-only blocks get their exact kind."""

from __future__ import annotations

from pathlib import Path

import pytest

from dependency_gates.import_contract import (
    DEFERRED,
    GUARDED,
    REQUIRED,
    TYPING_ONLY,
    ImportSite,
    format_findings,
    scan_imports,
    undeclared_imports,
)
from dependency_gates.manifest import canonical_name


def _write(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


@pytest.fixture
def synthetic(tmp_path: Path) -> Path:
    """A minimal project whose declared contract has exactly one base dependency and one extra."""
    _write(
        tmp_path,
        "pyproject.toml",
        '[project]\nname = "probe"\ndependencies = ["declared-base>=1"]\n'
        '\n[project.optional-dependencies]\nfeature = ["declared-extra>=1"]\n'
        '\n[dependency-groups]\ndev = ["declared-dev-group>=1"]\n',
    )
    (tmp_path / "app").mkdir()
    return tmp_path


def _findings(synthetic: Path, source: str) -> dict[str, list[ImportSite]]:
    _write(synthetic, "app/probe.py", source)
    return undeclared_imports(root=synthetic / "app", pyproject_path=synthetic / "pyproject.toml")


def _kinds(synthetic: Path, source: str, distribution: str = "declared-extra") -> set[str]:
    """The kinds the scanner assigns to ``distribution`` in ``source``.

    ``declared-extra`` is the default probe name because the synthetic project declares it as an extra only: an extra
    satisfies ``guarded``/``deferred`` but never ``required``, so the same source doubles as a check of what the
    classification then permits.
    """
    _write(synthetic, "app/probe.py", source)
    return {site.kind for site in scan_imports(synthetic / "app") if site.distribution == canonical_name(distribution)}


# --- negative controls -------------------------------------------------------------------------------------------


def test_a_synthetic_undeclared_module_level_import_fails_the_check(synthetic: Path):
    findings = _findings(synthetic, "import totally_undeclared_dist\n")
    assert list(findings) == ["totally-undeclared-dist"]
    assert findings["totally-undeclared-dist"][0].kind == REQUIRED
    assert "app/probe.py:1" in format_findings(findings)


def test_a_synthetic_undeclared_deferred_import_fails_the_check(synthetic: Path):
    """Lazy `pptx` imports of exactly this shape still crashed at tool-call time."""
    findings = _findings(synthetic, "def use():\n    import lazily_undeclared_dist\n")
    assert list(findings) == ["lazily-undeclared-dist"]
    assert findings["lazily-undeclared-dist"][0].kind == DEFERRED


def test_a_synthetic_undeclared_guarded_import_fails_the_check(synthetic: Path):
    findings = _findings(
        synthetic,
        "try:\n    import guarded_undeclared_dist\nexcept ImportError:\n    guarded_undeclared_dist = None\n",
    )
    assert list(findings) == ["guarded-undeclared-dist"]
    assert findings["guarded-undeclared-dist"][0].kind == GUARDED


def test_an_extra_does_not_satisfy_a_required_import(synthetic: Path):
    """The decision in prose: an extra is not installed, so it cannot cover an import-time dependency."""
    findings = _findings(synthetic, "import declared_extra\n")
    assert list(findings) == ["declared-extra"], "an extra-only declaration must not satisfy a module-level import"


def test_an_extra_satisfies_a_deferred_import(synthetic: Path):
    assert not _findings(synthetic, "def use():\n    import declared_extra\n")


def test_a_dependency_group_satisfies_nothing(synthetic: Path):
    """Dependency groups are development tooling and reach no runtime install path."""
    findings = _findings(synthetic, "def use():\n    import declared_dev_group\n")
    assert list(findings) == ["declared-dev-group"]


def test_a_declared_base_dependency_satisfies_every_import_kind(synthetic: Path):
    assert not _findings(
        synthetic,
        "import declared_base\n\n\ndef use():\n    import declared_base  # noqa: F811\n",
    )


def test_a_type_checking_only_import_is_not_a_dependency(synthetic: Path):
    assert not _findings(
        synthetic,
        "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    import typing_only_dist\n",
    )


def test_the_else_branch_of_a_type_checking_guard_is_not_typing_only(synthetic: Path):
    """`if TYPE_CHECKING: ... else: import x` does execute, so the exemption must not cover the else branch."""
    findings = _findings(
        synthetic,
        "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    pass\nelse:\n    import runtime_only_dist\n",
    )
    assert list(findings) == ["runtime-only-dist"]
    assert findings["runtime-only-dist"][0].kind == REQUIRED


def test_a_bare_except_counts_as_import_error_handling(synthetic: Path):
    """app/services/data_transfer/common.py guards its yaml import with a bare `except Exception`."""
    source = "try:\n    import declared_extra\nexcept Exception:\n    declared_extra = None\n"
    assert _kinds(synthetic, source) == {GUARDED}


def test_an_except_star_handler_guards_the_try_body(synthetic: Path):
    """`except* ImportError` matches a plain ImportError too (PEP 654 wraps it), so it degrades just as gracefully."""
    source = "try:\n    import declared_extra\nexcept* ImportError:\n    declared_extra = None\n"
    assert _kinds(synthetic, source) == {GUARDED}


def test_a_try_without_import_error_handling_does_not_guard(synthetic: Path):
    """Only a handler that can catch a missing import makes the module survive the distribution being absent."""
    source = "try:\n    import declared_extra\nexcept ValueError:\n    declared_extra = None\n"
    assert _kinds(synthetic, source) == {REQUIRED}
    assert list(_findings(synthetic, source)) == ["declared-extra"]


# --- a class body runs at import time ------------------------------------------------------------------------------


def test_a_class_body_import_is_required_not_deferred(synthetic: Path):
    """A class body executes while the module is imported, so an import in one crashes the import."""
    source = "class Probe:\n    import declared_extra\n"
    assert _kinds(synthetic, source) == {REQUIRED}
    findings = _findings(synthetic, source)
    assert list(findings) == ["declared-extra"], "an extra cannot cover an import that runs at import time"
    assert findings["declared-extra"][0].kind == REQUIRED


def test_an_undeclared_class_body_import_fails_the_check(synthetic: Path):
    findings = _findings(synthetic, "class Probe:\n    from classbody_undeclared_dist import thing\n")
    assert list(findings) == ["classbody-undeclared-dist"]
    assert findings["classbody-undeclared-dist"][0].kind == REQUIRED


def test_a_class_body_nested_in_a_function_is_deferred(synthetic: Path):
    """The function is what defers; a class body inside one runs only when the function is called."""
    source = "def build():\n    class Probe:\n        import declared_extra\n    return Probe\n"
    assert _kinds(synthetic, source) == {DEFERRED}
    assert not _findings(synthetic, source)


def test_a_method_body_is_still_deferred(synthetic: Path):
    """The pptx sites are methods; a class body around a function must not make its body eager."""
    source = "class Probe:\n    def use(self):\n        import declared_extra\n        return declared_extra\n"
    assert _kinds(synthetic, source) == {DEFERRED}
    assert not _findings(synthetic, source)


def test_a_guarded_class_body_import_is_guarded(synthetic: Path):
    source = "try:\n    class Probe:\n        import declared_extra\nexcept ImportError:\n    Probe = None\n"
    assert _kinds(synthetic, source) == {GUARDED}
    assert not _findings(synthetic, source)


# --- only the try body is guarded, never the other branches --------------------------------------------------------


def test_an_import_in_an_except_handler_is_not_guarded(synthetic: Path):
    """The handler runs because the guarded attempt already failed; a second missing import there propagates."""
    source = (
        "try:\n    import json\nexcept ImportError:\n    import declared_extra\n"
    )
    assert _kinds(synthetic, source) == {REQUIRED}
    assert list(_findings(synthetic, source)) == ["declared-extra"]


def test_an_import_in_the_else_branch_of_a_try_is_not_guarded(synthetic: Path):
    """`else` runs only when the body raised nothing, which is outside the handler's reach."""
    source = "try:\n    import json\nexcept ImportError:\n    pass\nelse:\n    import declared_extra\n"
    assert _kinds(synthetic, source) == {REQUIRED}
    assert list(_findings(synthetic, source)) == ["declared-extra"]


def test_an_import_in_a_finally_branch_is_not_guarded(synthetic: Path):
    """`finally` runs after the handler is done, so an ImportError raised there still leaves the module."""
    source = "try:\n    import json\nexcept ImportError:\n    pass\nfinally:\n    import declared_extra\n"
    assert _kinds(synthetic, source) == {REQUIRED}
    assert list(_findings(synthetic, source)) == ["declared-extra"]


def test_a_nested_try_inside_a_handler_still_guards_its_own_body(synthetic: Path):
    """The branch rule must not over-reject: a real guard nested in a handler is still a guard."""
    source = (
        "try:\n    import json\nexcept ImportError:\n    try:\n        import declared_extra\n"
        "    except ImportError:\n        declared_extra = None\n"
    )
    assert _kinds(synthetic, source) == {GUARDED}
    assert not _findings(synthetic, source)


def test_relative_and_first_party_imports_are_not_distributions(synthetic: Path):
    assert not _findings(synthetic, "from . import sibling\nfrom ..other import thing\nimport app.config\n")


def test_the_standard_library_is_not_a_distribution(synthetic: Path):
    assert not _findings(synthetic, "import json\nimport asyncio\nfrom pathlib import Path\n")


def test_typing_only_is_never_reported_as_a_site_kind(synthetic: Path):
    _write(synthetic, "app/probe.py", "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    import x_dist\n")
    assert TYPING_ONLY not in {site.kind for site in scan_imports(synthetic / "app")}
